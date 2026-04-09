import { useRef, useEffect } from 'react'
import useStore from '../stores/useStore'
import MessageItem from './MessageItem'

export default function ChatPanel({ onMenuClick, onPanelToggle }) {
    const activeSession = useStore(s => s.activeSession)
    const activeSessionId = useStore(s => s.activeSessionId)
    const streamingTextMap = useStore(s => s.streamingTextMap)
    const isThinkingMap = useStore(s => s.isThinkingMap)
    const isStreamingMap = useStore(s => s.isStreamingMap)
    const agentMode = useStore(s => s.agentMode)
    const agentThinking = useStore(s => s.agentThinking)
    const params = useStore(s => s.params)
    const config = useStore(s => s.config)
    const lastUsage = useStore(s => s.lastUsage)
    const retryMessage = useStore(s => s.retryMessage)
    const editMessage = useStore(s => s.editMessage)
    const observerMemoryStore = useStore(s => s.observerMemoryInfo)

    const omData = observerMemoryStore || (activeSession?.observer_summary ? {
        version: activeSession.observer_summary.version || 1,
        compressed_count: activeSession.observer_summary.compressed_up_to,
        active_count: Math.max(0, (activeSession.messages?.length || 0) - activeSession.observer_summary.compressed_up_to)
    } : null)

    const bottomRef = useRef(null)

    const messages = activeSession?.messages || []
    const nonSystemMessages = messages.filter(m => m.role !== 'system')
    const streamingText = activeSessionId ? (streamingTextMap[activeSessionId] || '') : ''
    const isThinking = activeSessionId ? (isThinkingMap[activeSessionId] || false) : false
    const isStreaming = activeSessionId ? (isStreamingMap[activeSessionId] || false) : false

    const currentProvider = params.provider || config?.default_provider || ''
    const currentModel = params.model || config?.default_model || ''

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [nonSystemMessages.length, streamingText, isThinking, agentThinking])

    // Retry handler: pop last pair, re-send
    const handleRetry = async () => {
        const text = await retryMessage()
        if (text) {
            // Auto-send by setting editingText then triggering
            useStore.getState().setEditingText(text)
            // Small delay then auto-submit
            setTimeout(() => {
                const inputEl = document.querySelector('.message-input')
                if (inputEl) {
                    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })
                    inputEl.dispatchEvent(event)
                }
            }, 100)
        }
    }

    const handleEdit = () => editMessage()

    if (!activeSessionId) {
        return (
            <div className="chat-panel">
                <div className="chat-empty">
                    <div className="chat-empty-icon">◉</div>
                    <h2>The Machine</h2>
                    <p>Select a session or create a new one</p>
                    <div className="chat-empty-hints">
                        <span onClick={() => useStore.getState().createNewSession()}>
                            + New Session
                        </span>
                    </div>
                </div>
            </div>
        )
    }

    const lastMsg = nonSystemMessages[nonSystemMessages.length - 1]
    const canRetryLast = !isStreaming && lastMsg && lastMsg.role === 'assistant'

    return (
        <div className="chat-panel">
            {/* Chat Header */}
            <div className="chat-header">
                <div className="chat-header-left">
                    <button className="hamburger-btn" onClick={onMenuClick} title="Menu">☰</button>
                    <span className="chat-session-name">{activeSession?.name || '对话'}</span>
                    {!agentMode && (
                        <span className="provider-badge">
                            {currentProvider} / {currentModel}
                        </span>
                    )}
                    {isStreaming && (
                        <div className="status-indicator">
                            <div className={`status-dot ${isThinking ? 'thinking' : 'streaming'}`} />
                            <span>{isThinking ? 'Processing…' : 'Streaming…'}</span>
                        </div>
                    )}
                </div>
                <div className="chat-header-right">
                    {lastUsage && (
                        <span className="usage-chip">
                            ↑{lastUsage.prompt_tokens} ↓{lastUsage.completion_tokens}
                        </span>
                    )}
                    <button className="panel-toggle-btn" onClick={onPanelToggle} title="切换面板">⚙</button>
                </div>
            </div>

            {/* Observer Memory 压缩通知 */}
            {omData && (
                <div className="observer-memory-toast">
                    <span className="om-icon">◈</span>
                    <span className="om-text">
                        Memory v{omData.version} · Archived {omData.compressed_count} · Active {omData.active_count}
                    </span>
                </div>
            )}

            {/* Messages */}
            <div className="chat-messages">
                {nonSystemMessages.length === 0 && !isStreaming && (
                    <div className="chat-empty" style={{ height: '50vh' }}>
                        <div className="chat-empty-icon">{agentMode ? '◉' : '◈'}</div>
                        <h2>{agentMode ? 'Autonomous Mode' : 'Direct Mode'}</h2>
                        <p>{agentMode ? 'Describe your task. The Machine will orchestrate.' : 'Select a model and start a conversation.'}</p>
                        <div className="chat-empty-hints">
                            {agentMode ? (
                                <>
                                    <span onClick={() => useStore.getState().setEditingText('帮我调研一下 Cursor IDE 的竞品')}>Research</span>
                                    <span onClick={() => useStore.getState().setEditingText('写一份AI编程工具的竞品分析报告')}>Write Report</span>
                                </>
                            ) : (
                                <>
                                    <span onClick={() => useStore.getState().setEditingText('你好，请介绍一下你自己')}>Say Hello</span>
                                    <span onClick={() => useStore.getState().setEditingText('帮我解释一下量子计算的基本原理')}>Ask a Question</span>
                                </>
                            )}
                        </div>
                    </div>
                )}

                {nonSystemMessages.map((msg, i) => {
                    const isLast = i === nonSystemMessages.length - 1
                    const isSecondLast = i === nonSystemMessages.length - 2
                    const canRetry = isLast && msg.role === 'assistant' && !isStreaming
                    const canEdit = !isStreaming && msg.role === 'user' && (
                        isLast || (isSecondLast && nonSystemMessages[nonSystemMessages.length - 1]?.role === 'assistant')
                    )
                    return (
                        <MessageItem
                            key={i}
                            message={msg}
                            isLast={isLast}
                            canRetry={canRetry}
                            canEdit={canEdit}
                            onRetry={handleRetry}
                            onEdit={handleEdit}
                            isStreaming={isStreaming}
                        />
                    )
                })}

                {/* Streaming text (直接对话模式) */}
                {!agentMode && streamingText && (
                    <MessageItem
                        message={{ role: 'assistant', content: streamingText }}
                        isStreaming={true}
                    />
                )}

                {/* Thinking indicator */}
                {(isThinking || (agentMode && agentThinking)) && (
                    <div className="chat-message assistant">
                        <div className="chat-message-avatar">◈</div>
                        <div className="chat-message-body">
                            <div className="chat-message-content thinking">
                                <span className="thinking-dot" />
                                {agentMode ? agentThinking : 'PROCESSING...'}
                            </div>
                        </div>
                    </div>
                )}

                <div ref={bottomRef} />
            </div>
        </div>
    )
}
