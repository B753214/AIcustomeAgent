export type StageKey =
  | 'rate_limit'
  | 'cache'
  | 'crew'
  | 'alarm_fetch'
  | 'alarm'
  | 'intent'
  | 'retrieve'
  | 'generate'
  | 'save'
  | 'error'
  | string

export type StageStatus = 'wait' | 'run' | 'ok' | 'err' | 'skip'

export type PipeStageState = {
  status: StageStatus
  ms: number | null
  desc: string
}

export type ChatMessage = {
  id: string
  role: 'user' | 'ai'
  content: string
  meta?: string
  typing?: boolean
}

export type SessionItem = {
  session_id: string
  created_at?: string
}

export type HealthInfo = {
  status?: string
  llm_model?: string
  embedding_model?: string
  postgres?: string
  milvus?: string
}

export type StatsInfo = {
  total_chunks?: number
  bm25_ready?: boolean
  use_crew?: boolean
  crew_available?: boolean
  ratelimit_blocked?: number
}

export type TraceEntry = {
  ts?: number
  message?: string
  session_id?: string
  intent?: string
  engine?: string
  cache_checked?: boolean
  cache_hit?: boolean
  total_ms?: number
  status?: number
}

export type TraceSummary = {
  cache_hit_rate?: number
  p95_ms?: number
  total?: number
  blocked?: number
}
