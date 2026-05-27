import { useEffect, useMemo, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
  Handle, Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import useStore from '../../store/useStore'
import api from '../../services/api'
import { Cpu, Server, Network } from 'lucide-react'

// ─── 自定义节点 ──────────────────────────────────────
function TopoNode({ data, selected }) {
  const isSwitch = data.type === 'switch'
  const handleColor = isSwitch ? '#2563eb' : '#10b981'

  return (
    <div className={`topo-node ${isSwitch ? 'node-switch' : 'node-host'} ${selected ? 'selected' : ''}`}>
      {/* 顶部端口 (Target + Source 叠加) */}
      <Handle type="target" position={Position.Top} id="t-left"   style={{ left: '25%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-left"  style={{ left: '25%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="target" position={Position.Top} id="t-center" style={{ left: '50%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-center" style={{ left: '50%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="target" position={Position.Top} id="t-right"  style={{ left: '75%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-right" style={{ left: '75%', width: 6, height: 6, opacity: 0 }} />

      {/* 底部端口 (Source + Target 叠加) */}
      <Handle type="source" position={Position.Bottom} id="b-left"   style={{ left: '25%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-left"  style={{ left: '25%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="b-center" style={{ left: '50%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-center" style={{ left: '50%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="b-right"  style={{ left: '75%', width: 6, height: 6, background: handleColor, border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-right" style={{ left: '75%', width: 6, height: 6, opacity: 0 }} />
      <span className="topo-node-icon">{isSwitch ? <Cpu size={20} color="#2563eb" /> : <Server size={20} color="#10b981" />}</span>
      <span className="topo-node-label">{data.label}</span>
      {data.ip && <span className="topo-node-ip">{data.ip}</span>}
    </div>
  )
}

const nodeTypes = { topoNode: TopoNode }

// ─── 智能树状分层布局算法 ─────────────────────────────────────
function toFlowNodes(nodes, links = []) {
  const switches = nodes.filter(n => n.type === 'switch')
  const hosts    = nodes.filter(n => n.type === 'host')
  const result   = []

  const cx = 450 // 画布中心X

  // 1. 寻找核心交换机（连接数最多，或默认 s1）
  let coreSw = switches.find(s => s.id === 's1') || switches[0]
  const edgeSwitches = switches.filter(s => s !== coreSw)

  // 核心层 Y=120
  if (coreSw) {
    result.push({
      id: coreSw.id,
      type: 'topoNode',
      position: { x: cx - 60, y: 120 }, // 减去节点半宽居中
      data: { ...coreSw },
    })
  }

  // 2. 边缘层 Y=280
  // 计算边缘交换机的 X 坐标分布
  const edgeY = 280
  const edgeWidth = 360 // 边缘交换机跨度
  const startX = cx - edgeWidth / 2

  edgeSwitches.forEach((sw, i) => {
    const swX = edgeSwitches.length === 1 ? cx - 60 : startX + (i / (edgeSwitches.length - 1)) * edgeWidth - 60
    result.push({
      id: sw.id,
      type: 'topoNode',
      position: { x: swX, y: edgeY },
      data: { ...sw },
    })

    // 3. 接入层（主机层） Y=440
    // 查找连接到当前边缘交换机的主机
    const connectedHosts = hosts.filter(h => 
      links.some(l => (l.source === h.id && l.target === sw.id) || (l.target === h.id && l.source === sw.id))
    )

    const hostSpan = 160 // 每个交换机下主机的分布宽度
    const hStartX = swX + 60 - (connectedHosts.length - 1) * (hostSpan / 2)

    connectedHosts.forEach((h, hi) => {
      result.push({
        id: h.id,
        type: 'topoNode',
        position: { x: hStartX + hi * hostSpan - 60, y: 440 },
        data: { ...h },
      })
    })
  })

  // 处理未关联到边缘交换机的孤立主机或直连核心的主机
  const allocatedHostIds = new Set(result.filter(n => n.data.type === 'host').map(n => n.id))
  const remainingHosts = hosts.filter(h => !allocatedHostIds.has(h.id))
  remainingHosts.forEach((h, i) => {
    result.push({
      id: h.id,
      type: 'topoNode',
      position: { x: cx - 200 + i * 120 - 60, y: 440 },
      data: { ...h },
    })
  })

  return result
}


function toFlowEdges(links, flowNodes = [], activePathEdges = []) {
  const nodeMap = Object.fromEntries(flowNodes.map(n => [n.id, n]))

  return links.map(link => {
    const sId = String(link.source)
    const tId = String(link.target)
    const sourceNode = nodeMap[sId]
    const targetNode = nodeMap[tId]

    // 智能端口分配：根据目标节点的相对位置选择左、中、右端口，并判断上下方向
    let sHandle = 'b-center'
    let tHandle = 't-center'

    if (sourceNode && targetNode) {
      const isUpward = sourceNode.position.y > targetNode.position.y
      const dx = targetNode.position.x - sourceNode.position.x
      
      // 判断左右关系
      let hPosSrc = 'center'
      if (dx < -40) hPosSrc = 'left'
      else if (dx > 40) hPosSrc = 'right'

      let hPosDst = 'center'
      if (dx < -40) hPosDst = 'right'
      else if (dx > 40) hPosDst = 'left'

      // 判断上下关系
      if (isUpward) {
        // 目标在上方（例如 主机 -> 交换机）：源用 Top，目标用 Bottom
        // 必须使用正确的叠加 Handle ID 避免类型错误
        sHandle = `st-${hPosSrc}`
        tHandle = `tb-${hPosDst}`
      } else {
        // 目标在下方（例如 交换机 -> 主机）：源用 Bottom，目标用 Top
        sHandle = `b-${hPosSrc}`
        tHandle = `t-${hPosDst}`
      }
    }

    const isActive = activePathEdges.includes(link.id)

    return {
      id: link.id,
      source: sId,
      target: tId,
      sourceHandle: sHandle,
      targetHandle: tHandle,
      type: 'smoothstep',
      animated: isActive,
      className: isActive ? 'edge-active-path' : '',
      style: {
        stroke: '#b45309', // 不管激活与否，统一使用古铜橙色
        strokeWidth: isActive ? 2.5 : 1.5,
        strokeDasharray: '5,5', // 统一使用虚线连线
        filter: isActive ? 'drop-shadow(0 0 5px rgba(180, 83, 9, 0.5))' : 'none', // 激活时辅以橙色微光阴影
      },
      label: link.utilization_pct != null ? `${link.utilization_pct.toFixed(0)}%` : undefined,
    }
  })
}

export default function NetworkTopology() {
  const topology = useStore(s => s.topology)
  const selectedNode = useStore(s => s.selectedNode)
  const setSelectedNode = useStore(s => s.setSelectedNode)
  const activePathEdges = useStore(s => s.activePathEdges)

  // 用 useNodesState / useEdgesState + useEffect 保证正确同步
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  
  // 记录上一次拓扑的 JSON，避免无意义的重绘导致的内存泄漏
  const [lastTopoJson, setLastTopoJson] = useState('')

  useEffect(() => {
    if (!topology) return
    const links = topology.links || []
    const topoNodes = topology.nodes || []
    
    // 简易深度比对（忽略时间戳等无关字段）
    const currentJson = JSON.stringify({ nodes: topoNodes, links })
    if (currentJson === lastTopoJson) return
    setLastTopoJson(currentJson)
    
    setNodes(currentNodes => {
      const posMap = new Map(currentNodes.map(n => [n.id, n.position]))
      const calculatedNodes = toFlowNodes(topology.nodes || [], links)
      
      const mergedNodes = calculatedNodes.map(n => {
        if (posMap.has(n.id)) {
          return { ...n, position: posMap.get(n.id) }
        }
        return n
      })
      
      setEdges(toFlowEdges(links, mergedNodes, activePathEdges))
      return mergedNodes
    })
  }, [topology, setNodes, setEdges, activePathEdges])

  // 获取选中交换机的流表
  const [nodeFlows, setNodeFlows] = useState(null)
  const [loadingFlows, setLoadingFlows] = useState(false)

  useEffect(() => {
    if (selectedNode && selectedNode.type === 'switch' && selectedNode.dpid) {
      setLoadingFlows(true)
      setNodeFlows(null)
      // 将 hex dpid 转为整数
      const dpidInt = parseInt(selectedNode.dpid, 16) || parseInt(selectedNode.dpid)
      api.get(`/flows/${dpidInt}`)
        .then(res => {
          setNodeFlows(res.data.flows || [])
        })
        .catch(err => {
          console.error('Failed to fetch flows', err)
          setNodeFlows([])
        })
        .finally(() => {
          setLoadingFlows(false)
        })
    } else {
      setNodeFlows(null)
    }
  }, [selectedNode])

  const isInitialLoading = useStore(s => s.isInitialLoading)
  const isEmpty = !topology?.nodes?.length

  if (isInitialLoading) {
    return (
      <div className="topology-canvas">
        <div className="empty-topology">
          <div className="empty-topology-text">正在加载网络拓扑...</div>
        </div>
      </div>
    )
  }

  return (
    <div className="topology-canvas">
      {isEmpty ? (
        <div className="empty-topology">
          <div className="empty-topology-icon"><Network size={48} /></div>
          <div className="empty-topology-text">暂无拓扑数据</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            请确认 VM Agent 正在运行
          </div>
        </div>
      ) : (
        <>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => setSelectedNode(node.data)}
            onPaneClick={() => setSelectedNode(null)}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            minZoom={0.2}
            maxZoom={2.5}
            attributionPosition="bottom-right"
          >
            <Background color="#e2e8f0" gap={60} size={1} variant="lines" />
            <Controls showInteractive={false} />
            <MiniMap
              nodeColor={n => n.data?.type === 'switch' ? '#6366f1' : '#16a34a'}
              maskColor="rgba(248,250,252,0.8)"
              style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}
            />
          </ReactFlow>

          {/* 预期路径展示标签 */}
          {activePathEdges && activePathEdges.length > 0 && (
            <div className="path-preview-legend">
              <span className="pp-indicator"></span>
              控制器规划预期路径 (Expected Path)
            </div>
          )}

          {/* 节点详情悬浮窗 */}
          {selectedNode && (
            <div className="node-detail-overlay">
              <div className="node-detail-header">
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {selectedNode.type === 'switch' ? <Cpu size={14} color="#6366f1" /> : <Server size={14} color="#10b981" />}
                  {selectedNode.type === 'switch' ? '交换机详情' : '主机详情'}
                </span>
                <button className="btn-close" onClick={() => setSelectedNode(null)}>✕</button>
              </div>
              <div className="node-detail-body">
                <div className="detail-row">
                  <span className="detail-label">名称</span>
                  <span className="detail-value">{selectedNode.label}</span>
                </div>
                {selectedNode.dpid && (
                  <div className="detail-row">
                    <span className="detail-label">DPID</span>
                    <span className="detail-value">{selectedNode.dpid}</span>
                  </div>
                )}
                {selectedNode.ip && (
                  <div className="detail-row">
                    <span className="detail-label">IP 地址</span>
                    <span className="detail-value">{selectedNode.ip}</span>
                  </div>
                )}
                {selectedNode.mac && (
                  <div className="detail-row">
                    <span className="detail-label">MAC 地址</span>
                    <span className="detail-value">{selectedNode.mac}</span>
                  </div>
                )}
                {selectedNode.port_count != null && (
                  <div className="detail-row">
                    <span className="detail-label">活跃端口数</span>
                    <span className="detail-value">{selectedNode.port_count}</span>
                  </div>
                )}
                {selectedNode.type === 'switch' && (
                  <div className="mt-3">
                    {loadingFlows ? (
                      <div className="text-muted text-center" style={{ fontSize: '11px' }}>加载流表中...</div>
                    ) : nodeFlows && nodeFlows.length > 0 ? (
                      <div style={{ fontSize: 11 }}>
                        <div style={{ color: 'var(--color-text-muted)', marginBottom: 4, fontWeight: 600 }}>流表摘要 ({nodeFlows.length} 条)</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          {nodeFlows.slice(0, 5).map((f, i) => (
                            <div key={i} style={{ display: 'flex', gap: 6, fontSize: 10, fontFamily: 'monospace', background: 'var(--color-bg-sidebar)', padding: '2px 6px', borderRadius: 4 }}>
                              <span style={{ color: '#6366f1', minWidth: 30 }}>p={f.priority}</span>
                              <span style={{ color: 'var(--color-text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {Object.keys(f.match || {}).length === 0 ? 'ANY' : Object.entries(f.match).slice(0, 2).map(([k, v]) => {
                                  if ((k === 'dl_type' || k === 'eth_type')) {
                                    if (v == 35020) return 'LLDP'
                                    if (v == 2054) return 'ARP'
                                    if (v == 2048) return 'IPv4'
                                  }
                                  if ((k === 'dl_dst' || k === 'eth_dst') && v === '01:80:c2:00:00:0e') return 'LLDP组播'
                                  return `${k.replace(/^(eth_|dl_|nw_|ipv4_|tcp_|udp_)/, '')}=${v}`
                                }).join(', ')}
                              </span>
                              <span style={{ color: (f.actions?.length === 0 || (!f.actions && !f.instructions)) ? '#ef4444' : '#16a34a' }}>
                                {f.actions?.length === 0 ? 'DROP' : 'FWD'}
                              </span>
                            </div>
                          ))}
                          {nodeFlows.length > 5 && (
                            <div style={{ fontSize: 9, color: 'var(--color-text-muted)', textAlign: 'center' }}>...还有 {nodeFlows.length - 5} 条 (左侧流表面板查看全部)</div>
                          )}
                        </div>
                      </div>
                    ) : nodeFlows !== null ? (
                      <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>暂无自定义流表</div>
                    ) : null}
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
