import { useState, useEffect } from 'react'
import useStore from '../stores/useStore'
import { deleteSession, updateSession } from '../utils/api'

export default function Sidebar() {
    const {
        sessions, activeSessionId, setActiveSessionId,
        setActiveSession, setShowSettings,
        agentMode, toggleAgentMode,
        loadSessions, selectSession, createNewSession,
    } = useStore()

    const [renamingId, setRenamingId] = useState(null)
    const [renameVal, setRenameVal] = useState('')
    const [confirmDeleteId, setConfirmDeleteId] = useState(null)

    useEffect(() => { loadSessions() }, [])

    const handleDeleteClick = (e, id) => {
        e.stopPropagation()
        setConfirmDeleteId(id)
    }

    const confirmDelete = async (e, id) => {
        e.stopPropagation()
        await deleteSession(id)
        if (activeSessionId === id) { setActiveSessionId(null); setActiveSession(null) }
        setConfirmDeleteId(null)
        await loadSessions()
    }

    const cancelDelete = (e) => {
        e.stopPropagation()
        setConfirmDeleteId(null)
    }

    const startRename = (e, s) => {
        e.stopPropagation()
        setRenamingId(s.id)
        setRenameVal(s.name)
    }

    const submitRename = async (id) => {
        if (renameVal.trim()) await updateSession(id, { name: renameVal.trim() })
        setRenamingId(null)
        await loadSessions()
    }

    return (
        <div className="sidebar">
            <div className="sidebar-header">
                <div className="sidebar-logo">
                    <div className="sidebar-logo-icon">🤖</div>
                    <span className="sidebar-logo-text">Multi-Agent</span>
                </div>
                <button className="new-session-btn" onClick={createNewSession}>
                    <span>+</span> 新对话
                </button>
            </div>

            {/* Agent 模式开关 */}
            <div className="agent-mode-toggle">
                <span className="agent-mode-label">
                    {agentMode ? '🧠 Agent 模式' : '💬 直接对话'}
                </span>
                <label className="toggle-switch">
                    <input type="checkbox" checked={agentMode} onChange={toggleAgentMode} />
                    <span className="toggle-slider" />
                </label>
            </div>

            <div className="sidebar-sessions">
                {sessions.length === 0 && (
                    <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>
                        暂无对话，点击上方"新对话"开始
                    </div>
                )}
                {sessions.map(s => (
                    <div
                        key={s.id}
                        className={`session-item ${activeSessionId === s.id ? 'active' : ''}`}
                        onClick={() => selectSession(s.id)}
                    >
                        <span className="session-item-icon">💬</span>
                        <div className="session-item-info">
                            {renamingId === s.id ? (
                                <input
                                    className="rename-input"
                                    value={renameVal}
                                    onChange={e => setRenameVal(e.target.value)}
                                    onBlur={() => submitRename(s.id)}
                                    onKeyDown={e => { if (e.key === 'Enter') submitRename(s.id); if (e.key === 'Escape') setRenamingId(null) }}
                                    autoFocus
                                    onClick={e => e.stopPropagation()}
                                />
                            ) : (
                                <div className="session-item-name">{s.name}</div>
                            )}
                            <div className="session-item-meta">{s.message_count} 条消息</div>
                        </div>
                        {confirmDeleteId === s.id ? (
                            <div className="session-confirm-delete" onClick={e => e.stopPropagation()}>
                                <button className="confirm-del-btn yes" onClick={e => confirmDelete(e, s.id)}>确认</button>
                                <button className="confirm-del-btn no" onClick={cancelDelete}>取消</button>
                            </div>
                        ) : (
                            <div className="session-item-actions">
                                <button className="icon-btn" title="重命名" onClick={e => startRename(e, s)}>✏️</button>
                                <button className="icon-btn danger" title="删除" onClick={e => handleDeleteClick(e, s.id)}>🗑</button>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            <div className="sidebar-footer">
                <button className="settings-btn" onClick={() => setShowSettings(true)}>
                    ⚙️ 设置 / API Key
                </button>
            </div>
        </div>
    )
}
