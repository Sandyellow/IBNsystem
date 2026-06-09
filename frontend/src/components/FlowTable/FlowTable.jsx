import { useState, useEffect } from 'react'
import api from '../../services/api'
import { Cpu, RefreshCw, Hash, Clock } from 'lucide-react'
import Select from '../common/Select'
import './FlowTable.css'

const ACTION_LABELS = {
  OUTPUT: (v) => `→ 端口 ${v?.port ?? v}`,
  DROP: () => '丢弃',
  METER: (v) => `Meter #${v?.meter_id ?? v}`,
  GOTO_TABLE: (v) => `→ 表 ${v}`,
}

function formatAction(action) {
  if (!action) return '-'
  if (typeof action === 'string') {
    if (action === 'OUTPUT:CONTROLLER') return '→ 控制器 (Controller)'
    if (action.startsWith('OUTPUT:')) return `→ 端口 ${action.split(':')[1]}`
    return action
  }
  const t = (action.type || '').toUpperCase()
  const fmt = ACTION_LABELS[t]
  return fmt ? fmt(action) : `${t}`
}

const ETH_TYPE_MAP = {
  2048: 'IPv4',
  2054: 'ARP',
  34525: 'IPv6',
  35020: 'LLDP',
  34887: 'MPLS'
}

const MAC_MAP = {
  '01:80:c2:00:00:0e': 'LLDP组播',
  'ff:ff:ff:ff:ff:ff': '广播(Broadcast)'
}

function formatMatch(match) {
  if (!match || Object.keys(match).length === 0) return [{ label: '全部', value: '(ANY)' }]
  const parts = []

  // 处理常用协议类型
  const ethType = match.eth_type || match.dl_type
  if (ethType) {
    const typeInt = parseInt(ethType, 10) || ethType
    parts.push({ label: '协议', value: ETH_TYPE_MAP[typeInt] || `0x${typeInt.toString(16)}` })
  }

  const inPort = match.in_port
  if (inPort !== undefined) parts.push({ label: '入端口', value: inPort })

  const dlSrc = match.eth_src || match.dl_src
  if (dlSrc) parts.push({ label: '源MAC', value: MAC_MAP[dlSrc] || dlSrc })

  const dlDst = match.eth_dst || match.dl_dst
  if (dlDst) parts.push({ label: '目的MAC', value: MAC_MAP[dlDst] || dlDst })

  const nwSrc = match.ipv4_src || match.nw_src
  if (nwSrc) parts.push({ label: '源IP', value: nwSrc })

  const nwDst = match.ipv4_dst || match.nw_dst
  if (nwDst) parts.push({ label: '目的IP', value: nwDst })

  const tpSrc = match.tcp_src || match.udp_src || match.tp_src
  if (tpSrc) parts.push({ label: '源端口', value: tpSrc })

  const tpDst = match.tcp_dst || match.udp_dst || match.tp_dst
  if (tpDst) parts.push({ label: '目的端口', value: tpDst })

  const handledKeys = [
    'eth_type', 'dl_type', 'in_port', 'eth_src', 'dl_src', 
    'eth_dst', 'dl_dst', 'ipv4_src', 'nw_src', 'ipv4_dst', 
    'nw_dst', 'tcp_src', 'udp_src', 'tp_src', 'tcp_dst', 'udp_dst', 'tp_dst'
  ]
  const unhandled = Object.entries(match).filter(([k]) => !handledKeys.includes(k))
  if (unhandled.length > 0) {
    unhandled.forEach(([k, v]) => {
      parts.push({ label: k.replace(/^(eth_|dl_|nw_|ipv4_|tcp_|udp_)/, ''), value: String(v) })
    })
  }

  return parts
}

