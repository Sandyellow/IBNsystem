import { useState, useEffect } from 'react'
import api from '../../services/api'
import { Cpu, RefreshCw, AlertTriangle } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import './PortStats.css'

function formatBytes(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function PortBar({ value, max }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  const color = pct > 80 ? '#fc814a' : pct > 50 ? '#f6e05e' : '#48bb78'
  return (
    <div className="port-bar-bg">
      <div className="port-bar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

function PortRow({ port, maxBytes }) {
  const portNo = port.port_no
  const isLocal = portNo === 4294967294  // LOCAL port
  if (isLocal) return null

  const rx = port.rx_bytes || 0
  const tx = port.tx_bytes || 0
  const rxPkt = port.rx_packets || 0
  const txPkt = port.tx_packets || 0
  const rxErr = port.rx_errors || 0
  const hasErrors = rxErr > 0

  return (
    <div className="port-row">
      <div className="port-no">
        {portNo === 4294967294 ? 'LOCAL' : `端口 ${portNo}`}
      </div>
      <div className="port-stats-grid">
        <div className="port-stat-item">
          <span className="port-stat-label rx">↓ RX</span>
          <span className="port-stat-value">{formatBytes(rx)}</span>
          <span className="port-stat-pkts">{rxPkt.toLocaleString()} pkts</span>
          <PortBar value={rx} max={maxBytes} />
        </div>
        <div className="port-stat-item">
          <span className="port-stat-label tx">↑ TX</span>
          <span className="port-stat-value">{formatBytes(tx)}</span>
          <span className="port-stat-pkts">{txPkt.toLocaleString()} pkts</span>
          <PortBar value={tx} max={maxBytes} />
        </div>
        {hasErrors && (
          <div className="port-errors" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <AlertTriangle size={12} /> {rxErr} 错误
          </div>
        )}
      </div>
    </div>
  )
}

export default function PortStats() {
  const [statsData, setStatsData] = useState({})
  const [historyData, setHistoryData] = useState({})
  const [loading, setLoading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchStats = async () => {
    setLoading(true)
    try {
      const resp = await api.get('/port-stats')
      setStatsData(resp.data.port_stats || {})
      setHistoryData(resp.data.history || {})
      setLastUpdated(new Date())
    } catch (e) {
      console.error('获取端口统计失败:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchStats()
    // 根据用户要求，不提供自动滚动的实时图表，仅展示点击/刷新时的静态快照
  }, [])

  const switches = Object.entries(statsData)

  // 计算所有端口最大字节数（用于 bar 归一化）
  const getMaxBytes = (ports) => {
    return Math.max(1, ...ports.map(p => Math.max(p.rx_bytes || 0, p.tx_bytes || 0)))
  }

  return (
    <div className="port-stats-container">
      <div className="port-stats-header">
        <span className="port-stats-title">端口流量统计</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {lastUpdated && (
            <span className="port-stats-time">{lastUpdated.toLocaleTimeString()}</span>
          )}
          <button className="port-refresh-btn" onClick={fetchStats} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {loading ? <RefreshCw size={12} className="spin-icon" /> : <RefreshCw size={12} />} 刷新
          </button>
        </div>
      </div>

      {switches.length === 0 ? (
        <div className="port-stats-empty">暂无端口统计，请确认 Ryu 已连接</div>
      ) : (
        switches.map(([dpid, ports]) => {
          const validPorts = (ports || []).filter(p => p.port_no !== 4294967294)
          const maxBytes = getMaxBytes(validPorts)
          const history = historyData[dpid] || []
          
          return (
            <div key={dpid} className="port-switch-section">
              <div className="port-switch-label" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <Cpu size={14} color="#6366f1" /> 交换机 dpid={dpid}
              </div>
              
              {history.length > 1 && (
                <div style={{ height: 180, width: '100%', marginBottom: 16 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={history} margin={{ top: 5, right: 20, left: -10, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
                      <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={10} tickMargin={8} minTickGap={20} />
                      <YAxis stroke="var(--color-text-muted)" fontSize={10} unit=" KB/s" tickCount={5} />
                      <RechartsTooltip 
                        contentStyle={{ fontSize: 11, borderRadius: 6, border: '1px solid var(--color-border)', boxShadow: 'var(--shadow-sm)', backgroundColor: 'rgba(255, 255, 255, 0.95)' }}
                        labelStyle={{ color: 'var(--color-text-muted)', marginBottom: 4 }}
                      />
                      {validPorts.map((p, idx) => {
                         const colors = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']
                         const color = colors[idx % colors.length]
                         return [
                           <Line key={`rx_${p.port_no}`} type="monotone" dataKey={`${p.port_no}_rx`} name={`Port ${p.port_no} RX`} stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />,
                           <Line key={`tx_${p.port_no}`} type="monotone" dataKey={`${p.port_no}_tx`} name={`Port ${p.port_no} TX`} stroke={color} strokeDasharray="4 4" strokeWidth={2} dot={false} isAnimationActive={false} />
                         ]
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {validPorts.length === 0 ? (
                <div className="port-stats-empty-sw">无端口数据</div>
              ) : (
                validPorts.map(port => (
                  <PortRow key={port.port_no} port={port} maxBytes={maxBytes} />
                ))
              )}
            </div>
          )
        })
      )}
    </div>
  )
}
