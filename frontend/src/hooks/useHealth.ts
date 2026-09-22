import { useCallback, useEffect, useState } from 'react'
import { fetchJson } from '../api/client'
import type { HealthInfo } from '../types'

export function useHealth(intervalMs = 10000) {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [online, setOnline] = useState(false)

  const refresh = useCallback(async () => {
    const h = await fetchJson<HealthInfo>('/health')
    if (!h) {
      setOnline(false)
      setHealth(null)
      return
    }
    setHealth(h)
    setOnline(h.status === 'healthy')
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => void refresh(), intervalMs)
    return () => window.clearInterval(id)
  }, [refresh, intervalMs])

  return { health, online, refresh }
}
