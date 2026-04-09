import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const ROLE_STYLES = {
    user: { avatar: '◉', className: 'user' },
    assistant: { avatar: '◈', className: 'assistant' },
    system: { avatar: '▣', className: 'system' },
}

export default function MessageItem({ message, isLast, canRetry, canEdit, onRetry, onEdit, isStreaming }) {
    const role = ROLE_STYLES[message.role] || ROLE_STYLES.assistant
    const content = message.content
    const [copied, setCopied] = useState(false)

    const handleCopy = () => {
        const text = typeof content === 'string' ? content
            : Array.isArray(content) ? content.filter(p => p.type === 'text').map(p => p.text).join('\n') : ''
        navigator.clipboard.writeText(text).then(() => {
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
        })
    }

    return (
        <div className={`chat-message ${role.className}`}>
            <div className="chat-message-avatar">{role.avatar}</div>
            <div className="chat-message-body">
                <div className="chat-message-content">
                    {message.role === 'user' ? (
                        typeof content === 'string' ? (
                            <p>{content}</p>
                        ) : (
                            <div>
                                {(Array.isArray(content) ? content : []).map((part, j) =>
                                    part.type === 'text' ? <p key={j}>{part.text}</p> :
                                    part.type === 'image_url' ? <img key={j} src={part.image_url.url} alt="" className="msg-image" /> : null
                                )}
                            </div>
                        )
                    ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {content || ''}
                        </ReactMarkdown>
                    )}
                </div>

                {/* 操作按钮 */}
                {!isStreaming && (
                    <div className="chat-message-actions">
                        {message.role === 'assistant' && (
                            <button className="msg-action-btn" onClick={handleCopy} title="复制内容">
                                {copied ? '✓ COPIED' : 'COPY'}
                            </button>
                        )}
                        {canRetry && (
                            <button className="msg-action-btn" onClick={onRetry} title="重新生成">
                                ▸ RETRY
                            </button>
                        )}
                        {canEdit && (
                            <button className="msg-action-btn" onClick={onEdit} title="编辑此消息">
                                ▸ EDIT
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
