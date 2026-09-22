import { useCallback, useRef, useState } from 'react'
import { apiHeaders, formatHttpError } from '../api/client'
import { INTENT_LABEL, STAGE_MAP, STAGES } from '../constants'
import type { ChatMessage, PipeStageState, StageKey, StageStatus } from '../types'

function emptyPipe(): Record<string, PipeStageState> {
  const state: Record<string, PipeStageState> = {}
  STAGES.forEach((s) => {
    state[s.key] = { status: 'wait', ms: null, desc: '' }
  })
  return state
}

let msgSeq = 0
function nextId() {
  msgSeq += 1
  return `m-${Date.now()}-${msgSeq}`
}

export function useChat(sessionId: string, apiKey: string, onDone?: () => void) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [sending, setSending] = useState(false)
  const [pipeState, setPipeState] = useState(emptyPipe)
  const [pipeLabel, setPipeLabel] = useState('就绪')
  const [sources, setSources] = useState<string[]>([])
  const tStart = useRef(0)
  const pipeRef = useRef(pipeState)
  pipeRef.current = pipeState

  const elapsed = () => Math.round(performance.now() - tStart.current)

  const resetPipeline = useCallback(() => {
    setPipeState(emptyPipe())
    setPipeLabel('就绪')
  }, [])

  const markStage = useCallback((key: StageKey, status: StageStatus, ms: number | null, desc?: string) => {
    setPipeState((prev) => {
      if (!prev[key] && !STAGES.some((s) => s.key === key)) return prev
      const cur = prev[key] || { status: 'wait' as StageStatus, ms: null, desc: '' }
      if (status === 'skip' && cur.status === 'ok') return prev
      return {
        ...prev,
        [key]: {
          status,
          ms: ms != null ? ms : cur.ms,
          desc: desc || cur.desc,
        },
      }
    })
  }, [])

  const clearChat = useCallback(() => {
    setMessages([])
    resetPipeline()
    setSources([])
  }, [resetPipeline])

  const loadHistory = useCallback(async (sid: string) => {
    setMessages([])
    resetPipeline()
    setSources([])
    try {
      const resp = await fetch(`/api/v1/sessions/${encodeURIComponent(sid)}/history`)
      if (!resp.ok) throw new Error('load failed')
      const data = (await resp.json()) as { messages?: { role: string; content: string }[] }
      const msgs = data.messages || []
      if (!msgs.length) return
      setMessages(
        msgs.map((m) => ({
          id: nextId(),
          role: m.role === 'user' ? 'user' : 'ai',
          content: m.content,
        })),
      )
    } catch {
      setMessages([{ id: nextId(), role: 'ai', content: '加载历史消息失败' }])
    }
  }, [resetPipeline])

  const processEvent = useCallback(
    (ev: Record<string, unknown>, bubbleId: string) => {
      if (ev.type === 'stage') {
        const intent = String(ev.name || ev.intent || '')
        if (intent) {
          markStage('intent', 'ok', elapsed(), `意图: ${intent}`)
          if (intent === 'knowledge') markStage('retrieve', 'run', null, '检索知识库…')
          else if (intent === 'order') markStage('retrieve', 'skip', null, '订单查询，跳过检索')
          else if (intent === 'alarm') {
            markStage('retrieve', 'skip', null, '告警排查，跳过检索')
            markStage('alarm', 'run', null, '告警 Agent…')
          } else markStage('retrieve', 'skip', null, '闲聊，跳过检索')
        } else if (ev.stage) {
          const key = STAGE_MAP[String(ev.stage)] || String(ev.stage)
          let status: StageStatus = 'run'
          if (ev.ok === true) status = 'ok'
          else if (ev.ok === false || ev.stage === 'error') status = 'err'
          else if (ev.skipped || ev.hit === false) status = 'skip'
          if (ev.hit === true) status = 'ok'
          const ms = typeof ev.ms === 'number' ? ev.ms : elapsed()
          markStage(key, status, ms, String(ev.msg || ev.stage))
        }
      } else if (ev.type === 'intent') {
        markStage('intent', 'ok', elapsed(), `意图: ${ev.intent}`)
      } else if (ev.type === 'token') {
        const text = String(ev.content || ev.reply || '')
        if (pipeRef.current.generate?.status === 'wait') {
          markStage('retrieve', 'ok', elapsed(), '检索完成')
          markStage('generate', 'run', null, '生成中…')
        }
        setMessages((prev) =>
          prev.map((m) => (m.id === bubbleId ? { ...m, content: m.content + text, typing: true } : m)),
        )
      } else if (ev.type === 'done') {
        const totalMs = Number(ev.total_ms) || elapsed()
        markStage('generate', 'ok', elapsed(), '生成完成')
        markStage('save', 'ok', null, '已保存')
        const hitLabel = ev.cache_hit ? ' · 缓存命中' : ''
        setPipeLabel(`完成 · ${totalMs}ms${hitLabel}`)
        setSources(Array.isArray(ev.sources) ? (ev.sources as string[]) : [])
        const meta = ev.meta as { fetch_channel?: string } | undefined
        const crewLabel = ev.used_crew ? ' · crew' : ''
        const fetchCh = meta?.fetch_channel ? ` · ${meta.fetch_channel}` : ''
        const intent = String(ev.intent || '-')
        const label = `${INTENT_LABEL[intent] || intent} · ${String(ev.engine || 'langchain')}${crewLabel}${fetchCh} · ${totalMs}ms${hitLabel}`
        setMessages((prev) =>
          prev.map((m) => (m.id === bubbleId ? { ...m, typing: false, meta: label } : m)),
        )
        onDone?.()
      }
    },
    [markStage, onDone],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || sending) return
      const sid = sessionId.trim() || 'default'
      const userMsg: ChatMessage = { id: nextId(), role: 'user', content: trimmed }
      const bubbleId = nextId()
      setMessages((prev) => [...prev, userMsg, { id: bubbleId, role: 'ai', content: '', typing: true }])
      resetPipeline()
      setPipeLabel('处理中…')
      setSources([])
      setSending(true)
      tStart.current = performance.now()

      try {
        const resp = await fetch('/api/v1/chat/stream', {
          method: 'POST',
          headers: apiHeaders({ 'Content-Type': 'application/json' }, apiKey),
          body: JSON.stringify({ message: trimmed, session_id: sid }),
        })
        if (!resp.ok) {
          const j = await resp.json().catch(() => ({}))
          const msg =
            resp.status === 401
              ? '无效或缺失 API Key，请在左侧「API 鉴权」填写正确 Key'
              : formatHttpError(j, resp.status)
          setMessages((prev) =>
            prev.map((m) =>
              m.id === bubbleId ? { ...m, content: `⚠️ ${msg}`, typing: false } : m,
            ),
          )
          setPipeLabel(resp.status === 401 ? '鉴权失败' : '请求失败')
          markStage('error', 'err', null, `HTTP ${resp.status}`)
          return
        }
        if (!resp.body) throw new Error('无响应流')
        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            if (buf.trim()) {
              const line = buf.split('\n').find((l) => l.startsWith('data:'))
              if (line) {
                try {
                  processEvent(JSON.parse(line.slice(5).trim()), bubbleId)
                } catch {
                  /* ignore */
                }
              }
            }
            break
          }
          buf += decoder.decode(value, { stream: true })
          const parts = buf.split('\n\n')
          buf = parts.pop() || ''
          for (const part of parts) {
            if (!part.trim()) continue
            const line = part.split('\n').find((l) => l.startsWith('data:'))
            if (!line) continue
            try {
              processEvent(JSON.parse(line.slice(5).trim()), bubbleId)
            } catch {
              /* ignore */
            }
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        setMessages((prev) =>
          prev.map((m) =>
            m.id === bubbleId ? { ...m, content: `⚠️ 网络错误：${message}`, typing: false } : m,
          ),
        )
        setPipeLabel('连接失败')
      } finally {
        setSending(false)
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== bubbleId) return m
            return {
              ...m,
              typing: false,
              content: m.content.trim() ? m.content : '（无输出）',
            }
          }),
        )
        onDone?.()
      }
    },
    [apiKey, markStage, onDone, processEvent, resetPipeline, sending, sessionId],
  )

  return {
    messages,
    sending,
    pipeState,
    pipeLabel,
    sources,
    sendChat,
    clearChat,
    loadHistory,
    resetPipeline,
    setMessages,
  }
}
