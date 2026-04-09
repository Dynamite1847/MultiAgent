import { useEffect } from 'react'
import useStore from '../stores/useStore'
import { updateSession } from '../utils/api'

export default function ParamDrawer() {
    const { config, params, setParams, activeSession, activeSessionId, setActiveSession } = useStore()

    useEffect(() => {
        if (!config) return
        const dp = config.default_params || {}
        const sp = useStore.getState().activeSession?.params || {}
        setParams({
            provider: sp.provider || config.default_provider,
            model: sp.model || config.default_model,
            max_tokens: sp.max_tokens ?? dp.max_tokens ?? 100000,
            temperature: sp.temperature ?? dp.temperature ?? 1.0,
            top_p: sp.top_p ?? dp.top_p ?? 1.0,
            frequency_penalty: sp.frequency_penalty ?? dp.frequency_penalty ?? 0.0,
            context_strategy: sp.context_strategy ?? config.context_strategy ?? 'rounds',
            context_rounds: sp.context_rounds ?? config.context_rounds ?? 10,
            context_token_threshold: sp.context_token_threshold ?? config.context_token_threshold ?? 8000,
        })
    }, [config, activeSessionId])

    useEffect(() => {
        if (!activeSessionId || !params.provider) return
        const sp = useStore.getState().activeSession?.params || {}
        const isChanged = Object.keys(params).some(k => params[k] !== sp[k] && k !== 'system_prompt')
        if (!isChanged) return

        const timer = setTimeout(() => {
            const currentParams = { ...useStore.getState().params }
            delete currentParams.system_prompt
            updateSession(activeSessionId, { params: currentParams }).catch(console.error)
            const curSession = useStore.getState().activeSession
            if (curSession && curSession.id === activeSessionId) {
                setActiveSession({ ...curSession, params: { ...curSession.params, ...currentParams } })
            }
        }, 1000)
        return () => clearTimeout(timer)
    }, [params, activeSessionId])

    const providers = config?.providers || {}
    const providerKeys = Object.keys(providers)
    const currentModels = providers[params.provider]?.models || []

    return (
        <div className="param-drawer">
            <div className="drawer-header">Parameters</div>

            {/* ── Model Card ── */}
            <div className="drawer-card">
                <div className="drawer-card-stack">
                    <span className="drawer-card-label">Provider</span>
                    <select
                        className="drawer-full-select"
                        value={params.provider || ''}
                        onChange={e => {
                            const p = e.target.value
                            const firstModel = providers[p]?.models?.[0] || ''
                            setParams({ provider: p, model: firstModel })
                        }}
                    >
                        {providerKeys.map(p => (
                            <option key={p} value={p}>{
                                p === 'anthropic' ? 'Anthropic (Claude)' :
                                    p === 'google' ? 'Google (Gemini)' :
                                        p === 'doubao' ? 'Doubao (火山引擎)' :
                                            p === 'dashscope' ? 'DashScope (百炼)' :
                                                p === 'openai' ? 'DeepSeek / OpenAI' : p
                            }</option>
                        ))}
                    </select>
                </div>
                <div className="drawer-card-divider" />
                <div className="drawer-card-stack">
                    <span className="drawer-card-label">Model</span>
                    <select
                        className="drawer-full-select"
                        value={params.model || ''}
                        onChange={e => setParams({ model: e.target.value })}
                    >
                        {currentModels.map(m => (
                            <option key={m} value={m}>{m}</option>
                        ))}
                    </select>
                </div>
            </div>

            {/* ── System Prompt ── */}
            <div className="drawer-section-title">System Prompt</div>
            <div className="drawer-card">
                <textarea
                    className="drawer-textarea"
                    placeholder={config?.global_system_prompt || 'Uses global default if empty…'}
                    value={activeSession ? (activeSession.system_prompt || '') : (params.system_prompt || '')}
                    onChange={e => {
                        const val = e.target.value
                        if (activeSession) setActiveSession({ ...activeSession, system_prompt: val })
                        setParams({ system_prompt: val })
                    }}
                    onBlur={e => {
                        if (activeSessionId) updateSession(activeSessionId, { system_prompt: e.target.value }).catch(console.error)
                    }}
                    rows={3}
                />
            </div>

            {/* ── Generation Card ── */}
            <div className="drawer-section-title">Generation</div>
            <div className="drawer-card">
                <div className="drawer-card-row">
                    <span className="drawer-card-label">Max Tokens</span>
                    <span className="drawer-card-value">{params.max_tokens.toLocaleString()}</span>
                </div>
                <div className="drawer-card-slider">
                    <input type="range" min={256} max={128000} step={256} value={params.max_tokens} onChange={e => setParams({ max_tokens: +e.target.value })} />
                </div>
                <div className="drawer-card-divider" />

                <div className="drawer-card-row">
                    <span className="drawer-card-label">Temperature</span>
                    <span className="drawer-card-value">{params.temperature.toFixed(2)}</span>
                </div>
                <div className="drawer-card-slider">
                    <input type="range" min={0} max={2} step={0.05} value={params.temperature} onChange={e => setParams({ temperature: +e.target.value })} />
                </div>
                <div className="drawer-card-divider" />

                <div className="drawer-card-row">
                    <span className="drawer-card-label">Top P</span>
                    <span className="drawer-card-value">{params.top_p.toFixed(2)}</span>
                </div>
                <div className="drawer-card-slider">
                    <input type="range" min={0} max={1} step={0.05} value={params.top_p} onChange={e => setParams({ top_p: +e.target.value })} />
                </div>
                <div className="drawer-card-divider" />

                <div className="drawer-card-row">
                    <span className="drawer-card-label">Freq. Penalty</span>
                    <span className="drawer-card-value">{params.frequency_penalty.toFixed(2)}</span>
                </div>
                <div className="drawer-card-slider">
                    <input type="range" min={0} max={2} step={0.05} value={params.frequency_penalty} onChange={e => setParams({ frequency_penalty: +e.target.value })} />
                </div>
            </div>

            {/* ── Context Card ── */}
            <div className="drawer-section-title">Context</div>
            <div className="drawer-card">
                <div className="drawer-card-row">
                    <span className="drawer-card-label">Strategy</span>
                    <div className="drawer-segmented">
                        <button className={`drawer-seg-btn ${params.context_strategy === 'rounds' ? 'active' : ''}`} onClick={() => setParams({ context_strategy: 'rounds' })}>Rounds</button>
                        <button className={`drawer-seg-btn ${params.context_strategy === 'tokens' ? 'active' : ''}`} onClick={() => setParams({ context_strategy: 'tokens' })}>Tokens</button>
                    </div>
                </div>
                <div className="drawer-card-divider" />
                {params.context_strategy === 'rounds' ? (
                    <>
                        <div className="drawer-card-row">
                            <span className="drawer-card-label">Keep Rounds</span>
                            <span className="drawer-card-value">{params.context_rounds}</span>
                        </div>
                        <div className="drawer-card-slider">
                            <input type="range" min={1} max={50} step={1} value={params.context_rounds} onChange={e => setParams({ context_rounds: +e.target.value })} />
                        </div>
                    </>
                ) : (
                    <div className="drawer-card-row">
                        <span className="drawer-card-label">Threshold</span>
                        <input type="number" className="drawer-card-input" value={params.context_token_threshold} min={1000} max={200000} step={1000} onChange={e => setParams({ context_token_threshold: +e.target.value })} />
                    </div>
                )}
            </div>
        </div>
    )
}
