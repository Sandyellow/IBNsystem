import { useState } from 'react'
import useStore from '../../store/useStore'
import FlowTable from '../FlowTable/FlowTable'
import PortStats from '../PortStats/PortStats'
import PolicyPanel from '../PolicyPanel/PolicyPanel'
import { Network, ArrowRightLeft, Activity, ShieldCheck, Server, Cpu } from 'lucide-react'
import api from '../../services/api'

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function formatSpeed(kbps) {
  if (!kbps) return '0 KB/s'
  if (kbps < 1000) return `${Number(kbps).toFixed(1)} KB/s`
  return `${(kbps / 1000).toFixed(2)} MB/s`
}

const TABS = [
  { id: 'topo', label: '拓扑信息', icon: Network },
  { id: 'flows', label: '流表', icon: ArrowRightLeft },
  { id: 'ports', label: '端口统计', icon: Activity },
  { id: 'policies', label: '活跃策略', icon: ShieldCheck },
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
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6 }}>
        {[
          { label: '交换机', value: switches.length, color: '#63b3ed' },
          { label: '主机', value: hosts.length, color: '#68d391' },
          { label: '总链路', value: links.length, color: '#f6e05e' },
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontWeight: 800, color: 'var(--color-text-primary)', fontSize: 15 }}>{sw.id}</span>
                    {sw.port_count != null && (
                      <span style={{ fontSize: 11, fontWeight: 500, color: 'var(--color-text-muted)', background: 'var(--color-bg-sidebar)', padding: '2px 8px', borderRadius: 12 }}>
                        {sw.port_count} 端口
                      </span>
                    )}
                  </div>
                  {sw.dpid && (
                    <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      dpid: <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace', fontWeight: 500 }}>{sw.dpid}</span>
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
        <div style={{ marginBottom: 12 }}>
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
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                  <span style={{ fontWeight: 800, color: 'var(--color-text-primary)', fontSize: 15 }}>{h.id}</span>
                  {h.ip && <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>IP: <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace', fontWeight: 500 }}>{h.ip}</span></span>}
                  {h.mac && <span style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>MAC: <span style={{ fontFamily: 'ui-monospace, SFMono-Regular, Consolas, "Courier New", monospace', fontWeight: 500 }}>{h.mac}</span></span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 链路使用率已移除，移动至点击连线展示 */}


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



export default function NetworkInfo() {
  const [activeTab, setActiveTab] = useState('topo')

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 0, padding: 0, overflow: 'hidden' }}>
      {/* Tab 导航 */}
      <div style={{
        display: 'flex',
        background: 'var(--color-bg-sidebar)',
        padding: '12px 12px',
        borderBottom: '1px solid var(--color-border)',
      }}>
        <div style={{
          display: 'flex',
          flex: 1,
          background: 'var(--color-surface-2)',
          borderRadius: '10px',
          padding: '4px',
          gap: '2px'
        }}>
          {TABS.map(tab => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  flex: 1,
                  background: isActive ? '#ffffff' : 'transparent',
                  border: 'none',
                  borderRadius: '6px',
                  color: isActive ? 'var(--color-text-primary)' : 'var(--color-text-secondary)',
                  padding: '6px 0',
                  fontWeight: isActive ? 600 : 500,
                  cursor: 'pointer',
                  transition: 'var(--transition)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 4,
                  boxShadow: isActive ? '0 1px 2px rgba(0,0,0,0.04)' : 'none',
                }}
              >
                <Icon size={16} />
                <span style={{ fontSize: 10, whiteSpace: 'nowrap', transform: 'scale(0.95)' }}>{tab.label}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Tab 内容 */}
      <div style={{ padding: 12, overflowY: 'auto', flex: 1 }}>
        {activeTab === 'topo' && <TopoInfo />}
        {activeTab === 'flows' && <FlowTable />}
        {activeTab === 'ports' && <PortStats />}
        {activeTab === 'policies' && <PolicyPanel />}
      </div>
    </div>
  )
}
