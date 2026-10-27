import type { ChatMessage, PipeStageState } from '../types'

export type SessionView = {
  messages: ChatMessage[]
  sending: boolean
  pipeState: Record<string, PipeStageState>
  pipeLabel: string
  sources: string[]
}

export type StreamRequest = {
  controller: AbortController
  startedAt: number
  reason?: 'stop' | 'timeout'
}

export type ChatSession = {
  id: string
  view: SessionView
  loaded: boolean
  request?: StreamRequest
  history?: AbortController
}

// One store per authenticated identity; switching the selected session only changes
// the view subscription. Every running stream keeps its own state and controller.
export class ChatSessions {
  private sessions = new Map<string, ChatSession>()
  private listeners = new Set<() => void>()

  constructor(private readonly emptyPipe: () => Record<string, PipeStageState>) {}

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  get(id: string): ChatSession {
    let session = this.sessions.get(id)
    if (!session) {
      session = { id, loaded: false, view: {
        messages: [], sending: false, pipeState: this.emptyPipe(), pipeLabel: '就绪', sources: [],
      } }
      this.sessions.set(id, session)
    }
    return session
  }

  owns(session: ChatSession) {
    return this.sessions.get(session.id) === session
  }

  localSessionIds() {
    return [...this.sessions.values()]
      .filter((session) => session.view.messages.length > 0 || session.request)
      .map((session) => session.id)
  }

  update(session: ChatSession, change: (view: SessionView) => SessionView) {
    if (!this.owns(session)) return
    session.view = change(session.view)
    this.listeners.forEach((listener) => listener())
  }

  begin(session: ChatSession): StreamRequest | null {
    if (!this.owns(session) || session.request) return null
    session.history?.abort()
    session.history = undefined
    session.loaded = true
    const request: StreamRequest = { controller: new AbortController(), startedAt: performance.now() }
    session.request = request
    return request
  }

  isActive(session: ChatSession, request: StreamRequest) {
    return this.owns(session) && session.request === request
  }

  clear(id: string) {
    const previous = this.sessions.get(id)
    // Remove ownership before aborting so late callbacks cannot modify new state.
    this.sessions.delete(id)
    previous?.request?.controller.abort()
    previous?.history?.abort()
    this.get(id).loaded = true
    this.listeners.forEach((listener) => listener())
  }

  dispose() {
    const previous = [...this.sessions.values()]
    this.sessions.clear()
    for (const session of previous) {
      session.request?.controller.abort()
      session.history?.abort()
    }
    this.listeners.forEach((listener) => listener())
  }
}
