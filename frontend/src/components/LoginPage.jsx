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
                    <div className="login-logo">◉</div>
                    <h1>The Machine</h1>
                    <p>Multi-Agent System</p>
                </div>
                <form className="login-form" onSubmit={handleSubmit}>
                    {error && <div className="login-error">{error}</div>}
                    <div className="login-field">
                        <label htmlFor="login-username">Operator ID</label>
                        <input
                            id="login-username"
                            type="text"
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            placeholder="Enter operator ID"
                            autoFocus
                            autoComplete="username"
                        />
                    </div>
                    <div className="login-field">
                        <label htmlFor="login-password">Access Code</label>
                        <input
                            id="login-password"
                            type="password"
                            value={password}
                            onChange={e => setPassword(e.target.value)}
                            placeholder="Enter access code"
                            autoComplete="current-password"
                        />
                    </div>
                    <button
                        type="submit"
                        className="login-submit"
                        disabled={loading || !username.trim() || !password.trim()}
                    >
                        {loading ? 'Authenticating...' : 'Initialize'}
                    </button>
                </form>
                <div className="login-footer">
                    <span>Secure connection</span>
                </div>
            </div>
        </div>
    )
}
