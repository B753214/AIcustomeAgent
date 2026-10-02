import { useCallback, useEffect, useState } from 'react'
import { apiHeaders, fetchJson } from '../api/client'
import type { StatsInfo, TraceEntry, TraceSummary } from '../types'

export function useMetrics(apiKey = '', userId = '', intervalMs = 3000) {
  const [stats, setStats] = useState<StatsInfo | null>(null)
  const [summary, setSummary] = useState<TraceSummary>({})
  const [entries, setEntries] = useState<TraceEntry[]>([])
  const [updatedAt, setUpdatedAt] = useState(Date.now() / 1000)

  const refresh = useCallback(async () => {
    const headers = apiHeaders({}, apiKey, userId)
    const [s, t] = await Promise.all([
      fetchJson<StatsInfo>('/api/v1/stats', { headers }),
      fetchJson<{ summary?: TraceSummary; entries?: TraceEntry[] }>(
        '/api/v1/traces?limit=20',
        { headers },
      ),
    ])
    if (s) setStats(s)
    setSummary(t?.summary || {})
    setEntries(t?.entries || [])
    setUpdatedAt(Date.now() / 1000)
  }, [apiKey, userId])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), intervalMs)
    return () => window.clearInterval(id)
  }, [refresh, intervalMs])

  return { stats, summary, entries, updatedAt, refresh }
}
