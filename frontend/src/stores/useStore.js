import { create } from 'zustand'
import { fetchSessions, fetchSession, createSession, fetchStatus, fetchConfig, streamConfirmPlan, retryLastMessages, fetchAgentConfig, fetchWorkflow } from '../utils/api'

const useStore = create((set, get) => ({
    // ═══ 系统配置 ═══
    config: null,         // ChatBot config (providers, models, params)
    setConfig: (config) => set({ config }),
    systemStatus: null,   // Agent system status (tools, agents)
    setSystemStatus: (s) => set({ systemStatus: s }),

    // ═══ Agent 模式（per-session） ═══
    agentMode: false,
    toggleAgentMode: () => {
        const newMode = !get().agentMode
        set({ agentMode: newMode })
        // 持久化到当前 session
        const sid = get().activeSessionId
        if (sid) {
            const token = localStorage.getItem('auth_token')
            const headers = { 'Content-Type': 'application/json' }
            if (token) headers['Authorization'] = `Bearer ${token}`
            fetch(`/api/sessions/${sid}`, {
                method: 'PATCH',
                headers,
                body: JSON.stringify({ mode: newMode ? 'agent' : 'chat' }),
            }).catch(() => {})
        }
    },

    // ═══ 会话管理 ═══
    sessions: [],
    setSessions: (sessions) => set({ sessions }),
    activeSessionId: null,
    setActiveSessionId: (id) => set({ activeSessionId: id }),
    activeSession: null,
    setActiveSession: (session) => set({ activeSession: session }),

    // ═══ 参数 (per-chat) ═══
    params: {
        provider: null,
        model: null,
        system_prompt: null,
        max_tokens: 100000,
        temperature: 1.0,
        top_p: 1.0,
        frequency_penalty: 0.0,
        context_strategy: 'rounds',
        context_rounds: 10,
        context_token_threshold: 8000,
    },
    setParams: (update) => set(s => ({ params: { ...s.params, ...update } })),

    // ═══ 直接对话流式状态 (per session) ═══
    isStreamingMap: {},
    setIsStreaming: (id, v) => set(s => ({ isStreamingMap: { ...s.isStreamingMap, [id]: v } })),

    isThinkingMap: {},
    setIsThinking: (id, v) => set(s => ({ isThinkingMap: { ...s.isThinkingMap, [id]: v } })),

    streamingTextMap: {},
    setStreamingText: (id, t) => set(s => ({ streamingTextMap: { ...s.streamingTextMap, [id]: t } })),
    appendStreamingText: (id, delta) => set(s => ({
        streamingTextMap: {
            ...s.streamingTextMap,
            [id]: (s.streamingTextMap[id] || '') + delta
        }
    })),

    // ═══ Agent 模式状态 ═══
    plan: null,
    workflowSteps: [],
    agentThinking: '',
    waitingConfirm: false,
    waitingAnswer: false,
    pausedStepId: null,  // 当前暂停的步骤 ID（mid-workflow pause）
    reviewingStepId: null, // 当前正在审查的步骤 ID
    reviewNextStep: null,  // 下一步预览
    workflowHistory: [],  // 历史工作流 [{ plan, steps, timestamp }]
    llmLogs: [],  // LLM 调用日志 [{ phase, model, messages, response, tokens, elapsed }]
    stepModels: {},       // { step_id: 'provider/model' } 每步自定义模型
    setStepModel: (stepId, model) => set(s => ({ stepModels: { ...s.stepModels, [stepId]: model } })),
    agentConfig: null,   // { role_models, available_providers }
    setAgentConfig: (c) => set({ agentConfig: c }),

    // ═══ 确认计划（修复：之前缺失导致 Workflow 无法启动）═══
    confirmPlan: (action, modification = '') => {
        const { handleAgentEvent, addToast, activeSessionId, loadSessions, stepModels } = get()
        set({ waitingConfirm: false })

        if (action === 'cancel') {
            set({ plan: null, workflowSteps: [], stepModels: {}, llmLogs: [] })
            const token = localStorage.getItem('auth_token')
            const headers = { 'Content-Type': 'application/json' }
            if (token) headers['Authorization'] = `Bearer ${token}`
            fetch('/api/task/confirm', {
                method: 'POST',
                headers,
                body: JSON.stringify({ action: 'cancel' })
            }).catch(() => {})
            return
        }

        if (action === 'modify') {
            const token = localStorage.getItem('auth_token')
            const headers = { 'Content-Type': 'application/json' }
            if (token) headers['Authorization'] = `Bearer ${token}`
            fetch('/api/task/confirm', {
                method: 'POST',
                headers,
                body: JSON.stringify({ action: 'modify', modification })
            }).then(r => r.json()).then(data => {
                if (data.plan) {
                    set({
                        plan: data.plan,
                        waitingConfirm: true,
                        stepModels: {},
                        workflowSteps: (data.plan.steps || []).map(s => ({
                            step_id: s.step_id, agent: s.agent,
                            description: s.description, input: s.input || {},
                            status: 'pending', output: '', elapsed: 0, tokens: 0,
                        })),
                    })
                }
            }).catch(e => addToast('修改失败: ' + e.message, 'error'))
            return
        }

        // confirm → SSE stream with session_id and step_models
        streamConfirmPlan('confirm', '', {
            onEvent: handleAgentEvent,
            sessionId: activeSessionId || '',
            stepModels: stepModels,
            onFinish: async () => {
                set(s => ({ isStreamingMap: { ...s.isStreamingMap, [activeSessionId]: false } }))
                if (activeSessionId) {
                    try {
                        const updated = await fetchSession(activeSessionId)
                        if (get().activeSessionId === activeSessionId) set({ activeSession: updated })
                    } catch {}
                }
                loadSessions()
            },
            onError: (err) => addToast('执行失败: ' + err, 'error'),
        })
    },

    // ═══ 文件上传 ═══
    pendingFiles: [],
    setPendingFiles: (files) => set({ pendingFiles: files }),
    addPendingFile: (f) => set(s => ({ pendingFiles: [...s.pendingFiles, f] })),
    removePendingFile: (idx) => set(s => ({
        pendingFiles: s.pendingFiles.filter((_, i) => i !== idx)
    })),

    // ═══ Token 估算 ═══
    promptTokenEstimate: 0,
    setPromptTokenEstimate: (n) => set({ promptTokenEstimate: n }),
    lastUsage: null,
    setLastUsage: (usage) => set({ lastUsage: usage }),

    // ═══ 编辑消息 ═══
    editingText: null,
    setEditingText: (t) => set({ editingText: t }),

    // ═══ UI 状态 ═══
    showSettings: false,
    setShowSettings: (v) => set({ showSettings: v }),

    // ═══ Toast ═══
    toasts: [],
    addToast: (msg, type = 'default') => {
        const id = Date.now()
        set(s => ({ toasts: [...s.toasts, { id, msg, type }] }))
        setTimeout(() => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })), 3500)
    },

    // ═══ 初始化 ═══
    init: async () => {
        try {
            const [cfg, status, sessions, agentCfg] = await Promise.all([
                fetchConfig(),
                fetchStatus(),
                fetchSessions(),
                fetchAgentConfig().catch(() => null),
            ])
            const dp = cfg.default_params || {}
            set({
                config: cfg,
                systemStatus: status,
                sessions,
                agentConfig: agentCfg,
                params: {
                    provider: cfg.default_provider,
                    model: cfg.default_model,
                    max_tokens: dp.max_tokens ?? 100000,
                    temperature: dp.temperature ?? 1.0,
                    top_p: dp.top_p ?? 1.0,
                    frequency_penalty: dp.frequency_penalty ?? 0.0,
                    context_strategy: cfg.context_strategy ?? 'rounds',
                    context_rounds: cfg.context_rounds ?? 10,
                    context_token_threshold: cfg.context_token_threshold ?? 8000,
                },
            })
        } catch (e) {
            console.error('初始化失败:', e)
        }
    },

    // ═══ 会话操作 ═══
    loadSessions: async () => {
        try {
            const data = await fetchSessions()
            set({ sessions: data })
        } catch (e) {}
    },

    selectSession: async (sessionId) => {
        try {
            const full = await fetchSession(sessionId)
            // 恢复该 session 的模式
            const sessionMode = full?.mode || 'chat'
            // 先重置 Agent 状态
            set({
                activeSessionId: sessionId,
                activeSession: full,
                agentMode: sessionMode === 'agent',
                plan: null,
                workflowSteps: [],
                workflowHistory: [],
                stepModels: {},
                agentThinking: '',
                waitingConfirm: false,
                waitingAnswer: false,
                pausedStepId: null,
                reviewingStepId: null,
                reviewNextStep: null,
                llmLogs: [],
            })

            // 加载该 session 的工作流数据
            try {
                const token = localStorage.getItem('auth_token')
                const wfHeaders = {}
                if (token) wfHeaders['Authorization'] = `Bearer ${token}`
                const wfRes = await fetch(`/api/sessions/${sessionId}/workflow`, { headers: wfHeaders })
                if (wfRes.ok) {
                    const wf = await wfRes.json()
                    if (wf && (wf.plan || (wf.history && wf.history.length > 0) || (wf.steps && wf.steps.length > 0))) {
                        // 从 backend history 恢复历史工作流
                        const restoredHistory = (wf.history || []).map(h => ({
                            plan: h.plan,
                            steps: h.steps || [],
                            timestamp: h.timestamp,
                        }))

                        // 如果当前工作流已完成，也放入历史
                        const isDone = wf.status === 'done'
                        const isWaiting = wf.status === 'waiting_confirm'

                        if (isDone && wf.plan) {
                            // 完成的工作流放入历史，当前清空
                            restoredHistory.push({
                                plan: wf.plan,
                                steps: wf.steps || [],
                                timestamp: wf.updated_at || new Date().toISOString(),
                            })
                            set({
                                plan: null,
                                workflowSteps: [],
                                waitingConfirm: false,
                                workflowHistory: restoredHistory,
                            })
                        } else {
                            // 进行中或待确认的工作流，正常还原
                            const planSteps = wf.plan?.steps || []
                            const execSteps = wf.steps || []
                            const mergedSteps = planSteps.map(ps => {
                                const es = execSteps.find(e => e.step_id === ps.step_id) || {}
                                return {
                                    step_id: ps.step_id,
                                    agent: ps.agent || es.agent || '',
                                    description: ps.description || es.description || '',
                                    input: ps.input || es.input || {},
                                    status: es.status || 'pending',
                                    output: es.output || '',
                                    elapsed: es.elapsed || 0,
                                    tokens: es.tokens || 0,
                                }
                            })
                            for (const es of execSteps) {
                                if (!mergedSteps.find(m => m.step_id === es.step_id)) {
                                    mergedSteps.push({
                                        step_id: es.step_id,
                                        agent: es.agent || '',
                                        description: es.description || '',
                                        input: es.input || {},
                                        status: es.status || 'completed',
                                        output: es.output || '',
                                        elapsed: es.elapsed || 0,
                                        tokens: es.tokens || 0,
                                    })
                                }
                            }
                            set({
                                plan: wf.plan || null,
                                workflowSteps: mergedSteps,
                                waitingConfirm: isWaiting,
                                workflowHistory: restoredHistory,
                            })
                        }
                    }
                }
            } catch (e) {
                console.warn('加载工作流数据失败:', e)
            }
            // 加载会话参数
            const cfg = get().config
            if (cfg && full.params) {
                const sp = full.params
                const dp = cfg.default_params || {}
                set(s => ({
                    params: {
                        ...s.params,
                        provider: sp.provider || cfg.default_provider,
                        model: sp.model || cfg.default_model,
                        max_tokens: sp.max_tokens ?? dp.max_tokens ?? 100000,
                        temperature: sp.temperature ?? dp.temperature ?? 1.0,
                        top_p: sp.top_p ?? dp.top_p ?? 1.0,
                        frequency_penalty: sp.frequency_penalty ?? dp.frequency_penalty ?? 0.0,
                    },
                }))
            }
            // 恢复工作流状态
            try {
                const wf = await fetchWorkflow(sessionId)
                if (wf && wf.plan) {
                    const steps = (wf.plan.steps || []).map(s => {
                        const result = (wf.steps || []).find(r => r.step_id === s.step_id)
                        return {
                            step_id: s.step_id,
                            agent: s.agent,
                            description: s.description,
                            input: s.input || {},
                            status: result?.status || 'completed',
                            output: result?.output || '',
                            elapsed: result?.elapsed || 0,
                            tokens: result?.tokens || 0,
                        }
                    })
                    set({
                        workflowHistory: [{
                            plan: wf.plan,
                            steps: steps,
                            timestamp: new Date().toISOString(),
                        }],
                    })
                }
            } catch {}
        } catch (e) {
            console.error('加载会话失败:', e)
        }
    },

    createNewSession: async () => {
        try {
            const name = '新对话 ' + new Date().toLocaleTimeString('zh', { hour12: false, hour: '2-digit', minute: '2-digit' })
            const s = await createSession(name)
            await get().loadSessions()
            await get().selectSession(s.id)
            return s
        } catch (e) {
            get().addToast('创建失败: ' + e.message, 'error')
        }
    },

    // ═══ Agent 事件处理 ═══
    handleAgentEvent: (event) => {
        const { type, data } = event

        switch (type) {
            case 'thinking':
                // 如果当前有已执行的工作流，归档到前端历史（后端 archive 已持久化）
                if (get().plan && get().workflowSteps.length > 0 &&
                    get().workflowSteps.some(s => s.status !== 'pending')) {
                    set(s => ({
                        workflowHistory: [...s.workflowHistory, {
                            plan: s.plan,
                            steps: s.workflowSteps,
                            timestamp: new Date().toISOString(),
                        }],
                        plan: null,
                        workflowSteps: [],
                        stepModels: {},
                        llmLogs: [],
                    }))
                } else if (!get().plan) {
                    // 没有进行中的工作流时也清空日志（新任务开始）
                    set({ llmLogs: [] })
                }
                set({ agentThinking: data.message })
                break

            case 'intent':
                set({ agentThinking: '' })
                break

            case 'reply':
                set(s => ({
                    agentThinking: '',
                    activeSession: s.activeSession ? {
                        ...s.activeSession,
                        messages: [...(s.activeSession.messages || []),
                            { role: 'assistant', content: data.content, timestamp: new Date().toISOString() }
                        ],
                    } : s.activeSession,
                }))
                break

            case 'clarify':
                set(s => ({
                    agentThinking: '',
                    waitingAnswer: true,
                    pausedStepId: null,
                    activeSession: s.activeSession ? {
                        ...s.activeSession,
                        messages: [...(s.activeSession.messages || []),
                            { role: 'assistant', content: '我需要了解更多信息：\n\n' + (data.questions || []).map((q, i) => `${i + 1}. ${q}`).join('\n'), timestamp: new Date().toISOString() }
                        ],
                    } : s.activeSession,
                }))
                break

            case 'step_pause':
                set(s => ({
                    agentThinking: '',
                    waitingAnswer: true,
                    pausedStepId: data.step_id,
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, status: 'paused' }
                            : ws
                    ),
                    activeSession: s.activeSession ? {
                        ...s.activeSession,
                        messages: [...(s.activeSession.messages || []),
                            {
                                role: 'assistant',
                                content: (data.message ? data.message + '\n\n' : '') +
                                    (data.questions || []).map((q, i) => `${i + 1}. ${q}`).join('\n'),
                                timestamp: new Date().toISOString(),
                            }
                        ],
                    } : s.activeSession,
                }))
                break

            case 'step_review':
                // 逐步审查：步骤完成后等待用户操作
                set(s => ({
                    agentThinking: '',
                    reviewingStepId: data.step_id,
                    reviewNextStep: data.next_step,
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, status: 'review' }
                            : ws
                    ),
                }))
                break

            case 'plan':
                set({
                    agentThinking: '',
                    plan: data,
                    waitingConfirm: true,
                    workflowSteps: (data.steps || []).map(s => ({
                        step_id: s.step_id,
                        agent: s.agent,
                        description: s.description,
                        input: s.input || {},
                        status: 'pending',
                        output: '',
                        elapsed: 0,
                        tokens: 0,
                    })),
                })
                break

            case 'paused':
                set(s => ({
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, status: 'paused' }
                            : ws
                    ),
                }))
                break

            case 'step_start':
                set(s => ({
                    agentThinking: '',
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, status: 'running', input: data.input || ws.input }
                            : ws
                    ),
                }))
                break

            case 'step_result':
                set(s => ({
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, status: data.status || 'completed', output: data.output || '', elapsed: data.elapsed || 0, tokens: data.tokens || 0 }
                            : ws
                    ),
                }))
                break

            case 'step_reflect':
                set(s => ({
                    workflowSteps: s.workflowSteps.map(ws =>
                        ws.step_id === data.step_id
                            ? { ...ws, reflectQuality: data.quality, reflectReason: data.reason }
                            : ws
                    ),
                }))
                break

            case 'summary':
                set(s => ({
                    agentThinking: '',
                    activeSession: s.activeSession ? {
                        ...s.activeSession,
                        messages: [...(s.activeSession.messages || []),
                            { role: 'assistant', content: data.content, timestamp: new Date().toISOString() }
                        ],
                    } : s.activeSession,
                }))
                break

            case 'error':
                set(s => ({
                    agentThinking: '',
                    activeSession: s.activeSession ? {
                        ...s.activeSession,
                        messages: [...(s.activeSession.messages || []),
                            { role: 'system', content: `❌ ${data.message}`, timestamp: new Date().toISOString() }
                        ],
                    } : s.activeSession,
                }))
                break

            case 'done':
                // 工作流完成 → 归档到历史
                set(s => {
                    const update = { agentThinking: '', stepModels: {}, waitingConfirm: false }
                    // 如果有已执行的工作流步骤，归档
                    if (s.plan && s.workflowSteps.length > 0) {
                        update.workflowHistory = [...s.workflowHistory, {
                            plan: s.plan,
                            steps: s.workflowSteps,
                            timestamp: new Date().toISOString(),
                        }]
                        update.plan = null
                        update.workflowSteps = []
                    }
                    return update
                })
                break

            case 'llm_log':
                set(s => ({
                    llmLogs: [...s.llmLogs, {
                        phase: data.phase,
                        model: data.model,
                        messages: data.messages || [],
                        response: data.response || '',
                        prompt_tokens: data.prompt_tokens || 0,
                        completion_tokens: data.completion_tokens || 0,
                        elapsed: data.elapsed || 0,
                        timestamp: new Date().toISOString(),
                    }],
                }))
                break
        }
    },

    // ═══ 重试 / 编辑 ═══
    retryMessage: async () => {
        const { activeSessionId, activeSession, addToast, setEditingText } = get()
        if (!activeSessionId) return
        const nonSystem = (activeSession?.messages || []).filter(m => m.role !== 'system')
        const endsWithUser = nonSystem.length > 0 && nonSystem[nonSystem.length - 1].role === 'user'
        const popCount = endsWithUser ? 1 : 2
        try {
            const result = await retryLastMessages(activeSessionId, popCount)
            const userMsg = result.last_user_message
            if (!userMsg) { addToast('没有可重试的消息', 'error'); return }
            const updated = await fetchSession(activeSessionId)
            set({ activeSession: updated })
            // Re-send by setting editing text then auto-submit
            let textContent = ''
            if (Array.isArray(userMsg)) {
                textContent = userMsg.filter(m => m.type === 'text').map(t => t.text).join('\n')
            } else {
                textContent = typeof userMsg === 'string' ? userMsg : ''
            }
            return textContent  // caller will re-send
        } catch (e) {
            addToast('重试失败: ' + e.message, 'error')
        }
    },

    editMessage: async () => {
        const { activeSessionId, activeSession, addToast, setEditingText } = get()
        if (!activeSessionId) return
        const nonSystem = (activeSession?.messages || []).filter(m => m.role !== 'system')
        const endsWithUser = nonSystem.length > 0 && nonSystem[nonSystem.length - 1].role === 'user'
        const popCount = endsWithUser ? 1 : 2
        try {
            const result = await retryLastMessages(activeSessionId, popCount)
            const userMsg = result.last_user_message
            if (!userMsg) { addToast('没有可编辑的消息', 'error'); return }
            const updated = await fetchSession(activeSessionId)
            set({ activeSession: updated })
            let textContent = ''
            if (Array.isArray(userMsg)) {
                textContent = userMsg.filter(m => m.type === 'text').map(t => t.text).join('\n')
            } else {
                textContent = typeof userMsg === 'string' ? userMsg : JSON.stringify(userMsg)
            }
            textContent = textContent.replace(/\[附件:.*?\]\n/g, '')
            setEditingText(textContent)
        } catch (e) {
            addToast('编辑失败: ' + e.message, 'error')
        }
    },
}))

export default useStore
