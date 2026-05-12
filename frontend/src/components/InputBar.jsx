import { useState, useRef, useCallback, useEffect } from 'react'
import useStore from '../stores/useStore'
import { uploadFile, streamChat, streamAgentChat, countTokens, fetchSession, fetchSessions, confirmToolCall } from '../utils/api'

export default function InputBar() {
    const {
        activeSessionId, activeSession, setActiveSession,
        params, config, agentMode,
        isStreamingMap, setIsStreaming, setIsThinking,
        setStreamingText, appendStreamingText,
        pendingFiles, addPendingFile, removePendingFile, setPendingFiles,
        promptTokenEstimate, setPromptTokenEstimate,
        setLastUsage, addToast,
        editingText, setEditingText,
        setSessions, loadSessions,
        handleAgentEvent,
        plan, workflowSteps,
        waitingAnswer,
        setObserverMemoryInfo,
        waitingToolConfirm, pendingToolCall,
    } = useStore()

    const [text, setText] = useState('')
    const [composing, setComposing] = useState(false)
    const [uploading, setUploading] = useState(0)
    const textareaRef = useRef(null)
    const fileInputRef = useRef(null)
    const abortRef = useRef(null)

    // Watch for editingText
    useEffect(() => {
        if (editingText !== null) {
            setText(editingText)
            setEditingText(null)
            setTimeout(() => {
                if (textareaRef.current) {
                    textareaRef.current.focus()
                    textareaRef.current.style.height = 'auto'
                    textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 200) + 'px'
                }
            }, 50)
        }
    }, [editingText])

    const handleTextChange = (e) => {
        setText(e.target.value)
        const ta = e.target
        ta.style.height = 'auto'
        ta.style.height = Math.min(ta.scrollHeight, 200) + 'px'
        if (!agentMode) estimateTokens(e.target.value)
    }

    const tokenTimerRef = useRef(null)
    const estimateTokens = useCallback((msg) => {
        if (!msg.trim()) { setPromptTokenEstimate(0); return }
        if (tokenTimerRef.current) clearTimeout(tokenTimerRef.current)
        tokenTimerRef.current = setTimeout(async () => {
            try {
                const msgs = [...(activeSession?.messages || []).map(m => ({
                    role: m.role, content: typeof m.content === 'string' ? m.content : '[multimodal]'
                })), { role: 'user', content: msg }]
                const count = await countTokens(msgs)
                setPromptTokenEstimate(count)
            } catch { }
        }, 500)
    }, [activeSession])

    const handleKeyDown = (e) => {
        if (e.nativeEvent.isComposing || composing || e.keyCode === 229) return
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            const finalValue = textareaRef.current?.value || text
            handleSend(finalValue)
        }
    }

    const handleFileSelect = async (files) => {
        const fileList = Array.from(files)
        setUploading(fileList.length)
        for (const file of fileList) {
            try {
                addToast(`正在上传: ${file.name}…`, 'default')
                const result = await uploadFile(file)
                addPendingFile(result)
                addToast(`上传完成: ${file.name}`, 'success')
            } catch (e) {
                addToast('文件上传失败: ' + e.message, 'error')
            } finally {
                setUploading(prev => prev - 1)
            }
        }
    }

    const handleToolConfirm = async (approved) => {
        try {
            await confirmToolCall(activeSessionId || '', approved)
            useStore.setState({ waitingToolConfirm: false, pendingToolCall: null })
        } catch (e) {
            addToast('确认失败: ' + e.message, 'error')
        }
    }

    const handlePaste = useCallback((e) => {
        const items = e.clipboardData?.items
        if (!items) return
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                const file = item.getAsFile()
                if (file) handleFileSelect([file])
            }
        }
    }, [])

    const handleDrop = (e) => {
        e.preventDefault()
        handleFileSelect(e.dataTransfer.files)
    }

    const handleSend = async (continueMsg = null) => {
        const msg = continueMsg || text.trim()
        if (!msg && pendingFiles.length === 0 && !continueMsg) return
        if (isStreaming) return

        // 快照当前 params，避免 async 期间被 useEffect 覆盖
        const snapshotParams = { ...useStore.getState().params }

        // 没有会话时自动创建
        let sessionId = activeSessionId
        if (!sessionId) {
            const s = await useStore.getState().createNewSession()
            sessionId = s?.id || useStore.getState().activeSessionId
            if (!sessionId) { addToast('创建会话失败', 'error'); return }
        }

        // Optimistic UI: add user message immediately
        const userContent = msg || ''
        useStore.setState(s => ({
            activeSession: s.activeSession ? {
                ...s.activeSession,
                messages: [...(s.activeSession.messages || []),
                    { role: 'user', content: userContent, timestamp: new Date().toISOString() }
                ]
            } : s.activeSession,
        }))

        setText('')
        setPendingFiles([])
        setPromptTokenEstimate(0)
        if (textareaRef.current) textareaRef.current.style.height = 'auto'

        const currentSessionId = sessionId

        if (agentMode) {
            const waitingAnswer = useStore.getState().waitingAnswer

            // ═══ Agent 模式 ═══
            setIsStreaming(currentSessionId, true)

            if (waitingAnswer) {
                // 用户在回答澄清问题 → /api/task/answer
                useStore.setState({ waitingAnswer: false })
                const controller = new AbortController()
                abortRef.current = controller
                const token = localStorage.getItem('auth_token')
                const reqHeaders = { 'Content-Type': 'application/json' }
                if (token) reqHeaders['Authorization'] = `Bearer ${token}`
                fetch('/api/task/answer', {
                    method: 'POST',
                    headers: reqHeaders,
                    body: JSON.stringify({ answer: msg, session_id: currentSessionId }),
                    signal: controller.signal,
                }).then(async res => {
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
                    setIsStreaming(currentSessionId, false)
                    try {
                        const updated = await fetchSession(currentSessionId)
                        if (useStore.getState().activeSessionId === currentSessionId) setActiveSession(updated)
                    } catch {}
                    loadSessions()
                }).catch(err => {
                    if (err.name !== 'AbortError') addToast('回答失败: ' + err.message, 'error')
                    setIsStreaming(currentSessionId, false)
                })
            } else {
                // 正常 Agent 请求

            abortRef.current = streamAgentChat(
                { message: msg, session_id: currentSessionId, files: pendingFiles.length > 0 ? pendingFiles : undefined },
                {
                    onEvent: handleAgentEvent,
                    onFinish: async () => {
                        setIsStreaming(currentSessionId, false)
                        // Reload session to get persisted messages
                        try {
                            const updated = await fetchSession(currentSessionId)
                            if (useStore.getState().activeSessionId === currentSessionId) {
                                setActiveSession(updated)
                            }
                        } catch { }
                        loadSessions()
                    },
                    onError: (err) => {
                        setIsStreaming(currentSessionId, false)
                        addToast('Agent 错误: ' + err, 'error')
                    },
                }
            )
            } // end waitingAnswer else
        } else {
            // ═══ 直接对话模式 ═══
            const cfg = config || {}
            const providerName = snapshotParams.provider || cfg.default_provider || 'anthropic'
            const model = snapshotParams.model || cfg.default_model || ''

            const payload = {
                session_id: currentSessionId,
                message: msg || '',
                files: pendingFiles.length > 0 ? pendingFiles : undefined,
                provider: providerName,
                model,
                system_prompt: activeSession?.system_prompt || snapshotParams.system_prompt || undefined,
                params: {
                    max_tokens: snapshotParams.max_tokens,
                    temperature: snapshotParams.temperature,
                    top_p: snapshotParams.top_p,
                    frequency_penalty: snapshotParams.frequency_penalty,
                },
                context_strategy: snapshotParams.context_strategy,
                context_rounds: snapshotParams.context_rounds,
                context_token_threshold: snapshotParams.context_token_threshold,
            }

            setIsStreaming(currentSessionId, true)
            setStreamingText(currentSessionId, '')
            setIsThinking(currentSessionId, false)

            abortRef.current = streamChat(payload, {
                onDelta: (delta) => {
                    setIsThinking(currentSessionId, false)
                    appendStreamingText(currentSessionId, delta)
                },
                onStatus: (status) => {
                    if (status === 'thinking') setIsThinking(currentSessionId, true)
                },
                onUsage: (usage) => setLastUsage(usage),
                onObserverMemory: (info) => setObserverMemoryInfo(info),
                onFinish: async () => {
                    setIsStreaming(currentSessionId, false)
                    setIsThinking(currentSessionId, false)
                    try {
                        const updated = await fetchSession(currentSessionId)
                        if (useStore.getState().activeSessionId === currentSessionId) {
                            setActiveSession(updated)
                        }
                    } catch { }
                    setStreamingText(currentSessionId, '')
                    // Delayed reload for auto-title
                    setTimeout(async () => {
                        try {
                            const sessions = await fetchSessions()
                            setSessions(sessions)
                            if (useStore.getState().activeSessionId === currentSessionId) {
                                const fresh = await fetchSession(currentSessionId)
                                setActiveSession(fresh)
                            }
                        } catch { }
                    }, 3000)
                },
                onError: (err) => {
                    setIsStreaming(currentSessionId, false)
                    setIsThinking(currentSessionId, false)
                    setStreamingText(currentSessionId, '')
                    addToast('错误: ' + err, 'error')
                },
            })
        }
    }

    const handleStop = () => {
        if (abortRef.current) abortRef.current.abort()
        if (activeSessionId) {
            setIsStreaming(activeSessionId, false)
            setStreamingText(activeSessionId, '')
            setIsThinking(activeSessionId, false)
            useStore.setState({ agentThinking: '', waitingToolConfirm: false, pendingToolCall: null })
        }
    }

    const isStreaming = activeSessionId ? (isStreamingMap[activeSessionId] || false) : false

    return (
        <div
            className={`input-area${waitingAnswer ? ' waiting-answer' : ''}`}
            onDrop={handleDrop}
            onDragOver={e => e.preventDefault()}
        >
            {/* 工具调用确认框（保证任意状态下都可见） */}
            {waitingToolConfirm && pendingToolCall && (
                <div className="tool-confirm-dialog" style={{ marginBottom: '10px' }}>
                    <div className="tool-confirm-icon">⚠️</div>
                    <div className="tool-confirm-info">
                        <div className="tool-confirm-title">
                            Agent 想要执行 <strong>{pendingToolCall.name}</strong>
                        </div>
                        <pre className="tool-confirm-args" style={{ maxHeight: '100px', overflow: 'auto' }}>
                            {JSON.stringify(pendingToolCall.arguments, null, 2)}
                        </pre>
                    </div>
                    <div className="tool-confirm-actions">
                        <button className="btn-confirm-approve" onClick={() => handleToolConfirm(true)}>
                            ✅ 允许
                        </button>
                        <button className="btn-confirm-reject" onClick={() => handleToolConfirm(false)}>
                            ❌ 拒绝
                        </button>
                    </div>
                </div>
            )}

            {/* 等待回答提示 */}
            {waitingAnswer && (
                <div className="answer-hint">
                    ▸ INPUT YOUR RESPONSE BELOW
                </div>
            )}
            {/* Token estimate (直接对话模式) */}
            {!agentMode && promptTokenEstimate > 0 && (
                <div className="token-dashboard">
                    <div className="token-counter">
                        预估 Prompt: <span className="val">{promptTokenEstimate}</span> tokens
                    </div>
                </div>
            )}

            {/* File previews */}
            {(pendingFiles.length > 0 || uploading > 0) && (
                <div className="file-previews">
                    {pendingFiles.map((f, i) => (
                        <div key={i} className="file-preview-item">
                            {f.type === 'image'
                                ? <img className="file-preview-img" src={f.data_url} alt={f.filename} />
                                : <span>📄</span>
                            }
                            <span>{f.filename}</span>
                            <button className="file-preview-remove" onClick={() => removePendingFile(i)}>×</button>
                        </div>
                    ))}
                    {uploading > 0 && (
                        <div className="file-preview-item" style={{ opacity: 0.7 }}>
                            <span className="upload-spinner" style={{ animation: 'spin 1s linear infinite', display: 'inline-block' }}>⏳</span>
                            <span>正在解析 {uploading} 个文件...</span>
                        </div>
                    )}
                </div>
            )}

            <div className="input-box">
                <button
                    className="upload-btn"
                    onClick={() => fileInputRef.current?.click()}
                    title="上传文件（图片/PDF/Word/Excel/PPT/HTML/CSV/JSON/音频/EPub/ZIP 等）"
                    disabled={uploading > 0}
                >⊕</button>

                <textarea
                    ref={textareaRef}
                    className="message-input"
                    placeholder={waitingAnswer
                        ? 'Enter your response...'
                        : agentMode
                            ? 'Describe task for autonomous orchestration...'
                            : 'Enter transmission... (Enter to send, Shift+Enter newline)'}
                    value={text}
                    onChange={handleTextChange}
                    onKeyDown={handleKeyDown}
                    onCompositionStart={() => setComposing(true)}
                    onCompositionEnd={() => setComposing(false)}
                    onPaste={handlePaste}
                    rows={1}
                    disabled={isStreaming}
                />

                {isStreaming
                    ? <button className="send-btn" onClick={handleStop} title="Stop">■</button>
                    : <button className="send-btn" onClick={() => handleSend()} disabled={!text.trim() && pendingFiles.length === 0} title="Send">▸</button>
                }
            </div>

            <div className="input-hint">Enter to send · Shift+Enter for new line · Drag to attach</div>

            <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,.pdf,.txt,.docx,.doc,.xlsx,.xls,.md,.pptx,.ppt,.html,.htm,.csv,.json,.xml,.epub,.zip,.mp3,.wav,.msg,.eml"
                style={{ display: 'none' }}
                onChange={e => handleFileSelect(e.target.files)}
            />
        </div>
    )
}
