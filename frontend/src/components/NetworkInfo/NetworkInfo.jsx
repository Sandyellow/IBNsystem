import useStore from '../../store/useStore'

export default function NetworkInfo() {
  const status = useStore(s => s.networkStatus)
  const topology = useStore(s => s.topology)

  const links = topology.links ?? []
  const downLinks = links.filter(l => l.state === 'down').length

  // 平均延迟：只取有值（> 0）的链路
  const latencyLinks = links.filter(l => l.latency_ms != null && l.latency_ms > 0)
  const avgLatency = latencyLinks.length > 0
    ? latencyLinks.reduce((sum, l) => sum + l.latency_ms, 0) / latencyLinks.length
    : null

  // 平均链路利用率：只取有值的链路
  const utilLinks = links.filter(l => l.utilization_pct != null)
  const avgUtil = utilLinks.length > 0
    ? utilLinks.reduce((sum, l) => sum + l.utilization_pct, 0) / utilLinks.length
    : null

  return (
    <div className="sidebar-section">
      <div className="sidebar-title">网络概览</div>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-card-label">节点数</div>
          <div className="stat-card-value">{status.node_count || topology.nodes?.length || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">链路数</div>
          <div className="stat-card-value">{status.link_count || links.length || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">断链</div>
          <div
            className="stat-card-value"
            style={{ color: downLinks > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}
          >
            {downLinks}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">平均延迟</div>
          <div className="stat-card-value">
            {avgLatency != null ? avgLatency.toFixed(1) : '—'}
            <span className="stat-card-unit"> ms</span>
          </div>
        </div>
        <div className="stat-card" style={{ gridColumn: 'span 2' }}>
          <div className="stat-card-label">平均链路负载</div>
          <div className="stat-card-value" style={{
            color: avgUtil != null && avgUtil > 70
              ? 'var(--color-danger)'
              : avgUtil != null && avgUtil > 40
                ? 'var(--color-warning, #f59e0b)'
                : undefined
          }}>
            {avgUtil != null ? avgUtil.toFixed(1) : '—'}
            <span className="stat-card-unit"> %</span>
          </div>
        </div>
      </div>
    </div>
  )
}
