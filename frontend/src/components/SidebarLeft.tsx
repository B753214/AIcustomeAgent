import { useEffect, useState } from 'react'
import {
  fetchJson,
  getStoredApiKey,
  getStoredUserId,
  setStoredApiKey,
  setStoredUserId,
} from '../api/client'
import type { HealthInfo, SessionItem } from '../types'

type Props = {
  sessionId: string
  apiKey: string
  userId: string
  health: HealthInfo | null
  onSessionIdChange: (id: string) => void
  onApiKeyChange: (key: string) => void
  onUserIdChange: (id: string) => void
  onNewSession: () => void
  onClearChat: () => void
  onSwitchSession: (id: string) => void
  refreshToken: number
}

export function SidebarLeft({
  sessionId,
  apiKey,
  userId,
  health,
  onSessionIdChange,
  onApiKeyChange,
  onUserIdChange,
  onNewSession,
  onClearChat,
  onSwitchSession,
  refreshToken,
}: Props) {
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [showKey, setShowKey] = useState(false)

  useEffect(() => {
    void fetchJson<SessionItem[]>('/sessions', { method: 'POST' }).then((list) => {
      setSessions(Array.isArray(list) ? list : [])
    })
  }, [refreshToken])

  return (
    <div className="sidebar-left">
      <div className="section">
        <div className="section-title">会话管理</div>
        <input
          className="session-input"
          value={sessionId}
          placeholder="Session ID"
          spellCheck={false}
          onChange={(e) => onSessionIdChange(e.target.value)}
        />
        <div className="session-actions">
          <button className="btn sm" type="button" onClick={onNewSession}>
            新建会话
          </button>
          <button className="btn ghost sm" type="button" onClick={onClearChat}>
            清空聊天
          </button>
        </div>
      </div>

      <div className="section" style={{ borderTop: '1px solid var(--line)', paddingTop: 12 }}>
        <div className="section-title">用户隔离</div>
        <input
          className="session-input"
          value={userId}
          placeholder="X-User-Id（空=anonymous）"
          spellCheck={false}
          autoComplete="off"
          onChange={(e) => {
            onUserIdChange(e.target.value)
            setStoredUserId(e.target.value)
          }}
          onBlur={() => setStoredUserId(userId || getStoredUserId())}
        />
        <div className="api-key-hint">切换用户后，「我的记忆」会按此 ID 刷新</div>
      </div>

      <div className="section" style={{ borderTop: '1px solid var(--line)', paddingTop: 12 }}>
        <div className="section-title">API 鉴权</div>
        <div className="api-key-row">
          <input
            className="session-input"
            type={showKey ? 'text' : 'password'}
            value={apiKey}
            placeholder="X-API-Key"
            spellCheck={false}
            autoComplete="off"
            onChange={(e) => {
              onApiKeyChange(e.target.value)
              setStoredApiKey(e.target.value)
            }}
            onBlur={() => setStoredApiKey(apiKey || getStoredApiKey())}
          />
          <button className="btn ghost sm" type="button" onClick={() => setShowKey((v) => !v)}>
            {showKey ? '🙈' : '👁'}
          </button>
        </div>
        <div className={`api-key-hint ${apiKey.trim() ? '' : 'warn'}`}>
          {apiKey.trim()
            ? '已保存到当前标签页 sessionStorage'
            : '服务端开启鉴权时必填；留空则不携带 Key'}
        </div>
      </div>

      <div className="section-title" style={{ padding: '0 12px' }}>
        历史会话
      </div>
      <div className="session-list">
        {!sessions.length ? (
          <div style={{ color: 'var(--muted)', fontSize: 11, padding: 8 }}>暂无历史会话</div>
        ) : (
          sessions.map((s) => {
            const id = s.session_id
            const active = id === sessionId.trim()
            const time = s.created_at
              ? new Date(s.created_at).toLocaleString('zh-CN', {
                  month: '2-digit',
                  day: '2-digit',
                  hour: '2-digit',
                  minute: '2-digit',
                })
              : ''
            return (
              <div
                key={id}
                className={`session-item${active ? ' active' : ''}`}
                title={id}
                onClick={() => onSwitchSession(id)}
              >
                {time} {id.slice(0, 8)}…
              </div>
            )
          })
        )}
      </div>

      <div className="health-info">
        <div>
          <span className="label">LLM: </span>
          <span className="val">{health?.llm_model || '-'}</span>
        </div>
        <div>
          <span className="label">Embed: </span>
          <span className="val">{health?.embedding_model || '-'}</span>
        </div>
        <div>
          <span className="label">PG: </span>
          <span className="val" style={{ color: health?.postgres === 'ok' ? 'var(--ok)' : 'var(--err)' }}>
            {health?.postgres || '-'}
          </span>
        </div>
        <div>
          <span className="label">Milvus: </span>
          <span className="val" style={{ color: health?.milvus === 'ok' ? 'var(--ok)' : 'var(--err)' }}>
            {health?.milvus || '-'}
          </span>
        </div>
      </div>
    </div>
  )
}
