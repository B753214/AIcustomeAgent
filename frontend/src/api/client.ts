const API_KEY_STORAGE = 'dashboard_api_key'

export function getStoredApiKey(): string {
  return (sessionStorage.getItem(API_KEY_STORAGE) || '').trim()
}

export function setStoredApiKey(key: string) {
  sessionStorage.setItem(API_KEY_STORAGE, key.trim())
}

export function apiHeaders(extra: Record<string, string> = {}, apiKey?: string): HeadersInit {
  const headers: Record<string, string> = { ...extra }
  const key = (apiKey ?? getStoredApiKey()).trim()
  if (key) headers['X-API-Key'] = key
  return headers
}

export function formatHttpError(j: unknown, status: number): string {
  const detail = (j as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => (d as { msg?: string }).msg || JSON.stringify(d)).join('; ')
  }
  return `HTTP ${status}`
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T | null> {
  try {
    const resp = await fetch(url, init)
    if (!resp.ok) return null
    return (await resp.json()) as T
  } catch {
    return null
  }
}

export function fmtTs(t?: number): string {
  if (!t) return '-'
  const d = new Date(t * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export function fmtMs(v?: number | null): string {
  if (v == null) return '-'
  return v < 1000 ? `${v}ms` : `${(v / 1000).toFixed(1)}s`
}

export function newSessionId(): string {
  if (crypto.randomUUID) return crypto.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}