function formatActions(flow) {
  // Try actions field first
  const actions = flow.actions || []
  if (actions.length === 0) return <span className="fc-action-drop">DROP</span>
  // Check instructions
  const instructions = flow.instructions || []
  const allActions = []
  for (const inst of instructions) {
    if (inst.actions) allActions.push(...inst.actions)
    if (inst.type === 'METER') allActions.push(inst)
  }
  const src = allActions.length > 0 ? allActions : actions
  return src.map((a, i) => (
    <span key={i} className="fc-action-tag">{formatAction(a)}</span>
  ))
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

function FlowCard({ flow, isCustom }) {
  const cookie = flow.cookie ? `0x${flow.cookie.toString(16)}` : '0'
  return (
    <div className={`fc-card ${isCustom ? 'custom' : 'default'}`}>
      <div className="fc-header">
        <span className={`fc-priority ${isCustom ? 'high' : 'low'}`}>
          Pri: {flow.priority}
        </span>
        <div className="fc-header-right">
          <span className="fc-meta" title="Cookie">
            <Hash size={10} /> {cookie}
          </span>
          {flow.idle_timeout > 0 && (
            <span className="fc-meta" title="Idle Timeout">
              <Clock size={10} /> {flow.idle_timeout}s
            </span>
          )}
        </div>
      </div>
      <div className="fc-body">
        <div className="fc-row">
          <span className="fc-label">匹配</span>
          <div className="fc-matches">
            {(() => {
              const matches = formatMatch(flow.match || {})
              return matches.map((m, i) => (
                <span key={i} className="fc-match-tag">
                  <span className="fc-match-label">{m.label}:</span>
                  <span className="fc-match-value">{m.value}</span>
                </span>
              ))
            })()}
          </div>
        </div>
        <div className="fc-row">
          <span className="fc-label">动作</span>
          <div className="fc-actions">{formatActions(flow)}</div>
        </div>
      </div>
      <div className="fc-footer">
        <div className="fc-stat">
          <span className="fc-stat-val">{(flow.packet_count || 0).toLocaleString()}</span> pkts
        </div>
        <div className="fc-stat">
          <span className="fc-stat-val">{formatBytes(flow.byte_count || 0)}</span>
        </div>
      </div>
    </div>
  )
}

export default function FlowTable({ autoRefresh = false }) {
  const [flowData, setFlowData] = useState({})
  const [loading, setLoading] = useState(false)
  const [selectedSwitch, setSelectedSwitch] = useState('all')
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchFlows = async () => {
    setLoading(true)
    try {
      const resp = await api.get('/flows')
      setFlowData(resp.data.flows || {})
      setLastUpdated(new Date())
    } catch (e) {
      console.error('获取流表失败:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchFlows()
  }, [])

  useEffect(() => {
    if (!autoRefresh) return
    const t = setInterval(fetchFlows, 5000)
    return () => clearInterval(t)
  }, [autoRefresh])

  const switches = Object.keys(flowData)
  const displaySwitches = selectedSwitch === 'all' ? switches : [selectedSwitch]

  // Determine which flows are IBN-installed (non-zero cookie, priority >= 200)
  const isCustomFlow = (flow) => flow.cookie && flow.cookie !== 0 && flow.priority >= 200

  const totalFlows = switches.reduce((s, k) => s + (flowData[k]?.length || 0), 0)

  return (
    <div className="flow-table-container">
      <div className="flow-table-header">
        <div className="flow-table-title">
          流表规则
          <span className="flow-count-badge">{totalFlows}</span>
        </div>
        <div className="flow-table-controls">
          <Select
            options={[
              { label: '全部交换机', value: 'all' },
              ...switches.map(dpid => ({ label: `dpid=${dpid}`, value: dpid }))
            ]}
            value={selectedSwitch}
            onChange={setSelectedSwitch}
          />
          <button className="flow-refresh-btn" onClick={fetchFlows} disabled={loading} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            {loading ? <RefreshCw size={12} className="spin-icon" /> : <RefreshCw size={12} />} 刷新
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div className="flow-legend">
          <span className="legend-item"><span className="flow-row-custom-dot" />自定义</span>
          <span className="legend-item"><span className="flow-row-default-dot" />自动规则</span>
        </div>
        {lastUpdated && (
          <div className="flow-last-updated">
            更新: {lastUpdated.toLocaleTimeString()}
          </div>
        )}
      </div>

      {displaySwitches.length === 0 ? (
        <div className="flow-empty">暂无流表数据，请确认 Ryu 已连接</div>
      ) : (
        displaySwitches.map(dpid => {
          const flows = flowData[dpid] || []
          return (
            <div key={dpid} className="flow-switch-section">
              <div className="flow-switch-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <Cpu size={14} color="#6366f1" />
                交换机 dpid={dpid}
                <span className="flow-count-sm">{flows.length} 条规则</span>
              </div>
              {flows.length === 0 ? (
                <div className="flow-empty-switch">该交换机暂无流表</div>
              ) : (
                <div className="flow-card-list">
                  {flows
                    .slice()
                    .sort((a, b) => b.priority - a.priority)
                    .map((flow, i) => (
                      <FlowCard key={i} flow={flow} isCustom={isCustomFlow(flow)} />
                    ))}
                </div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}
