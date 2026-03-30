import { useState } from 'react'

export default function LoginPage({ onLogin }) {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!username.trim() || !password.trim()) return
        setLoading(true)
        setError('')
        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username: username.trim(), password }),
            })
            const data = await res.json()
            if (!res.ok) {
                setError(data.detail || '登录失败')
                return
            }
            onLogin(data.token, data.user)
        } catch (err) {
            setError('网络错误，请检查连接')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="login-page">
            <div className="login-card">
                <div className="login-header">
                    <div className="login-logo">🤖</div>
                    <h1>Multi-Agent Workbench</h1>
                    <p>智能多 Agent 协作平台</p>
                </div>
                <form className="login-form" onSubmit={handleSubmit}>
                    {error && <div className="login-error">{error}</div>}
                    <div className="login-field">
                        <label htmlFor="login-username">用户名</label>
                        <input
                            id="login-username"
                            type="text"
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            placeholder="请输入用户名"
                            autoFocus
                            autoComplete="username"
                        />
                    </div>
                    <div className="login-field">
                        <label htmlFor="login-password">密码</label>
                        <input
                            id="login-password"
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            placeholder="请输入密码"
                            autoComplete="current-password"
                        />
                    </div>
                    <button
                        type="submit"
                        className="login-submit"
                        disabled={loading || !username.trim() || !password.trim()}
                    >
                        {loading ? '登录中…' : '登 录'}
                    </button>
                </form>
                <div className="login-footer">
                    <span>🔒 数据已加密传输</span>
                </div>
            </div>
        </div>
    )
}
