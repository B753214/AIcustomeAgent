import { fmtMs, fmtTs } from '../api/client'
import type { TraceEntry } from '../types'

type Props = {
  entries: TraceEntry[]
}

export function TracesPanel({ entries }: Props) {
  return (
    <div className="traces-panel">
      <div className="traces-head">
        实时请求监控
        <span>3 秒自动刷新 · /api/v1/traces</span>
      </div>
      <div className="traces-table-wrap">
        <table className="traces-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>问题</th>
              <th>会话</th>
              <th>意图</th>
              <th>引擎</th>
              <th>缓存</th>
              <th>耗时</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {!entries.length ? (
              <tr>
                <td colSpan={8} style={{ color: 'var(--muted)', textAlign: 'center', padding: 16 }}>
                  暂无请求——发送一条 chat 后这里会出现记录
                </td>
              </tr>
            ) : (
              entries.map((e, idx) => {
                const cache = e.cache_checked ? (
                  e.cache_hit ? (
                    <span style={{ color: 'var(--ok)' }}>命中</span>
                  ) : (
                    <span style={{ color: 'var(--muted)' }}>未中</span>
                  )
                ) : (
                  '-'
                )
                const status =
                  e.status === 429 ? (
                    <span style={{ color: 'var(--err)' }}>429</span>
                  ) : (
                    <span style={{ color: 'var(--ok)' }}>200</span>
                  )
                return (
                  <tr key={`${e.ts}-${idx}`}>
                    <td className="mono">{fmtTs(e.ts)}</td>
                    <td
                      style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}
                      title={e.message || ''}
                    >
                      {e.message || '-'}
                    </td>
                    <td className="mono">{(e.session_id || '-').slice(0, 12)}</td>
                    <td>
                      <span className={`chip ${e.intent || ''}`}>{e.intent || '-'}</span>
                    </td>
                    <td>{e.engine || '-'}</td>
                    <td>{cache}</td>
                    <td className="mono">{fmtMs(e.total_ms)}</td>
                    <td>{status}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
