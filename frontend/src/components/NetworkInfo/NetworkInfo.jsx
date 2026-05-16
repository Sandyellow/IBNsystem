import useStore from '../../store/useStore'

export default function NetworkInfo() {
  const status = useStore(s => s.networkStatus)
  const topology = useStore(s => s.topology)

  const downLinks = topology.links?.filter(l => l.state === 'down').length || 0
  const avgLatency = topology.links
    ?.filter(l => l.latency_ms != null)
    .reduce((acc, l, _, arr) => acc + l.latency_ms / arr.length, 0) || 0

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
          <div className="stat-card-value">{status.link_count || topology.links?.length || 0}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">断链</div>
          <div className="stat-card-value" style={{ color: downLinks > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>
            {downLinks}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-card-label">平均延迟</div>
          <div className="stat-card-value">
            {avgLatency > 0 ? avgLatency.toFixed(1) : '—'}
            <span className="stat-card-unit"> ms</span>
          </div>
        </div>
      </div>
    </div>
  )
}
