import { useCallback, useState } from 'react'
import { getStoredApiKey, newSessionId, setStoredApiKey } from './api/client'
import { ChatPanel } from './components/ChatPanel'
import { Header } from './components/Header'
import { SidebarLeft } from './components/SidebarLeft'
import { SidebarRight } from './components/SidebarRight'
import { StatsStrip } from './components/StatsStrip'
import { TracesPanel } from './components/TracesPanel'
import { useChat } from './hooks/useChat'
import { useHealth } from './hooks/useHealth'
import { useMetrics } from './hooks/useMetrics'
import './styles/dashboard.css'

export default function App() {
  const [sessionId, setSessionId] = useState('default')
  const [apiKey, setApiKey] = useState(() => getStoredApiKey())
  const [refreshToken, setRefreshToken] = useState(0)

  const bumpRefresh = useCallback(() => setRefreshToken((n) => n + 1), [])
  const { health, online, refresh: refreshHealth } = useHealth()
  const { stats, summary, entries, updatedAt, refresh: refreshMetrics } = useMetrics()
  const chat = useChat(sessionId, apiKey, () => {
    bumpRefresh()
    void refreshMetrics()
  })

  return (
    <div className="app">
      <Header online={online} health={health} onRefresh={() => void refreshHealth()} />
      <StatsStrip stats={stats} summary={summary} updatedAt={updatedAt} />

      <div className="page-body">
        <div className="main">
          <SidebarLeft
            sessionId={sessionId}
            apiKey={apiKey}
            health={health}
            refreshToken={refreshToken}
            onSessionIdChange={setSessionId}
            onApiKeyChange={(key) => {
              setApiKey(key)
              setStoredApiKey(key)
            }}
            onNewSession={() => {
              const id = newSessionId()
              setSessionId(id)
              chat.clearChat()
            }}
            onClearChat={chat.clearChat}
            onSwitchSession={(id) => {
              setSessionId(id)
              void chat.loadHistory(id)
              bumpRefresh()
            }}
          />

          <ChatPanel messages={chat.messages} sending={chat.sending} onSend={(t) => void chat.sendChat(t)} />

          <SidebarRight
            pipeState={chat.pipeState}
            pipeLabel={chat.pipeLabel}
            sources={chat.sources}
            apiKey={apiKey}
            onUploaded={() => void refreshMetrics()}
          />
        </div>

        <TracesPanel entries={entries} />
      </div>
    </div>
  )
}
