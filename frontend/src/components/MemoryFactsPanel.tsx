import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiHeaders, formatHttpError } from '../api/client'
import type { MemoryFact } from '../types'

type Props = {
  apiKey: string
  userId: string
  refreshToken?: number
}

type FilterTab = 'all' | 'candidate' | 'active'

const KIND_LABEL: Record<string, string> = {
  profile: '身份',
  preference: '偏好',
  constraint: '约束',
  business_fact: '业务',
}

async function readError(resp: Response): Promise<string> {
  const j = await resp.json().catch(() => ({}))
  if (resp.status === 401) return '无效或缺失 API Key'
  return formatHttpError(j, resp.status)
}

export function MemoryFactsPanel({ apiKey, userId, refreshToken = 0 }: Props) {
  const [facts, setFacts] = useState<MemoryFact[]>([])
  const [filter, setFilter] = useState<FilterTab>('all')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [draft, setDraft] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const resp = await fetch('/api/v1/memory/facts?limit=100', {
        headers: apiHeaders({}, apiKey, userId),
      })
      if (!resp.ok) throw new Error(await readError(resp))
      const data = (await resp.json()) as MemoryFact[]
      setFacts(Array.isArray(data) ? data : [])
    } catch (err) {
      setFacts([])
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [apiKey, userId])

  useEffect(() => {
    void load()
  }, [load, refreshToken])

  const visible = useMemo(() => {
    if (filter === 'all') return facts
    return facts.filter((f) => f.status === filter)
  }, [facts, filter])

  const runAction = async (id: string, action: () => Promise<void>) => {
    setBusyId(id)
    setError('')
    try {
      await action()
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  const onConfirm = (id: string) =>
    void runAction(id, async () => {
      const resp = await fetch(`/api/v1/memory/facts/${encodeURIComponent(id)}/confirm`, {
        method: 'POST',
        headers: apiHeaders({}, apiKey, userId),
      })
      if (!resp.ok) throw new Error(await readError(resp))
    })

  const onForget = (id: string) => {
    if (!window.confirm('确定遗忘这条记忆？列表中将不再显示。')) return
    void runAction(id, async () => {
      const resp = await fetch(`/api/v1/memory/facts/${encodeURIComponent(id)}/forget`, {
        method: 'POST',
        headers: apiHeaders({}, apiKey, userId),
      })
      if (!resp.ok) throw new Error(await readError(resp))
      if (editingId === id) {
        setEditingId(null)
        setDraft('')
      }
    })
  }

  const onSaveEdit = (id: string) => {
    const content = draft.trim()
    if (!content) {
      setError('内容不能为空')
      return
    }
    void runAction(id, async () => {
      const resp = await fetch(`/api/v1/memory/facts/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        headers: apiHeaders({ 'Content-Type': 'application/json' }, apiKey, userId),
        body: JSON.stringify({ content }),
      })
      if (!resp.ok) throw new Error(await readError(resp))
      setEditingId(null)
      setDraft('')
    })
  }

  return (
    <div className="memory-panel">
      <div className="panel-title">
        我的记忆
        <span className="tag">{facts.length ? `${facts.length} 条` : ''}</span>
        <button className="btn ghost sm memory-refresh" type="button" onClick={() => void load()} disabled={loading}>
          刷新
        </button>
      </div>

      <div className="memory-filters">
        {(
          [
            ['all', '全部'],
            ['candidate', '待确认'],
            ['active', '已生效'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={`memory-filter${filter === key ? ' active' : ''}`}
            onClick={() => setFilter(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? <div className="memory-error">{error}</div> : null}

      <div className="memory-list">
        {loading && !facts.length ? (
          <div className="memory-empty">加载中…</div>
        ) : !visible.length ? (
          <div className="memory-empty">
            {error
              ? '加载失败，请检查鉴权与用户 ID'
              : filter === 'candidate'
                ? '暂无待确认记忆'
                : '暂无长期记忆（需开启服务端抽取）'}
          </div>
        ) : (
          visible.map((f) => {
            const busy = busyId === f.id
            const editing = editingId === f.id
            return (
              <div key={f.id} className={`memory-item status-${f.status}`}>
                <div className="memory-item-head">
                  <span className={`memory-badge ${f.status}`}>
                    {f.status === 'candidate' ? '待确认' : '已生效'}
                  </span>
                  <span className="memory-kind">{KIND_LABEL[f.kind] || f.kind}</span>
                  <span className="memory-key" title={f.key}>
                    {f.key}
                  </span>
                </div>

                {editing ? (
                  <textarea
                    className="memory-edit"
                    value={draft}
                    rows={3}
                    disabled={busy}
                    onChange={(e) => setDraft(e.target.value)}
                  />
                ) : (
                  <div className="memory-content">{f.content}</div>
                )}

                <div className="memory-meta">
                  置信 {(f.confidence ?? 0).toFixed(2)} · {f.source_type}
                </div>

                <div className="memory-actions">
                  {editing ? (
                    <>
                      <button className="btn sm" type="button" disabled={busy} onClick={() => onSaveEdit(f.id)}>
                        保存
                      </button>
                      <button
                        className="btn ghost sm"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setEditingId(null)
                          setDraft('')
                        }}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <>
                      {f.status === 'candidate' ? (
                        <button className="btn sm" type="button" disabled={busy} onClick={() => onConfirm(f.id)}>
                          确认
                        </button>
                      ) : null}
                      <button
                        className="btn ghost sm"
                        type="button"
                        disabled={busy}
                        onClick={() => {
                          setEditingId(f.id)
                          setDraft(f.content)
                        }}
                      >
                        修正
                      </button>
                      <button className="btn ghost sm danger" type="button" disabled={busy} onClick={() => onForget(f.id)}>
                        遗忘
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
