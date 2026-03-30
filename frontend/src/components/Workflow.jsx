import { useState, useCallback, useEffect } from 'react'
import useStore from '../stores/useStore'
import WorkflowNode from './WorkflowNode'
import LlmLogPanel from './LlmLogPanel'
import { pauseTask, resumeTask, updateAgentConfig, fetchAgentConfig } from '../utils/api'

export default function Workflow() {
    const plan = useStore(s => s.plan)
    const workflowSteps = useStore(s => s.workflowSteps)
    const waitingConfirm = useStore(s => s.waitingConfirm)
    const confirmPlan = useStore(s => s.confirmPlan)
    const agentThinking = useStore(s => s.agentThinking)
    const workflowHistory = useStore(s => s.workflowHistory)
    const reviewingStepId = useStore(s => s.reviewingStepId)
    const reviewNextStep = useStore(s => s.reviewNextStep)
    const handleAgentEvent = useStore(s => s.handleAgentEvent)
    const activeSessionId = useStore(s => s.activeSessionId)
    const agentConfig = useStore(s => s.agentConfig)
    const setAgentConfig = useStore(s => s.setAgentConfig)
    const isStreamingMap = useStore(s => s.isStreamingMap)
    const addToast = useStore(s => s.addToast)

    const [showModify, setShowModify] = useState(false)
    const [modification, setModification] = useState('')
    const [activeDetailIdx, setActiveDetailIdx] = useState(null)
    const [expandedHistory, setExpandedHistory] = useState(null)
    const [paused, setPaused] = useState(false)
    const [editingOutput, setEditingOutput] = useState(false)
    const [editContent, setEditContent] = useState('')
    const [reviewLoading, setReviewLoading] = useState(false)
    const [modelSaving, setModelSaving] = useState(false)

    // 当前 orchestrator 模型
    const currentRoleModel = agentConfig?.role_models?.orchestrator || ''
    const currentParts = currentRoleModel.split('/')
    const currentProvider = currentParts[0] || ''
    const currentModel = currentParts.slice(1).join('/') || ''

    // 可用的提供商和模型
    const availableProviders = agentConfig?.available_providers || {}
    const providerKeys = Object.keys(availableProviders)
    const currentProviderModels = availableProviders[currentProvider]?.models || []

    // 是否正在执行任务
    const isExecuting = activeSessionId ? (isStreamingMap[activeSessionId] || false) : false
    const hasActivePlan = plan?.steps?.length > 0 || workflowSteps.length > 0

    const handleProviderChange = async (newProvider) => {
        const firstModel = availableProviders[newProvider]?.models?.[0] || ''
        if (!firstModel) return
        await applyModelChange(newProvider, firstModel)
    }

    const handleModelChange = async (newModel) => {
        await applyModelChange(currentProvider, newModel)
    }

    const applyModelChange = async (provider, model) => {
        const newRoleModel = `${provider}/${model}`
        setModelSaving(true)
        try {
            // 更新所有角色的模型
            const newRoleModels = {}
            if (agentConfig?.role_models) {
                for (const role of Object.keys(agentConfig.role_models)) {
                    newRoleModels[role] = newRoleModel
                }
            } else {
                newRoleModels['orchestrator'] = newRoleModel
            }
            const result = await updateAgentConfig(newRoleModels)
            // 更新本地 agentConfig
            setAgentConfig({
                ...agentConfig,
                role_models: result.role_models || newRoleModels,
            })
            addToast(`模型已切换为 ${model}`, 'success')
        } catch (e) {
            addToast('模型切换失败: ' + e.message, 'error')
        } finally {
            setModelSaving(false)
        }
    }

    const sendReviewAction = useCallback(async (action) => {
        setReviewLoading(true)
        useStore.setState({ reviewingStepId: null, reviewNextStep: null })

        try {
            const token = localStorage.getItem('auth_token')
            const headers = { 'Content-Type': 'application/json' }
            if (token) headers['Authorization'] = `Bearer ${token}`

            const res = await fetch('/api/task/answer', {
                method: 'POST',
                headers,
                body: JSON.stringify({ answer: action, session_id: activeSessionId }),
            })
            
            if (res.status === 401) {
                useStore.setState({ isAuthModalOpen: true }) // Handle 401 generically or let handleLogin take over
                return
            }
            const reader = res.body.getReader()
            const decoder = new TextDecoder()
            let buffer = ''
            while (true) {
                const { done, value } = await reader.read()
                if (done) break
                buffer += decoder.decode(value, { stream: true })
                const lines = buffer.split('\n')
                buffer = lines.pop() || ''
                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue
                    try {
                        const event = JSON.parse(line.slice(6))
                        if (event.type === 'stream_end') break
                        handleAgentEvent(event)
                    } catch {}
                }
            }
        } catch (err) {
            console.error('Review action failed:', err)
        } finally {
            setReviewLoading(false)
            setEditingOutput(false)
            setEditContent('')
        }
    }, [activeSessionId, handleAgentEvent])

    // 提供商显示名映射
    const providerLabels = {
        anthropic: '⬡ Anthropic (Claude)',
        google: '◈ Google (Gemini)',
        openai: '○ DeepSeek / OpenAI',
        doubao: '☁️ Doubao (火山)',
        dashscope: '🔮 DashScope (百炼)',
        xiaomi: '📱 Xiaomi (Mimo)',
    }

    // 模型选择器组件
    const ModelSelector = () => (
        <div className="agent-model-selector">
            <div className="agent-model-header">
                <span className="agent-model-label">🤖 Agent 模型</span>
                {modelSaving && <span className="agent-model-saving">保存中...</span>}
            </div>
            <div className="agent-model-selects">
                <select
                    className="form-select agent-model-provider"
                    value={currentProvider}
                    onChange={e => handleProviderChange(e.target.value)}
                    disabled={isExecuting || modelSaving}
                >
                    {providerKeys.map(p => (
                        <option key={p} value={p}>{providerLabels[p] || p}</option>
                    ))}
                </select>
                <select
                    className="form-select agent-model-model"
                    value={currentModel}
                    onChange={e => handleModelChange(e.target.value)}
                    disabled={isExecuting || modelSaving}
                >
                    {currentProviderModels.map(m => (
                        <option key={m} value={m}>{m}</option>
                    ))}
                </select>
            </div>
        </div>
    )

    // 没有 plan 也没有历史时显示空状态
    if (!plan && workflowSteps.length === 0 && workflowHistory.length === 0) {
        return (
            <div className="workflow">
                {agentConfig && <ModelSelector />}
                <div className="workflow-empty">
                    <div className="workflow-empty-icon">🧠</div>
                    <h4>Agent 工作区</h4>
                    <p>发送任务后，编排计划会显示在这里</p>
                </div>
            </div>
        )
    }

    const completed = workflowSteps.filter(s => s.status === 'completed').length
    const failed = workflowSteps.filter(s => s.status === 'failed').length
    const total = workflowSteps.length
    const running = workflowSteps.some(s => s.status === 'running' || s.status === 'paused' || s.status === 'review')

    return (
        <div className="workflow">
            {/* 模型选择器 */}
            {agentConfig && !isExecuting && <ModelSelector />}
                    <div className="workflow-header">
                        <h3>📋 执行计划</h3>
                        {running && (
                            <button
                                className={`step-action-btn ${paused ? 'resume' : 'pause'}`}
                                onClick={async () => {
                                    if (paused) {
                                        await resumeTask()
                                        setPaused(false)
                                    } else {
                                        await pauseTask()
                                        setPaused(true)
                                    }
                                }}
                            >
                                {paused ? '▶ 继续' : '⏸ 暂停'}
                            </button>
                        )}
                        {plan && (
                            <div className="workflow-meta">
                                <span className="workflow-goal">🎯 {plan.goal}</span>
                                <span className="workflow-progress">
                                    {completed + failed}/{total} 步骤
                                    {running && !paused && ' · 🔄 执行中...'}
                                    {paused && ' · ⏸ 已暂停'}
                                    {agentThinking && ` · ${agentThinking}`}
                                </span>
                            </div>
                        )}
                    </div>

                    {/* 确认操作栏 */}
                    {waitingConfirm && (
                        <div className="workflow-confirm-bar">
                            {showModify ? (
                                <div className="plan-modify">
                                    <textarea
                                        value={modification}
                                        onChange={e => setModification(e.target.value)}
                                        placeholder="描述你想要的修改..."
                                        rows={3}
                                    />
                                    <div className="plan-modify-actions">
                                        <button onClick={() => { confirmPlan('modify', modification); setShowModify(false); setModification('') }} className="btn-primary">
                                            提交修改
                                        </button>
                                        <button onClick={() => setShowModify(false)} className="btn-ghost">取消</button>
                                    </div>
                                </div>
                            ) : (
                                <div className="plan-confirm-actions">
                                    <button onClick={() => confirmPlan('confirm')} className="btn-primary">
                                        ▶ 确认执行
                                    </button>
                                    <button onClick={() => setShowModify(true)} className="btn-secondary">
                                        ✏️ 修改
                                    </button>
                                    <button onClick={() => confirmPlan('cancel')} className="btn-ghost">
                                        取消
                                    </button>
                                </div>
                            )}
                        </div>
                    )}

                    {/* 步骤列表 */}
                    <div className="workflow-nodes">
                        {workflowSteps.map((step, idx) => (
                            <div key={step.step_id} className="workflow-node-wrapper">
                                {idx > 0 && <div className="workflow-connector" />}
                                <WorkflowNode
                                    step={step}
                                    isActive={activeDetailIdx === idx}
                                    onClick={() => setActiveDetailIdx(activeDetailIdx === idx ? null : idx)}
                                    showModelSelector={waitingConfirm}
                                />

                                {/* 逐步审查操作栏 */}
                                {reviewingStepId === step.step_id && (
                                    <div className="step-review-bar">
                                        {editingOutput ? (
                                            <div className="step-review-edit">
                                                <textarea
                                                    value={editContent}
                                                    onChange={e => setEditContent(e.target.value)}
                                                    placeholder="修改步骤输出内容..."
                                                    rows={5}
                                                    autoFocus
                                                />
                                                <div className="step-review-edit-actions">
                                                    <button
                                                        className="btn-primary"
                                                        disabled={reviewLoading || !editContent.trim()}
                                                        onClick={() => sendReviewAction(`edit:${editContent}`)}
                                                    >
                                                        {reviewLoading ? '提交中...' : '✅ 提交修改'}
                                                    </button>
                                                    <button
                                                        className="btn-ghost"
                                                        onClick={() => { setEditingOutput(false); setEditContent('') }}
                                                    >
                                                        取消
                                                    </button>
                                                </div>
                                            </div>
                                        ) : (
                                            <>
                                                {reviewNextStep && (
                                                    <div className="step-review-next-preview">
                                                        下一步: <strong>{reviewNextStep.description}</strong>
                                                        <span className="step-review-agent">({reviewNextStep.agent})</span>
                                                    </div>
                                                )}
                                                <div className="step-review-actions">
                                                    <button
                                                        className="btn-primary"
                                                        disabled={reviewLoading}
                                                        onClick={() => sendReviewAction('continue')}
                                                    >
                                                        {reviewLoading ? '执行中...' : '✅ 继续执行'}
                                                    </button>
                                                    <button
                                                        className="btn-secondary"
                                                        disabled={reviewLoading}
                                                        onClick={() => {
                                                            setEditContent(step.output || '')
                                                            setEditingOutput(true)
                                                        }}
                                                    >
                                                        ✏️ 修改输出
                                                    </button>
                                                    <button
                                                        className="btn-warning"
                                                        disabled={reviewLoading}
                                                        onClick={() => sendReviewAction('retry')}
                                                    >
                                                        🔄 重新执行
                                                    </button>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

            {/* LLM 调用日志 */}
            <LlmLogPanel />

            {/* 历史工作流 */}
            {workflowHistory.length > 0 && (
                <div className="workflow-history">
                    <div className="workflow-history-title">
                        📜 历史工作流 ({workflowHistory.length})
                    </div>
                    {workflowHistory.map((h, hi) => (
                        <div
                            key={hi}
                            className={`workflow-history-item ${expandedHistory === hi ? 'expanded' : ''}`}
                        >
                            <div
                                className="workflow-history-header"
                                onClick={() => setExpandedHistory(expandedHistory === hi ? null : hi)}
                            >
                                <span className="workflow-history-goal">
                                    🎯 {h.plan?.goal || '任务'}
                                </span>
                                <span className="workflow-history-meta">
                                    {h.steps?.filter(s => s.status === 'completed').length}/{h.steps?.length} ✅
                                    {' · '}
                                    {expandedHistory === hi ? '▲' : '▼'}
                                </span>
                            </div>
                            {expandedHistory === hi && h.steps && (
                                <div className="workflow-history-steps">
                                    {h.steps.map((step, si) => (
                                        <WorkflowNode
                                            key={step.step_id || si}
                                            step={{
                                                ...step,
                                                step_id: step.step_id || si,
                                                status: step.status || 'completed',
                                                elapsed: step.elapsed || 0,
                                                tokens: step.tokens || 0,
                                                input: step.input || {},
                                                output: step.output || '',
                                            }}
                                            isActive={activeDetailIdx === `h${hi}_${si}`}
                                            onClick={() => setActiveDetailIdx(
                                                activeDetailIdx === `h${hi}_${si}` ? null : `h${hi}_${si}`
                                            )}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
