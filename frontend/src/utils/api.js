const BASE = '/api'

export async function fetchConfig() {
    const r = await fetch(`${BASE}/config`)
    return r.json()
}

export async function saveConfig(config) {
    const r = await fetch(`${BASE}/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config })
    })
    return r.json()
}

export async function fetchStatus() {
    const r = await fetch(`${BASE}/status`)
    return r.json()
}

export async function fetchSessions() {
    const r = await fetch(`${BASE}/sessions`)
    return r.json()
}

export async function createSession(name, system_prompt = '') {
    const r = await fetch(`${BASE}/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, system_prompt })
    })
    return r.json()
}

export async function fetchSession(id) {
    const r = await fetch(`${BASE}/sessions/${id}`)
    return r.json()
}

export async function fetchWorkflow(id) {
    const r = await fetch(`${BASE}/sessions/${id}/workflow`)
    return r.json()
}

export async function updateSession(id, patch) {
    const r = await fetch(`${BASE}/sessions/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
    })
    return r.json()
}

export async function deleteSession(id) {
    const r = await fetch(`${BASE}/sessions/${id}`, { method: 'DELETE' })
    return r.json()
}

export async function clearMessages(id) {
    const r = await fetch(`${BASE}/sessions/${id}/messages`, { method: 'DELETE' })
    return r.json()
}

export async function retryLastMessages(id, count = 2) {
    const r = await fetch(`${BASE}/sessions/${id}/messages/last?count=${count}`, { method: 'DELETE' })
    if (!r.ok) throw new Error('Retry failed')
    return r.json()
}

export async function countTokens(messages) {
    const r = await fetch(`${BASE}/tokens/count`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages })
    })
    const data = await r.json()
    return data.token_count || 0
}

export async function uploadFile(file) {
    const form = new FormData()
    form.append('file', file)
    const r = await fetch(`${BASE}/files/upload`, { method: 'POST', body: form })
    if (!r.ok) throw new Error('Upload failed')
    return r.json()
}

/**
 * 直接对话 SSE 流（非 Agent 模式）
 */
export function streamChat(payload, { onDelta, onStatus, onUsage, onFinish, onError }) {
    const controller = new AbortController()

    fetch(`${BASE}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
    }).then(async res => {
        if (!res.ok) {
            const text = await res.text()
            onError(text)
            return
        }
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })

            let boundary = buffer.indexOf('\n\n')
            while (boundary !== -1) {
                const chunkStr = buffer.slice(0, boundary).trim()
                buffer = buffer.slice(boundary + 2)
                boundary = buffer.indexOf('\n\n')

                if (!chunkStr) continue

                const lines = chunkStr.split('\n')
                for (let line of lines) {
                    line = line.trim()
                    if (!line.startsWith('data: ')) continue

                    const raw = line.slice(6).trim()
                    if (raw === '[DONE]') { onFinish(); return }

                    try {
                        const parsed = JSON.parse(raw)
                        if (parsed.error) { onError(parsed.error); return }
                        if (parsed.status && onStatus) onStatus(parsed.status)
                        if (parsed.delta !== undefined) onDelta(parsed.delta)
                        if (parsed.usage) onUsage(parsed.usage)
                    } catch (e) {
                        console.error('JSON parse error:', raw, e)
                    }
                }
            }
        }

        // Trailing buffer
        if (buffer.trim()) {
            const lines = buffer.trim().split('\n')
            for (let line of lines) {
                line = line.trim()
                if (!line.startsWith('data: ')) continue
                const raw = line.slice(6).trim()
                if (raw === '[DONE]') { onFinish(); return }
                try {
                    const parsed = JSON.parse(raw)
                    if (parsed.delta !== undefined) onDelta(parsed.delta)
                } catch (e) {}
            }
        }

        onFinish()
    }).catch(err => {
        if (err.name !== 'AbortError') onError(err.message)
    })

    return controller
}

/**
 * Agent 模式 SSE 流
 */
export function streamAgentChat(payload, { onEvent, onFinish, onError }) {
    const controller = new AbortController()

    fetch(`${BASE}/chat/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: controller.signal
    }).then(async res => {
        if (!res.ok) {
            const text = await res.text()
            onError(text)
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
                    if (event.type === 'stream_end') { onFinish(); return }
                    onEvent(event)
                } catch (e) {}
            }
        }
        onFinish()
    }).catch(err => {
        if (err.name !== 'AbortError') onError(err.message)
    })

    return controller
}
/**
 * 暂停执行
 */
export async function pauseTask() {
    const r = await fetch(`${BASE}/task/pause`, { method: 'POST' })
    return r.json()
}

/**
 * 恢复执行
 */
export async function resumeTask() {
    const r = await fetch(`${BASE}/task/resume`, { method: 'POST' })
    return r.json()
}

/**
 * 重试失败步骤 (SSE)
 */
export function streamRetryStep(stepId, { onEvent, onFinish, onError }) {
    const controller = new AbortController()

    fetch(`${BASE}/task/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step_id: stepId }),
        signal: controller.signal
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
                    if (event.type === 'stream_end') { onFinish(); return }
                    onEvent(event)
                } catch {}
            }
        }
        onFinish()
    }).catch(err => {
        if (err.name !== 'AbortError') onError(err.message)
    })

    return controller
}

/**
 * Agent 确认计划
 */
export async function confirmPlan(action, modification = '') {
    const r = await fetch(`${BASE}/task/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, modification })
    })
    return r
}

/**
 * Agent 确认计划 SSE 流
 */
export function streamConfirmPlan(action, modification, { onEvent, onFinish, onError, sessionId = '', stepModels = {} }) {
    const controller = new AbortController()

    fetch(`${BASE}/task/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, modification, session_id: sessionId, step_models: stepModels }),
        signal: controller.signal
    }).then(async res => {
        if (!res.ok) {
            const data = await res.json().catch(() => ({}))
            onError(data.detail || 'Confirm failed')
            return
        }

        // If action is confirm, it returns SSE stream
        if (action === 'confirm') {
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
                        if (event.type === 'stream_end') { onFinish(); return }
                        onEvent(event)
                    } catch (e) {}
                }
            }
            onFinish()
        } else {
            // modify/cancel returns JSON
            const data = await res.json()
            onFinish(data)
        }
    }).catch(err => {
        if (err.name !== 'AbortError') onError(err.message)
    })

    return controller
}

/**
 * Agent 配置（role_models）
 */
export async function fetchAgentConfig() {
    const r = await fetch(`${BASE}/agent/config`)
    return r.json()
}

export async function updateAgentConfig(role_models) {
    const r = await fetch(`${BASE}/agent/config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role_models })
    })
    return r.json()
}
