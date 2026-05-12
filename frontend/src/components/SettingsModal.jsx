import { useState } from 'react'
import useStore from '../stores/useStore'
import { saveConfig, fetchConfig } from '../utils/api'

export default function SettingsModal() {
    const { config, setConfig, setShowSettings, addToast } = useStore()
    const [draft, setDraft] = useState(() => JSON.parse(JSON.stringify(config || {})))
    const [saving, setSaving] = useState(false)

    const update = (path, value) => {
        setDraft(prev => {
            const next = JSON.parse(JSON.stringify(prev))
            const keys = path.split('.')
            let obj = next
            for (let i = 0; i < keys.length - 1; i++) obj = obj[keys[i]]
            obj[keys[keys.length - 1]] = value
            return next
        })
    }

    const handleSave = async () => {
        setSaving(true)
        try {
            await saveConfig(draft)
            const fresh = await fetchConfig()
            setConfig(fresh)
            setShowSettings(false)
            addToast('配置已保存', 'success')
        } catch (e) {
            addToast('保存失败: ' + e.message, 'error')
        } finally {
            setSaving(false)
        }
    }

    const providerLabels = {
        anthropic: { icon: '⬡', name: 'Anthropic (Claude)', color: 'anthropic' },
        google: { icon: '◈', name: 'Google (Gemini)', color: 'google' },
        openai: { icon: '○', name: 'OpenAI / 兼容接口', color: 'openai' },
        doubao: { icon: '☁️', name: 'Doubao (火山引擎)', color: 'doubao' },
        dashscope: { icon: '🔮', name: 'DashScope (百炼)', color: 'dashscope' },
        mimo: { icon: '📱', name: 'Xiaomi (MiMo)', color: 'mimo' }
    }

    return (
        <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) setShowSettings(false) }}>
            <div className="modal">
                <div className="modal-title">⚙️ API 配置</div>
                <div className="modal-subtitle">配置各提供商的 API Key 和自定义 Base URL（支持中转/代理服务）</div>

                {Object.entries(draft.providers || {}).map(([key, prov]) => {
                    const label = providerLabels[key] || { icon: '○', name: key, color: 'openai' }
                    return (
                        <div key={key} className="modal-provider-block">
                            <div className="modal-provider-title">
                                <div className={`provider-dot ${label.color}`} />
                                {label.icon} {label.name}
                            </div>
                            <div className="modal-row full" style={{ marginBottom: 8 }}>
                                <div>
                                    <div className="modal-label">API Key</div>
                                    <input type="password" className="form-input" value={prov.api_key || ''} onChange={e => update(`providers.${key}.api_key`, e.target.value)} placeholder="sk-..." autoComplete="off" />
                                </div>
                            </div>
                            <div className="modal-row full">
                                <div>
                                    <div className="modal-label">Base URL <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>（自定义代理地址，需包含 /v1）</span></div>
                                    <input type="text" className="form-input" value={prov.base_url || ''} onChange={e => update(`providers.${key}.base_url`, e.target.value)} placeholder="https://your-proxy.com/v1" />
                                </div>
                            </div>
                        </div>
                    )
                })}

                <div className="modal-section">
                    <div className="modal-label">默认提供商</div>
                    <select className="form-select" value={draft.default_provider || 'anthropic'} onChange={e => { const p = e.target.value; const firstModel = draft.providers?.[p]?.models?.[0] || ''; update('default_provider', p); update('default_model', firstModel) }}>
                        {Object.keys(draft.providers || {}).map(p => (
                            <option key={p} value={p}>{providerLabels[p]?.name || p}</option>
                        ))}
                    </select>
                </div>

                <div className="modal-section">
                    <div className="modal-label">默认模型</div>
                    <select className="form-select" value={draft.default_model || ''} onChange={e => update('default_model', e.target.value)}>
                        {(draft.providers?.[draft.default_provider]?.models || []).map(m => (
                            <option key={m} value={m}>{m}</option>
                        ))}
                    </select>
                </div>

                <div className="modal-section">
                    <div className="modal-label">全局 System Prompt</div>
                    <textarea className="form-textarea" rows={3} placeholder="所有会话的默认 System Prompt" value={draft.global_system_prompt || ''} onChange={e => update('global_system_prompt', e.target.value)} />
                </div>

                <div className="modal-footer">
                    <button className="btn-secondary" onClick={() => setShowSettings(false)}>取消</button>
                    <button className="btn-primary" onClick={handleSave} disabled={saving}>
                        {saving ? '保存中…' : '保存配置'}
                    </button>
                </div>
            </div>
        </div>
    )
}
