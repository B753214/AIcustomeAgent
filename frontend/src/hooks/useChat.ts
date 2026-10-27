import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from 'react'
import { consumeChatStream, type ChatEvent } from '../api/chatStream'
import { ChatSessions, type ChatSession, type StreamRequest } from '../api/chatSessions'
import { apiHeaders, formatHttpError } from '../api/client'
import { INTENT_LABEL, STAGE_MAP, STAGES } from '../constants'
import type { ChatMessage, PipeStageState, StageKey, StageStatus } from '../types'

function emptyPipe(): Record<string, PipeStageState> {
  return Object.fromEntries(STAGES.map((stage) => [stage.key, { status: 'wait', ms: null, desc: '' }]))
}

const STREAM_IDLE_MS = 120_000
let msgSeq = 0
function nextId() {
  return `m-${Date.now()}-${++msgSeq}`
}

export function useChat(sessionId: string, apiKey: string, userId: string, onDone?: () => void) {
  const sid = sessionId.trim() || 'default'
  const store = useMemo(() => new ChatSessions(emptyPipe), [apiKey, userId])
  const snapshot = useCallback(() => store.get(sid).view, [store, sid])
  const view = useSyncExternalStore(store.subscribe, snapshot)
  const onDoneRef = useRef(onDone)
  onDoneRef.current = onDone

  // Session changes retain all requests. Identity changes/unmount release them.
  useEffect(() => () => store.dispose(), [store])

  const clearChat = useCallback(() => store.clear(sid), [store, sid])
  const stopChat = useCallback(() => {
    const request = store.get(sid).request
    if (request) {
      request.reason = 'stop'
      request.controller.abort()
    }
  }, [store, sid])

  const loadHistory = useCallback(async (id: string) => {
    const session = store.get(id.trim() || 'default')
    // Local live/completed results take precedence over a possibly older DB snapshot.
    if (session.loaded || session.request || session.history) return
    const controller = new AbortController()
    session.history = controller
    const isValid = () => store.owns(session) && session.history === controller
      && !controller.signal.aborted && !session.request
    try {
      const resp = await fetch(`/api/v1/sessions/${encodeURIComponent(session.id)}/history`, {
        signal: controller.signal,
        headers: apiHeaders({}, apiKey, userId),
      })
      if (resp.status === 404) {
        if (isValid()) session.loaded = true
        return
      }
      if (!resp.ok) throw new Error('load failed')
      const data = (await resp.json()) as { messages?: { role: string; content: string }[] }
      if (!isValid()) return
      session.loaded = true
      store.update(session, (previous) => ({ ...previous,
        messages: (data.messages || []).map((message) => ({
          id: nextId(), role: message.role === 'user' ? 'user' : 'ai', content: message.content,
        })),
      }))
    } catch {
      if (isValid()) store.update(session, (previous) => ({ ...previous,
        messages: [{ id: nextId(), role: 'ai', content: '加载历史消息失败，请重新选择会话重试' }],
      }))
    } finally {
      if (session.history === controller) session.history = undefined
    }
  }, [apiKey, store, userId])

  useEffect(() => { void loadHistory(sid) }, [loadHistory, sid])

  const updateStage = useCallback((session: ChatSession, key: StageKey, status: StageStatus,
    ms: number | null, desc?: string) => {
    store.update(session, (previous) => {
      const current = previous.pipeState[key]
      if (!current && !STAGES.some((stage) => stage.key === key)) return previous
      if (status === 'skip' && current?.status === 'ok') return previous
      return { ...previous, pipeState: { ...previous.pipeState,
        [key]: { status, ms: ms ?? current?.ms ?? null, desc: desc || current?.desc || '' },
      } }
    })
  }, [store])

  const processEvent = useCallback(
    (session: ChatSession, request: StreamRequest, ev: ChatEvent, bubbleId: string) => {
      const elapsed = () => Math.round(performance.now() - request.startedAt)
      const markStage = (key: StageKey, status: StageStatus, ms: number | null, desc?: string) =>
        updateStage(session, key, status, ms, desc)
      const setMessages = (change: (messages: ChatMessage[]) => ChatMessage[]) =>
        store.update(session, (view) => ({ ...view, messages: change(view.messages) }))
      const setPipeLabel = (pipeLabel: string) =>
        store.update(session, (view) => ({ ...view, pipeLabel }))
      const setSources = (sources: string[]) =>
        store.update(session, (view) => ({ ...view, sources }))
      if (ev.type === 'stage' || ev.type === 'workflow.step') {
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
          markStage(key, status, ms, String(ev.message || ev.msg || ev.stage))
        }
      } else if (ev.type === 'route.selected' || ev.type === 'intent') {
        markStage('intent', 'ok', elapsed(), `意图: ${ev.intent || ev.agent_id || ev.agent || "-"}`)
      } else if (ev.type.startsWith('tool.')) {
        const failed = ev.type === 'tool.failed'
        markStage('generate', failed ? 'err' : ev.type === 'tool.completed' ? 'ok' : 'run',
          elapsed(), `工具 ${String(ev.tool || ev.name || '')}：${failed ? '失败' : ev.type === 'tool.completed' ? '完成' : '执行中'}`)
      } else if (ev.type === 'model.started') {
        markStage('generate', 'run', null, '生成中…')
      } else if (ev.type === 'token' || ev.type === 'model.token') {
        const text = String(ev.content || ev.reply || '')
        if (session.view.pipeState.generate?.status === 'wait') {
          markStage('retrieve', 'ok', elapsed(), '检索完成')
          markStage('generate', 'run', null, '生成中…')
        }
        setMessages((prev) =>
          prev.map((m) => (m.id === bubbleId ? { ...m, content: m.content + text, typing: true } : m)),
        )
      } else if (ev.type === 'run.failed' || ev.type === 'error') {
        throw new Error(String(ev.message || ev.detail || '任务执行失败'))
      } else if (ev.type === 'done' || ev.type === 'run.completed') {
        const metadata = (ev.metadata || ev.meta || {}) as Record<string, unknown>
        ev = { ...metadata, ...ev }
        const totalMs = Number(ev.total_ms) || elapsed()
        markStage('generate', 'ok', elapsed(), '生成完成')
        markStage('save', 'ok', null, '已保存')
        const hitLabel = ev.cache_hit ? ' · 缓存命中' : ''
        setPipeLabel(`完成 · ${totalMs}ms${hitLabel}`)
        setSources(Array.isArray(ev.sources) ? (ev.sources as string[]) : [])
        const meta = metadata as { fetch_channel?: string }
        const crewLabel = ev.used_crew ? ' · crew' : ''
        const fetchCh = meta?.fetch_channel ? ` · ${meta.fetch_channel}` : ''
        const intent = String(ev.intent || '-')
        const label = `${INTENT_LABEL[intent] || intent} · ${String(ev.engine || 'langchain')}${crewLabel}${fetchCh} · ${totalMs}ms${hitLabel}`
        setMessages((prev) =>
          prev.map((m) => (m.id === bubbleId ? { ...m, content: typeof ev.output === 'string' ? ev.output : typeof ev.reply === 'string' ? ev.reply : m.content, typing: false, meta: label } : m)),
        )
      }
    },
    [store, updateStage],
  )

  const sendChat = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      const session = store.get(sid)
      const request = store.begin(session)
      if (!request) return
      const isValid = () => store.isActive(session, request)
      let timer: ReturnType<typeof setTimeout> | undefined
      const resetTimeout = () => {
        clearTimeout(timer)
        timer = setTimeout(() => {
          request.reason = 'timeout'
          request.controller.abort()
        }, STREAM_IDLE_MS)
      }
      const userMsg: ChatMessage = { id: nextId(), role: 'user', content: trimmed }
      const bubbleId = nextId()
      store.update(session, (previous) => ({ ...previous,
        messages: [...previous.messages, userMsg, { id: bubbleId, role: 'ai', content: '', typing: true }],
        pipeState: emptyPipe(), pipeLabel: '处理中…', sources: [], sending: true,
      }))

      resetTimeout()
      try {
        const resp = await fetch('/api/v1/chat/stream', {
          method: 'POST',
          signal: request.controller.signal,
          headers: apiHeaders({ 'Content-Type': 'application/json' }, apiKey, userId),
          body: JSON.stringify({ message: trimmed, session_id: sid }),
        })
        if (!isValid()) return
        if (!resp.ok) {
          const j = await resp.json().catch(() => ({}))
          throw new Error(resp.status === 401
            ? '无效或缺失 API Key，请在左侧「API 鉴权」填写正确 Key'
            : formatHttpError(j, resp.status))
        }
        if (!resp.body) throw new Error('无响应流')
        if (!resp.headers.get('content-type')?.includes('text/event-stream')) {
          throw new Error('服务未返回 SSE 事件流')
        }
        resetTimeout()
        await consumeChatStream(resp.body, (event: ChatEvent) => {
          if (isValid()) processEvent(session, request, event, bubbleId)
        }, request.controller.signal, resetTimeout)
      } catch (err) {
        if (!isValid()) return
        const stopped = request.reason === 'stop'
        const message = stopped ? '已停止接收，本次执行可能尚未在服务端结束'
          : request.reason === 'timeout' ? '等待响应超过 120 秒，连接已中断'
          : err instanceof Error ? err.message : String(err)
        console.warn('Chat stream ended:', stopped ? 'user stopped' : message)
        store.update(session, (previous) => ({ ...previous,
          messages: previous.messages.map((messageRow) => messageRow.id === bubbleId
            ? { ...messageRow, content: messageRow.content.trim() ? messageRow.content
                : (stopped ? '已停止接收' : '未收到完整回答'),
                meta: `⚠️ ${message}`, typing: false } : messageRow),
          pipeLabel: stopped ? '已停止接收' : '回答中断',
        }))
        updateStage(session, 'error', stopped ? 'skip' : 'err',
          Math.round(performance.now() - request.startedAt), message)
      } finally {
        clearTimeout(timer)
        request.controller.abort()
        if (isValid()) {
          session.request = undefined
          store.update(session, (previous) => ({ ...previous, sending: false,
            messages: previous.messages.map((message) => message.id === bubbleId
              ? { ...message, typing: false, content: message.content.trim() ? message.content : '（无输出）' }
              : message),
          }))
          onDoneRef.current?.()
        }
      }
    },
    [apiKey, processEvent, sid, store, updateStage, userId],
  )

  return { ...view, localSessionIds: store.localSessionIds(), sendChat, stopChat, clearChat, loadHistory }
}
