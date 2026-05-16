import useStore from '../../store/useStore'

function timeAgo(ts) {
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s 前`
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`
  return `${Math.floor(diff / 3600)}h 前`
}

function AlertIcon({ severity }) {
  if (severity === 'critical') return '🔴'
  if (severity === 'warning') return '🟡'
  return 'ℹ️'
}

export default function AlertPanel() {
  const alerts = useStore(s => s.alerts)
  const active = alerts.filter(a => !a.resolved)

  return (
    <div className="sidebar-section" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      <div className="sidebar-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span>实时告警</span>
        {active.length > 0 && (
          <span style={{
            background: 'var(--color-danger)',
            color: 'white',
            fontSize: 10,
            fontWeight: 700,
            padding: '1px 6px',
            borderRadius: 20,
          }}>
            {active.length}
          </span>
        )}
      </div>
      <div className="alert-list" style={{ overflowY: 'auto', flex: 1 }}>
        {active.length === 0 ? (
          <div className="alert-empty">
            <div style={{ fontSize: 24, marginBottom: 6 }}>✅</div>
            网络运行正常
          </div>
        ) : (
          active.slice(0, 20).map(alert => (
            <div key={alert.id} className={`alert-item ${alert.severity}`}>
              <span className="alert-icon">
                <AlertIcon severity={alert.severity} />
              </span>
              <div className="alert-content">
                <div className="alert-message">{alert.message}</div>
                <div className="alert-time">{timeAgo(alert.timestamp)}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
