import { useState, useCallback } from 'react'
import useStore from '../stores/useStore'
import WorkflowNode from './WorkflowNode'
import LlmLogPanel from './LlmLogPanel'
import { pauseTask, resumeTask } from '../utils/api'

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

    const [showModify, setShowModify] = useState(false)
    const [modification, setModification] = useState('')
    const [activeDetailIdx, setActiveDetailIdx] = useState(null)
    const [expandedHistory, setExpandedHistory] = useState(null)
    const [paused, setPaused] = useState(false)
    const [editingOutput, setEditingOutput] = useState(false)
    const [editContent, setEditContent] = useState('')
    const [reviewLoading, setReviewLoading] = useState(false)

    const sendReviewAction = useCallback(async (action) => {
        setReviewLoading(true)
        useStore.setState({ reviewingStepId: null, reviewNextStep: null })

        try {
            const res = await fetch('/api/task/answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ answer: action, session_id: activeSessionId }),
            })
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

    // 没有 plan 也没有历史时显示空状态
    if (!plan && workflowSteps.length === 0 && workflowHistory.length === 0) {
        return (
            <div className="workflow">
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
            {/* 当前计划 */}
            {(plan?.steps?.length > 0 || workflowSteps.length > 0) && (
                <>
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
                </>
            )}

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
