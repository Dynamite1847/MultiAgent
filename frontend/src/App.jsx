import { useState, useEffect, useCallback } from 'react'
import useStore from './stores/useStore'
import LoginPage from './components/LoginPage'
import Sidebar from './components/Sidebar'
import ChatPanel from './components/ChatPanel'
import InputBar from './components/InputBar'
import ParamDrawer from './components/ParamDrawer'
import Workflow from './components/Workflow'
import SettingsModal from './components/SettingsModal'

function ToastContainer() {
    const toasts = useStore(s => s.toasts)
    return (
        <div className="toast-container">
            {toasts.map(t => (
                <div key={t.id} className={`toast ${t.type}`}>{t.msg}</div>
            ))}
        </div>
    )
}

export default function App() {
    const init = useStore(s => s.init)
    const agentMode = useStore(s => s.agentMode)
    const showSettings = useStore(s => s.showSettings)

    // Auth state
    const [isAuthenticated, setIsAuthenticated] = useState(() => {
        return !!localStorage.getItem('auth_token')
    })
    const [currentUser, setCurrentUser] = useState(() => {
        try {
            return JSON.parse(localStorage.getItem('auth_user') || 'null')
        } catch { return null }
    })

    const handleLogin = useCallback((token, user) => {
        localStorage.setItem('auth_token', token)
        localStorage.setItem('auth_user', JSON.stringify(user))
        setIsAuthenticated(true)
        setCurrentUser(user)
    }, [])

    const handleLogout = useCallback(() => {
        localStorage.removeItem('auth_token')
        localStorage.removeItem('auth_user')
        setIsAuthenticated(false)
        setCurrentUser(null)
    }, [])

    // Mobile state
    const [sidebarOpen, setSidebarOpen] = useState(false)
    const [sidePanelOpen, setSidePanelOpen] = useState(false)

    useEffect(() => {
        if (isAuthenticated) init()
    }, [isAuthenticated])

    if (!isAuthenticated) {
        return <LoginPage onLogin={handleLogin} />
    }

    return (
        <div className="app-layout">
            {/* Mobile overlay */}
            {(sidebarOpen || sidePanelOpen) && (
                <div
                    className="mobile-overlay"
                    onClick={() => { setSidebarOpen(false); setSidePanelOpen(false) }}
                />
            )}

            <Sidebar
                isOpen={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
                currentUser={currentUser}
                onLogout={handleLogout}
            />

            <div className="main-area">
                <div className="main-content">
                    <div className="chat-section">
                        <ChatPanel
                            onMenuClick={() => setSidebarOpen(true)}
                            onPanelToggle={() => setSidePanelOpen(v => !v)}
                        />
                        <InputBar />
                    </div>
                    <div className={`side-panel ${sidePanelOpen ? 'open' : ''}`}>
                        {agentMode ? <Workflow /> : <ParamDrawer />}
                    </div>
                </div>
            </div>

            {showSettings && <SettingsModal />}
            <ToastContainer />
        </div>
    )
}
