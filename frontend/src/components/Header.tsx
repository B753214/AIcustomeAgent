import type { HealthInfo } from '../types'

type Props = {
  online: boolean
  health: HealthInfo | null
  onRefresh: () => void
}

const oldDashboardHref = import.meta.env.DEV
  ? 'http://127.0.0.1:8000/dashboard'
  : '/dashboard'

export function Header({ online, health, onRefresh }: Props) {
  return (
    <header>
      <div className="left">
        <h1>
          智能客服<span className="dot">控制台</span>
        </h1>
        <span>
          <span className={`status-dot ${online ? 'ok' : 'err'}`} />
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>{online ? '在线' : '离线'}</span>
        </span>
      </div>
      <div className="right">
        <span className="meta">LLM: {health?.llm_model || '-'}</span>
        <a className="btn ghost sm" href={oldDashboardHref} style={{ textDecoration: 'none' }}>
          旧版控制台
        </a>
        <button className="btn ghost sm" type="button" onClick={onRefresh}>
          刷新状态
        </button>
      </div>
    </header>
  )
}
