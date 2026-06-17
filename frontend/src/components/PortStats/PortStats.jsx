import { useState, useEffect } from 'react'
import api from '../../services/api'
import { Cpu, RefreshCw, AlertTriangle, Filter } from 'lucide-react'
import { LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, CartesianGrid, Legend } from 'recharts'
import Select from '../common/Select'
import './PortStats.css'

const PORT_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899']

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

function PortRow({ port, maxBytes, color }) {
  const portNo = port.port_no
  const isLocal = portNo === 4294967294 || String(portNo).toUpperCase() === 'LOCAL'
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
        {color && <div className="port-color-dot" style={{ backgroundColor: color }} />}
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
  const [selectedSwitch, setSelectedSwitch] = useState('all')
  const [hiddenPorts, setHiddenPorts] = useState({})

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

  const filteredSwitches = selectedSwitch === 'all' 
    ? switches 
    : switches.filter(([dpid]) => dpid === selectedSwitch)

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

      {switches.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <Filter size={14} color="var(--color-text-muted)" />
          <Select 
            options={[
              { label: '显示所有交换机', value: 'all' },
              ...switches.map(([dpid]) => ({ label: `交换机 DPID: ${dpid}`, value: dpid }))
            ]}
            value={selectedSwitch}
            onChange={setSelectedSwitch}
            style={{ flex: 1 }}
          />
        </div>
      )}

      {switches.length === 0 ? (
        <div className="port-stats-empty">暂无端口统计，请确认 Ryu 已连接</div>
      ) : filteredSwitches.length === 0 ? (
        <div className="port-stats-empty">未找到匹配的交换机</div>
      ) : (
        filteredSwitches.map(([dpid, ports]) => {
          const validPorts = (ports || []).filter(p => p.port_no !== 4294967294 && String(p.port_no).toUpperCase() !== 'LOCAL')
          const maxBytes = getMaxBytes(validPorts)
          const history = historyData[dpid] || []
          
          return (
            <div key={dpid} className="port-switch-section">
              <div className="port-switch-label" style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
                <Cpu size={14} color="#6366f1" /> 
                <span style={{ flex: 1 }}>交换机 dpid={dpid}</span>

              </div>
              
              {history.length > 1 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 16 }}>
                  {/* RX Chart */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#48bb78', marginBottom: 4, marginLeft: 4 }}>↓ 入端口速率 (RX)</div>
                    <div style={{ height: 260, width: '100%' }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={history} margin={{ top: 28, right: 5, left: -10, bottom: 5 }} style={{ outline: 'none' }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
                          <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={10} tickMargin={8} minTickGap={20} />
                          <YAxis 
                            stroke="var(--color-text-muted)" fontSize={10} tickCount={5}
                            domain={[0, (dataMax) => Math.max(10, dataMax)]}
                            tickFormatter={(val) => val >= 1000 ? `${(val / 1000).toFixed(1)} M` : Number(val.toFixed(2))}
                          />
                          <RechartsTooltip isAnimationActive={false} animationDuration={0} position={{ y: -5 }} content={<CustomChartTooltip />} cursor={{ stroke: 'var(--color-border-strong)', strokeWidth: 1, strokeDasharray: '3 3' }} />
                          <Legend wrapperStyle={{ paddingTop: 10, fontSize: 11, cursor: 'pointer' }} onClick={(e) => { if (e && e.dataKey) setHiddenPorts(prev => ({ ...prev, [e.dataKey.split('_')[0]]: !prev[e.dataKey.split('_')[0]] })) }} />
                          {validPorts.map((p, idx) => {
                             const color = PORT_COLORS[idx % PORT_COLORS.length]
                             const isHidden = hiddenPorts[p.port_no]
                             return <Line key={`rx_${p.port_no}`} type="monotone" dataKey={`${p.port_no}_rx`} name={`端口 ${p.port_no} RX`} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive={false} hide={isHidden} strokeOpacity={0.8} />
                          })}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* TX Chart */}
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#63b3ed', marginBottom: 4, marginLeft: 4 }}>↑ 出端口速率 (TX)</div>
                    <div style={{ height: 260, width: '100%' }}>
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={history} margin={{ top: 28, right: 5, left: -10, bottom: 5 }} style={{ outline: 'none' }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
                          <XAxis dataKey="time" stroke="var(--color-text-muted)" fontSize={10} tickMargin={8} minTickGap={20} />
                          <YAxis 
                            stroke="var(--color-text-muted)" fontSize={10} tickCount={5}
                            domain={[0, (dataMax) => Math.max(10, dataMax)]}
                            tickFormatter={(val) => val >= 1000 ? `${(val / 1000).toFixed(1)} M` : Number(val.toFixed(2))}
                          />
                          <RechartsTooltip isAnimationActive={false} animationDuration={0} position={{ y: -5 }} content={<CustomChartTooltip />} cursor={{ stroke: 'var(--color-border-strong)', strokeWidth: 1, strokeDasharray: '3 3' }} />
                          <Legend wrapperStyle={{ paddingTop: 10, fontSize: 11, cursor: 'pointer' }} onClick={(e) => { if (e && e.dataKey) setHiddenPorts(prev => ({ ...prev, [e.dataKey.split('_')[0]]: !prev[e.dataKey.split('_')[0]] })) }} />
                          {validPorts.map((p, idx) => {
                             const color = PORT_COLORS[idx % PORT_COLORS.length]
                             const isHidden = hiddenPorts[p.port_no]
                             return <Line key={`tx_${p.port_no}`} type="monotone" dataKey={`${p.port_no}_tx`} name={`端口 ${p.port_no} TX`} stroke={color} strokeDasharray="4 4" strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive={false} hide={isHidden} strokeOpacity={0.8} />
                          })}
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>
              )}

              {validPorts.length === 0 ? (
                <div className="port-stats-empty-sw">无端口数据</div>
              ) : (
                validPorts.map((port, idx) => (
                  <PortRow key={port.port_no} port={port} maxBytes={maxBytes} color={PORT_COLORS[idx % PORT_COLORS.length]} />
                ))
              )}
            </div>
          )
        })
      )}
    </div>
  )
}

const CustomChartTooltip = ({ active, payload, label }) => {
  if (active && payload && payload.length) {
    const ports = {}
    payload.forEach(item => {
      const pNo = item.dataKey.split('_')[0]
      const type = item.dataKey.split('_')[1]
      if (!ports[pNo]) ports[pNo] = { color: item.color }
      ports[pNo][type] = item.value
    })

    return (
      <div style={{ pointerEvents: 'none', display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '6px 12px', fontSize: 11, color: 'var(--color-text-primary)' }}>
        {Object.entries(ports).map(([pNo, data]) => (
          <div key={pNo} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: data.color, flexShrink: 0 }} />
            <span style={{ fontWeight: 600 }}>
              {data.rx !== undefined ? `P${pNo}: ↓ ${data.rx >= 1000 ? (data.rx/1000).toFixed(2)+'M' : Number(data.rx).toFixed(1)+'K'}` : `P${pNo}: ↑ ${data.tx >= 1000 ? (data.tx/1000).toFixed(2)+'M' : Number(data.tx).toFixed(1)+'K'}`}
            </span>
          </div>
        ))}
      </div>
    )
  }
  return null
}
