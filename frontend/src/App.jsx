import { useEffect } from 'react'
import useStore from './stores/useStore'
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

    useEffect(() => { init() }, [])

    return (
        <div className="app-layout">
            <Sidebar />
            <div className="main-area">
                <div className="main-content">
                    <div className="chat-section">
                        <ChatPanel />
                        <InputBar />
                    </div>
                    <div className="side-panel">
                        {agentMode ? <Workflow /> : <ParamDrawer />}
                    </div>
                </div>
            </div>
            {showSettings && <SettingsModal />}
            <ToastContainer />
        </div>
    )
}
