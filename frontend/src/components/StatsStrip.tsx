import { fmtMs, fmtTs } from '../api/client'
import type { StatsInfo, TraceSummary } from '../types'

type Props = {
  stats: StatsInfo | null
  summary: TraceSummary
  updatedAt: number
}

export function StatsStrip({ stats, summary, updatedAt }: Props) {
  const hitRate =
    summary.cache_hit_rate != null ? `${Math.round(summary.cache_hit_rate * 100)}%` : '-'
  const blocked = summary.blocked ?? stats?.ratelimit_blocked ?? 0

  return (
    <div className="stats-strip">
      <div className="stat-card">
        <div className="k">知识库块</div>
        <div className="v acc">{stats?.total_chunks ?? '-'}</div>
      </div>
      <div className="stat-card">
        <div className="k">BM25</div>
        <div className={`v ${stats?.bm25_ready ? 'ok' : 'warn'}`}>
          {stats?.bm25_ready ? '就绪' : '未就绪'}
        </div>
      </div>
      <div className="stat-card">
        <div className="k">缓存命中</div>
        <div className={`v ${(summary.cache_hit_rate ?? 0) > 0.3 ? 'ok' : ''}`}>{hitRate}</div>
      </div>
      <div className="stat-card">
        <div className="k">P95延迟</div>
        <div className={`v ${(summary.p95_ms ?? 0) > 3000 ? 'warn' : 'ok'}`}>
          {fmtMs(summary.p95_ms)}
        </div>
      </div>
      <div className="stat-card">
        <div className="k">请求数</div>
        <div className="v">{summary.total ?? 0}</div>
      </div>
      <div className="stat-card">
        <div className="k">限流拦截</div>
        <div className={`v ${blocked > 0 ? 'err' : 'ok'}`}>{blocked}</div>
      </div>
      <div className="stat-card">
        <div className="k">Crew</div>
        <div className={`v ${stats?.use_crew ? 'ok' : ''}`}>
          {stats?.use_crew && stats?.crew_available ? '开' : '关'}
        </div>
      </div>
      <div className="stat-card">
        <div className="k">刷新</div>
        <div className="v" style={{ fontSize: 11 }}>
          {fmtTs(updatedAt).slice(0, 8)}
        </div>
      </div>
    </div>
  )
}
