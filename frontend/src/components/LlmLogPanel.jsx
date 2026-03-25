import { useState } from 'react'
import useStore from '../stores/useStore'

const PHASE_LABELS = {
    intent: '🧠 意图理解',
    plan: '📋 计划生成',
    summarize: '📝 结果汇总',
}

function getPhaseLabel(phase) {
    if (PHASE_LABELS[phase]) return PHASE_LABELS[phase]
    if (phase.startsWith('step_')) return `⚙️ 步骤 ${phase.replace('step_', '')}`
    return `📎 ${phase}`
}

export default function LlmLogPanel() {
    const llmLogs = useStore(s => s.llmLogs)
    const [expandedIdx, setExpandedIdx] = useState(null)

    if (!llmLogs.length) return null

    return (
        <div className="llm-log-panel">
            <div className="llm-log-title">
                🔍 LLM 调用日志 ({llmLogs.length})
            </div>
            <div className="llm-log-list">
                {llmLogs.map((log, idx) => {
                    const isExpanded = expandedIdx === idx
                    return (
                        <div key={idx} className={`llm-log-item ${isExpanded ? 'expanded' : ''}`}>
                            <div
                                className="llm-log-header"
                                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                            >
                                <span className="llm-log-phase">{getPhaseLabel(log.phase)}</span>
                                <span className="llm-log-meta">
                                    {log.model?.split('/').pop()} · {log.prompt_tokens}+{log.completion_tokens}t · {log.elapsed}s
                                </span>
                                <span className="llm-log-toggle">{isExpanded ? '▲' : '▼'}</span>
                            </div>
                            {isExpanded && (
                                <div className="llm-log-detail" onClick={e => e.stopPropagation()}>
                                    {log.messages.map((msg, mi) => (
                                        <div key={mi} className={`llm-log-msg role-${msg.role}`}>
                                            <div className="llm-log-msg-role">
                                                {msg.role === 'system' ? '📋 SYSTEM' :
                                                 msg.role === 'user' ? '👤 USER' :
                                                 '🤖 ASSISTANT'}
                                            </div>
                                            <pre className="llm-log-msg-content">{msg.content}</pre>
                                        </div>
                                    ))}
                                    <div className="llm-log-msg role-response">
                                        <div className="llm-log-msg-role">🤖 RESPONSE</div>
                                        <pre className="llm-log-msg-content">{log.response}</pre>
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
