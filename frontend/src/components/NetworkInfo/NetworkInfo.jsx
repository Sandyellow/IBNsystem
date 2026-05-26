import { useState } from 'react'
import useStore from '../../store/useStore'
import FlowTable from '../FlowTable/FlowTable'
import PortStats from '../PortStats/PortStats'
import PolicyPanel from '../PolicyPanel/PolicyPanel'
import { Network, ArrowRightLeft, Activity, ShieldCheck, Server, ShieldAlert, Cpu, AlertTriangle, AlertCircle, Info, CheckCircle2 } from 'lucide-react'

const TABS = [
  { id: 'topo', label: '拓扑信息', icon: Network },
  { id: 'flows', label: '流表', icon: ArrowRightLeft },
  { id: 'ports', label: '端口统计', icon: Activity },
  { id: 'policies', label: '活跃策略', icon: ShieldCheck },
  { id: 'alerts', label: '系统告警', icon: AlertTriangle },
]

function TopoInfo() {
  const topology = useStore(s => s.topology)
  const networkStatus = useStore(s => s.networkStatus)

  const nodes = topology?.nodes || []
  const links = topology?.links || []
  const switches = nodes.filter(n => n.type === 'switch')
  const hosts = nodes.filter(n => n.type === 'host')
  const swLinks = links.filter(l => !l.source.startsWith('h') && !l.target.startsWith('h'))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* 状态概览 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        {[
          { label: '交换机', value: switches.length, color: '#63b3ed' },
          { label: '主机', value: hosts.length, color: '#68d391' },
          { label: '链路', value: swLinks.length, color: '#f6e05e' },
          { label: '活跃告警', value: networkStatus?.active_alerts || 0, color: '#fc814a' },
        ].map(item => (
          <div key={item.label} style={{
            background: '#ffffff',
            border: '1px solid var(--color-border-strong)',
            borderRadius: 8,
            padding: '10px 12px',
            boxShadow: 'var(--shadow-sm)',
          }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)', marginBottom: 4 }}>{item.label}</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: item.color }}>{item.value}</div>
          </div>
        ))}
      </div>

      {/* 交换机列表 */}
      {switches.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 6, fontWeight: 700 }}>交换机</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {switches.map(sw => (
              <div key={sw.id} style={{
                background: '#ffffff',
                border: '1px solid var(--color-border-strong)',
                borderRadius: 8,
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 14,
                boxShadow: 'var(--shadow-sm)',
              }}>
                <Cpu size={18} color="#1d4ed8" style={{ marginTop: 2, flexShrink: 0 }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 800, color: 'var(--color-text-primary)' }}>{sw.id}</span>
                    {sw.port_count != null && (
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-primary)' }}>
                        {sw.port_count} 端口
                      </span>
                    )}
                  </div>
                  {sw.dpid && (
                    <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      dpid={sw.dpid}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 主机列表 */}
      {hosts.length > 0 && (
        <div>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', marginBottom: 6, fontWeight: 700 }}>主机</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {hosts.map(h => (
              <div key={h.id} style={{
                background: '#ffffff',
                border: '1px solid var(--color-border-strong)',
                borderRadius: 8,
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 12,
                fontSize: 14,
                boxShadow: 'var(--shadow-sm)',
              }}>
                <Server size={18} color="#15803d" style={{ marginTop: 2, flexShrink: 0 }} />
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1, minWidth: 0 }}>
                  <span style={{ fontWeight: 800, color: 'var(--color-text-primary)' }}>{h.id}</span>
                  {h.ip && <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-secondary)', fontFamily: 'monospace' }}>IP: {h.ip}</span>}
                  {h.mac && <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-secondary)', fontFamily: 'monospace' }}>MAC: {h.mac}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {nodes.length === 0 && (
        <div style={{
          textAlign: 'center', color: 'var(--color-text-muted)', fontSize: 12,
          padding: '20px 12px', background: 'var(--color-surface-2)',
          borderRadius: 8, border: '1px dashed var(--color-border)',
        }}>
          <Network size={24} style={{ opacity: 0.5, marginBottom: 6 }} />
          <div>等待 Ryu 连接...</div>
          <div style={{ fontSize: 10, marginTop: 4, opacity: 0.6 }}>确保 VM 上的 Ryu 和 Mininet 正在运行</div>
        </div>
      )}
    </div>
  )
}

function timeAgo(ts) {
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s 前`
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`
  return `${Math.floor(diff / 3600)}h 前`
}

function AlertsTab() {
  const alerts = useStore(s => s.alerts)
  const active = alerts.filter(a => !a.resolved)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-text-primary)' }}>实时告警</span>
        {active.length > 0 && (
          <span style={{
            background: 'var(--color-primary)',
            color: '#fff',
            fontSize: 11,
            fontWeight: 700,
            padding: '1px 7px',
            borderRadius: 10,
          }}>
            {active.length}
          </span>
        )}
      </div>
      <div className="alert-list" style={{ overflowY: 'auto', flex: 1 }}>
        {active.length === 0 ? (
          <div className="alert-empty">
            <CheckCircle2 size={24} color="#10b981" style={{ marginBottom: 6 }} />
            <div>网络运行正常</div>
          </div>
        ) : (
          active.slice(0, 20).map(alert => {
            const Icon = alert.severity === 'critical' ? ShieldAlert : (alert.severity === 'warning' ? AlertTriangle : Info)
            return (
              <div key={alert.id} className={`alert-item ${alert.severity}`}>
                <span className="alert-icon" style={{ marginTop: 2 }}>
                  <Icon size={14} />
                </span>
                <div className="alert-content">
                  <div className="alert-message">{alert.message}</div>
                  <div className="alert-time">{timeAgo(alert.timestamp)}</div>
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}

export default function NetworkInfo() {
  const [activeTab, setActiveTab] = useState('topo')

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 0, overflow: 'hidden' }}>
      {/* Tab 导航 */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface-2)',
        padding: '0 4px',
      }}>
        {TABS.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              style={{
                flex: 1,
                background: 'none',
                border: 'none',
                borderBottom: activeTab === tab.id ? '2px solid var(--color-primary)' : '2px solid transparent',
                color: activeTab === tab.id ? 'var(--color-primary)' : 'var(--color-text-muted)',
                padding: '8px 2px',
                fontSize: 11,
                fontWeight: activeTab === tab.id ? 700 : 400,
                cursor: 'pointer',
                transition: 'all 0.15s',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <Icon size={16} />
              <span style={{ fontSize: 9 }}>{tab.label}</span>
            </button>
          )
        })}
      </div>

      {/* Tab 内容 */}
      <div style={{ padding: 12, overflowY: 'auto', flex: 1 }}>
        {activeTab === 'topo' && <TopoInfo />}
        {activeTab === 'flows' && <FlowTable />}
        {activeTab === 'ports' && <PortStats />}
        {activeTab === 'policies' && <PolicyPanel />}
        {activeTab === 'alerts' && <AlertsTab />}
      </div>
    </div>
  )
}
