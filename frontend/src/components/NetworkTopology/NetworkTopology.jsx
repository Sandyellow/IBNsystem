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
import * as d3 from 'd3-force'

// ─── 自定义节点 ──────────────────────────────────────
function TopoNode({ data, selected }) {
  const isSwitch = data.type === 'switch'
  const handleColor = isSwitch ? '#60a5fa' : '#34d399'

  return (
    <div className={`topo-node ${isSwitch ? 'node-switch' : 'node-host'} ${selected ? 'selected' : ''}`}>
      {/* 隐藏的中心端口用于无向图的自适应连线 */}
      <Handle type="target" position={Position.Top} id="center-target" style={{ top: '50%', left: '50%', transform: 'translate(-50%, -50%)', opacity: 0, zIndex: -1 }} />
      <Handle type="source" position={Position.Bottom} id="center-source" style={{ top: '50%', left: '50%', transform: 'translate(-50%, -50%)', opacity: 0, zIndex: -1 }} />

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
      <span className="topo-node-icon">{isSwitch ? <Cpu size={20} color="#60a5fa" /> : <Server size={20} color="#34d399" />}</span>
      <span className="topo-node-label">{data.label}</span>
      {data.ip && <span className="topo-node-ip">{data.ip}</span>}
    </div>
  )
}

const nodeTypes = { topoNode: TopoNode }

// ─── 智能自动布局算法 (d3-force) ─────────────────────────────────────
function toFlowNodes(nodes, links = []) {
  if (!nodes || nodes.length === 0) return []

  const simulationNodes = nodes.map(n => ({ ...n, id: String(n.id) }))
  const simulationLinks = links.map(l => ({
    source: String(l.source),
    target: String(l.target),
    id: l.id
  }))

  const simulation = d3.forceSimulation(simulationNodes)
    .force('link', d3.forceLink(simulationLinks).id(d => d.id).distance(120))
    .force('charge', d3.forceManyBody().strength(-800))
    .force('center', d3.forceCenter(400, 300))
    .force('collide', d3.forceCollide().radius(60))

  for (let i = 0; i < 300; i++) {
    simulation.tick()
  }

  return simulationNodes.map(n => ({
    id: n.id,
    type: 'topoNode',
    position: { x: n.x - 60, y: n.y - 30 },
    data: { ...n },
  }))
}


function toFlowEdges(links, flowNodes = [], activePathEdges = []) {
  const nodeMap = Object.fromEntries(flowNodes.map(n => [n.id, n]))

  return links.map(link => {
    const sId = String(link.source.id || link.source)
    const tId = String(link.target.id || link.target)
    const sourceNode = nodeMap[sId]
    const targetNode = nodeMap[tId]

    const isActive = activePathEdges.includes(link.id)

    return {
      id: link.id,
      source: sId,
      target: tId,
      sourceHandle: 'center-source',
      targetHandle: 'center-target',
      type: 'straight',
      animated: isActive,
      className: isActive ? 'edge-active-path' : '',
      style: {
        stroke: '#d97706', // 更柔和的古铜橙色
        strokeWidth: isActive ? 2.5 : 1.5,
        strokeDasharray: '5,5', // 统一使用虚线连线
        filter: isActive ? 'drop-shadow(0 0 5px rgba(217, 119, 6, 0.4))' : 'none', // 激活时辅以橙色微光阴影
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
              nodeColor={n => n.data?.type === 'switch' ? '#818cf8' : '#4ade80'}
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
                  {selectedNode.type === 'switch' ? <Cpu size={14} color="#818cf8" /> : <Server size={14} color="#34d399" />}
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
                              <span style={{ color: '#818cf8', minWidth: 30 }}>p={f.priority}</span>
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
