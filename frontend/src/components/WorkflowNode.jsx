import useStore from '../stores/useStore'
import { streamRetryStep } from '../utils/api'

const AGENT_ICONS = {
    web_search: '🔍', analysis: '📊',
    writing: '📝', interview: '🎤',
}

const AGENT_LABELS = {
    web_search: '网络搜索', analysis: '分析整合',
    writing: '文档撰写', interview: '用户访谈',
}

const STATUS_STYLES = {
    pending: { icon: '⏳', className: 'pending', label: '等待中' },
    running: { icon: '🔄', className: 'running', label: '执行中' },
    completed: { icon: '✅', className: 'completed', label: '已完成' },
    warning: { icon: '⚠️', className: 'warning', label: '数据不足' },
    failed: { icon: '❌', className: 'failed', label: '失败' },
}

export default function WorkflowNode({ step, isActive, onClick, showModelSelector = false }) {
    const config = useStore(s => s.config)
    const stepModels = useStore(s => s.stepModels)
    const setStepModel = useStore(s => s.setStepModel)
    const handleAgentEvent = useStore(s => s.handleAgentEvent)
    const addToast = useStore(s => s.addToast)

    const agentIcon = AGENT_ICONS[step.agent] || '❓'
    const agentLabel = AGENT_LABELS[step.agent] || step.agent
    const statusInfo = STATUS_STYLES[step.status] || STATUS_STYLES.pending
    const canExpand = step.status !== 'pending'
    const isExpanded = isActive && canExpand
    const currentModel = stepModels[step.step_id] || ''
    const roleModel = config?.role_models?.[step.agent] || config?.role_models?.orchestrator || ''

    const getAvailableModels = () => {
        if (!config?.providers) return []
        const models = []
        for (const [prov, info] of Object.entries(config.providers)) {
            for (const m of (info.models || [])) {
                models.push(`${prov}/${m}`)
            }
        }
        return models
    }

    const handleRetry = (e) => {
        e.stopPropagation()
        streamRetryStep(step.step_id, {
            onEvent: handleAgentEvent,
            onFinish: () => addToast(`步骤 "${agentLabel}" 重试完成`, 'success'),
            onError: (err) => addToast('重试失败: ' + err, 'error'),
        })
    }

    // 生成 output 预览（未展开时显示前 120 字符）
    const outputPreview = step.output
        ? step.output.replace(/[#*\[\]`]/g, '').slice(0, 120).trim()
        : ''

    return (
        <div className={`workflow-node ${statusInfo.className}`} onClick={onClick}>
            <div className="workflow-node-header">
                <span className="workflow-node-status">{statusInfo.icon}</span>
                <span className="workflow-node-icon">{agentIcon}</span>
                <div className="workflow-node-title">
                    <strong>{agentLabel}</strong>
                    <span className="workflow-node-desc">{step.description}</span>
                </div>
                {/* 步骤操作按钮 */}
                <div className="workflow-node-actions" onClick={e => e.stopPropagation()}>
                    {step.status === 'failed' && (
                        <button className="step-action-btn retry" onClick={handleRetry} title="重试此步骤">
                            🔄 重试
                        </button>
                    )}
                </div>
                {canExpand && (
                    <span className="workflow-node-toggle">{isExpanded ? '▲' : '▼'}</span>
                )}
                {step.elapsed > 0 && (
                    <span className="workflow-node-time">{step.elapsed.toFixed(1)}s</span>
                )}
            </div>

            {/* 摘要信息条 — 未展开时也显示关键信息 */}
            {step.status !== 'pending' && !isExpanded && (
                <div className="workflow-node-summary">
                    {step.tokens > 0 && <span className="summary-chip">🪙 {step.tokens}</span>}
                    {step.elapsed > 0 && <span className="summary-chip">⏱ {step.elapsed.toFixed(1)}s</span>}
                    {step.reflectQuality && (
                        <span className={`summary-chip quality-${step.reflectQuality}`}>
                            {step.reflectQuality === 'good' ? '✅ 质量良好' :
                             step.reflectQuality === 'poor' ? '🔄 已重试' :
                             '⚠️ 无数据'}
                        </span>
                    )}
                    {roleModel && <span className="summary-chip model-chip">🤖 {roleModel.split('/').pop()}</span>}
                </div>
            )}

            {/* 未展开时的 output 预览 */}
            {outputPreview && !isExpanded && (
                <div className="workflow-node-preview">
                    {outputPreview}{step.output.length > 120 ? '...' : ''}
                </div>
            )}

            {/* 模型选择器 */}
            {showModelSelector && step.status === 'pending' && (
                <div className="workflow-node-model" onClick={e => e.stopPropagation()}>
                    <label>模型:</label>
                    <select
                        value={currentModel}
                        onChange={e => setStepModel(step.step_id, e.target.value)}
                    >
                        <option value="">{roleModel || '当前默认模型'}</option>
                        {getAvailableModels()
                            .filter(m => m !== roleModel)
                            .map(m => (
                            <option key={m} value={m}>{m}</option>
                        ))}
                    </select>
                </div>
            )}

            {/* 展开的完整详情 */}
            {isExpanded && (
                <div className="workflow-node-details" onClick={e => e.stopPropagation()}>
                    {/* 元信息栏 */}
                    <div className="workflow-node-meta-bar">
                        {roleModel && <span className="meta-item">🤖 {roleModel}</span>}
                        {step.tokens > 0 && <span className="meta-item">🪙 {step.tokens} tokens</span>}
                        {step.elapsed > 0 && <span className="meta-item">⏱ {step.elapsed.toFixed(1)}s</span>}
                        <span className={`meta-item status-${step.status}`}>{statusInfo.label}</span>
                    </div>

                    {step.input && Object.keys(step.input).length > 0 && (
                        <div className="workflow-node-io">
                            <div className="workflow-node-io-label">📤 Input</div>
                            <pre>{JSON.stringify(step.input, null, 2)}</pre>
                        </div>
                    )}
                    {step.output && (
                        <div className="workflow-node-io">
                            <div className="workflow-node-io-label">📥 Output</div>
                            <pre>{step.output}</pre>
                        </div>
                    )}
                    {step.reflectQuality && (
                        <div className={`workflow-node-reflect quality-${step.reflectQuality}`}>
                            {step.reflectQuality === 'good' ? '✅ 数据质量良好' :
                             step.reflectQuality === 'poor' ? '🔄 数据不足，已重试' :
                             '⚠️ 未找到相关数据'}
                            {step.reflectReason && <span className="reflect-reason"> — {step.reflectReason}</span>}
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
