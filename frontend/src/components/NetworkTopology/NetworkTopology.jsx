import { useEffect, useMemo, useState } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
  Handle, Position, BaseEdge, EdgeLabelRenderer, getStraightPath
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import useStore from '../../store/useStore'
import api from '../../services/api'
import { Cpu, Server, Network, EthernetPort } from 'lucide-react'
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

      <span className="topo-node-icon">{isSwitch ? <Cpu size={26} color="#60a5fa" /> : <Server size={16} color="#34d399" />}</span>
      <span className="topo-node-label">{data.label}</span>
    </div>
  )
}

const nodeTypes = { topoNode: TopoNode }

function PortEdge({ id, sourceX, sourceY, targetX, targetY, style, markerEnd, data }) {
  const [edgePath] = getStraightPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  const formatPort = (p) => {
    if (p == null) return '';
    const num = parseInt(p, 16);
    return isNaN(num) ? String(p).replace(/^0+/, '') : String(num);
  };

  const p1 = formatPort(data.srcPort);
  const p2 = formatPort(data.dstPort);
  
  if (!p1 && !p2) {
    return <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />;
  }

  // 椭圆相交算法计算贴边位置 (精确避开节点框)
  // 增加 a, b 和 padding，确保彻底推到节点的外侧，避免与节点阴影或边框重叠
  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const len = Math.sqrt(dx * dx + dy * dy) || 1;
  const nx = dx / len;
  const ny = dy / len;

  // 使用偏大一点的包围盒，确保完全包住节点及阴影
  const a = 75; 
  const b = 45; 
  const scale = 1 / Math.sqrt((dx * dx) / (a * a) + (dy * dy) / (b * b));
  
  // padding: 中心点从相交处继续向外延伸的安全距离 (24px，抵消掉标签自身的尺寸)
  // 当线太短导致重叠时，最大不超过线长的一半减去15px
  const maxAllowed = (len / 2) - 15;
  const actualDist = Math.min((len * scale) + 24, maxAllowed > 0 ? maxAllowed : 0);

  const srcLabelX = sourceX + nx * actualDist;
  const srcLabelY = sourceY + ny * actualDist;
  
  const dstLabelX = targetX - nx * actualDist;
  const dstLabelY = targetY - ny * actualDist;

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      <EdgeLabelRenderer>
        {p1 && (
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${srcLabelX}px,${srcLabelY}px)`,
              background: 'rgba(255, 255, 255, 0.95)',
              padding: '2px 6px',
              borderRadius: '6px',
              fontSize: '10px',
              fontWeight: 700,
              color: '#475569',
              border: '1px solid #cbd5e1',
              pointerEvents: 'none',
              backdropFilter: 'blur(2px)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              display: 'flex',
              alignItems: 'center',
              gap: '3px'
            }}
            className="nodrag nopan"
          >
            <EthernetPort size={10} style={{ color: '#94a3b8' }} />
            <span>{p1}</span>
          </div>
        )}
        {p2 && (
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${dstLabelX}px,${dstLabelY}px)`,
              background: 'rgba(255, 255, 255, 0.95)',
              padding: '2px 6px',
              borderRadius: '6px',
              fontSize: '10px',
              fontWeight: 700,
              color: '#475569',
              border: '1px solid #cbd5e1',
              pointerEvents: 'none',
              backdropFilter: 'blur(2px)',
              boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
              display: 'flex',
              alignItems: 'center',
              gap: '3px'
            }}
            className="nodrag nopan"
          >
            <EthernetPort size={10} style={{ color: '#94a3b8' }} />
            <span>{p2}</span>
          </div>
        )}
      </EdgeLabelRenderer>
    </>
  );
}

const edgeTypes = { portEdge: PortEdge }

// ─── 数据中心 Spine-Leaf 分层布局算法 ─────────────────────────────────────
function toFlowNodesTree(nodes, links = []) {
  if (!nodes || nodes.length === 0) return []

  const simulationNodes = nodes.map(n => ({ ...n, id: String(n.id) }))
  
  // 1. 构建邻接表
  const adj = {}
  simulationNodes.forEach(n => adj[n.id] = [])
  links.forEach(l => {
    const s = String(l.source.id || l.source)
    const t = String(l.target.id || l.target)
    if(adj[s]) adj[s].push(t)
    if(adj[t]) adj[t].push(s)
  })

  // 2. 从主机开始 BFS，划分层级 (Tier 0: Hosts, Tier 1: ToR Switches, Tier 2: Core)
  const hosts = simulationNodes.filter(n => n.type === 'host' || n.id.startsWith('h')).map(n => n.id).sort()
  const layers = []
  const visited = new Set(hosts)
  
  if (hosts.length > 0) {
    layers.push(hosts)
    let queue = hosts
    while(queue.length > 0) {
      const nextLayer = []
      for(const curr of queue) {
        for(const neighbor of adj[curr]) {
          if(!visited.has(neighbor)) {
            visited.add(neighbor)
            nextLayer.push(neighbor)
          }
        }
      }
      if(nextLayer.length > 0) {
        nextLayer.sort() // 字母排序保证一致性
        layers.push(nextLayer)
      }
      queue = nextLayer
    }
  }

  // 3. 处理游离节点
  const unvisited = simulationNodes.filter(n => !visited.has(n.id)).map(n => n.id).sort()
  if(unvisited.length > 0) {
    layers.push(unvisited)
  }

  // 4. 计算坐标 (自下而上)
  const layerHeight = 220 // 增大层间距，使连线更长
  const nodeSpacing = 200 // 增大同层节点间距，避免拥挤
  const positions = {}
  const totalLayers = layers.length
  
  layers.forEach((layerNodes, layerIndex) => {
    // 层级越高（核心交换机），Y坐标越小（越靠上）
    const y = (totalLayers - 1 - layerIndex) * layerHeight + 50
    // 居中对齐该层的节点
    const totalWidth = (layerNodes.length - 1) * nodeSpacing
    const startX = 400 - totalWidth / 2
    
    layerNodes.forEach((nodeId, i) => {
      positions[nodeId] = { x: startX + i * nodeSpacing, y: y }
    })
  })

  return simulationNodes.map(n => ({
    id: n.id,
    type: 'topoNode',
    position: { x: (positions[n.id]?.x || 400) - 60, y: (positions[n.id]?.y || 300) - 30 },
    data: { ...n },
  }))
}

// ─── D3 物理力导向算法 ─────────────────────────────────────
function toFlowNodesD3(nodes, links = []) {
  if (!nodes || nodes.length === 0) return []

  const simulationNodes = nodes.map((n, i) => {
    const isSwitch = n.type === 'switch' || n.data?.type === 'switch'
    return {
      ...n,
      id: String(n.id),
      // 给主机一个初始远离中心的位置，防止被交换机斥力场困在中心
      x: isSwitch ? 400 + Math.random() * 50 : (i % 2 === 0 ? 0 : 800),
      y: isSwitch ? 300 + Math.random() * 50 : (i % 3 === 0 ? 0 : 600)
    }
  })
  const simulationLinks = links.map(l => ({
    source: String(l.source.id || l.source),
    target: String(l.target.id || l.target),
    id: l.id
  }))

  const simulation = d3.forceSimulation(simulationNodes)
    .force('link', d3.forceLink(simulationLinks).id(d => d.id).distance(l => {
      const isSwitchLink = (l.source.type || l.source.data?.type) === 'switch' && (l.target.type || l.target.data?.type) === 'switch'
      return isSwitchLink ? 220 : 100
    }))
    .force('charge', d3.forceManyBody().strength(n => n.type === 'switch' ? -1500 : -600))
    .force('x', d3.forceX(400).strength(n => n.type === 'switch' ? 0.1 : 0))
    .force('y', d3.forceY(300).strength(n => n.type === 'switch' ? 0.1 : 0))
    .force('r', d3.forceRadial(350, 400, 300).strength(n => n.type === 'switch' ? 0 : 0.15))
    .force('collide', d3.forceCollide().radius(n => n.type === 'switch' ? 100 : 60))

  for (let i = 0; i < 400; i++) {
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
      type: 'portEdge',
      animated: isActive,
      className: isActive ? 'edge-active-path' : '',
      style: {
        stroke: '#d97706', // 更柔和的古铜橙色
        strokeWidth: isActive ? 2.5 : 1.5,
        strokeDasharray: '5,5', // 统一使用虚线连线
        filter: isActive ? 'drop-shadow(0 0 5px rgba(217, 119, 6, 0.4))' : 'none', // 激活时辅以橙色微光阴影
      },
      data: {
        srcPort: link.src_port,
        dstPort: link.dst_port,
        srcLabel: sourceNode?.data?.label || sId,
        dstLabel: targetNode?.data?.label || tId,
        sourceDpid: sourceNode?.data?.dpid || sourceNode?.dpid,
        targetDpid: targetNode?.data?.dpid || targetNode?.dpid,
      }
    }
  })
}

// ─── Edge Detail Overlay ──────────────────────────────────────
function formatSpeed(kbps) {
  if (!kbps) return '0 Kbps'
  if (kbps < 1000) return `${Number(kbps).toFixed(1)} Kbps`
  return `${(kbps / 1000).toFixed(2)} Mbps`
}

function getPercentage(kbps, capacity) {
  if (!kbps || !capacity) return '0.0';
  const percent = (kbps / capacity) * 100;
  return Math.min(percent, 100).toFixed(1);
}

function EdgeDetailOverlay({ edgeData, onClose }) {
  const [statsData, setStatsData] = useState({});
  const [historyData, setHistoryData] = useState({});
  const [descData, setDescData] = useState({});
  
  useEffect(() => {
    let mounted = true;
    const fetchDesc = async () => {
      try {
        const resp = await api.get('/port-desc');
        if (mounted) {
          setDescData(resp.data.port_desc || {});
        }
      } catch (e) {
        console.error('Failed to fetch port desc', e);
      }
    };
    fetchDesc();
  }, []);

  useEffect(() => {
    let mounted = true;
    const fetchStats = async () => {
      try {
        const resp = await api.get('/port-stats');
        if (mounted) {
          setStatsData(resp.data.port_stats || {});
          setHistoryData(resp.data.history || {});
        }
      } catch (e) {
        console.error('Failed to fetch port stats', e);
      }
    };
    
    fetchStats();
    const interval = setInterval(fetchStats, 2000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  let speedForward = 0;
  let speedBackward = 0;

  const srcDpidParsed = edgeData.sourceDpid ? parseInt(edgeData.sourceDpid, 16).toString() : null;
  const dstDpidParsed = edgeData.targetDpid ? parseInt(edgeData.targetDpid, 16).toString() : null;
  const srcPortNum = edgeData.srcPort ? parseInt(edgeData.srcPort, 16) : null;
  const dstPortNum = edgeData.dstPort ? parseInt(edgeData.dstPort, 16) : null;

  let srcCapacity = 100000;
  let dstCapacity = 100000;

  if (srcDpidParsed && descData[srcDpidParsed]) {
    const pDesc = descData[srcDpidParsed].find(p => String(p.port_no) === String(srcPortNum));
    if (pDesc && pDesc.curr_speed) {
      srcCapacity = pDesc.curr_speed;
    }
  }
  
  if (dstDpidParsed && descData[dstDpidParsed]) {
    const pDesc = descData[dstDpidParsed].find(p => String(p.port_no) === String(dstPortNum));
    if (pDesc && pDesc.curr_speed) {
      dstCapacity = pDesc.curr_speed;
    }
  }

  if (srcDpidParsed && historyData[srcDpidParsed] && historyData[srcDpidParsed].length > 0) {
    const latest = historyData[srcDpidParsed][historyData[srcDpidParsed].length - 1];
    if (srcPortNum && latest[`${srcPortNum}_tx`] !== undefined) speedForward = latest[`${srcPortNum}_tx`];
    if (srcPortNum && latest[`${srcPortNum}_rx`] !== undefined) speedBackward = latest[`${srcPortNum}_rx`];
  } else if (dstDpidParsed && historyData[dstDpidParsed] && historyData[dstDpidParsed].length > 0) {
    const latest = historyData[dstDpidParsed][historyData[dstDpidParsed].length - 1];
    if (dstPortNum && latest[`${dstPortNum}_rx`] !== undefined) speedForward = latest[`${dstPortNum}_rx`];
    if (dstPortNum && latest[`${dstPortNum}_tx`] !== undefined) speedBackward = latest[`${dstPortNum}_tx`];
  }

  return (
    <div className="node-detail-overlay">
      <div className="node-detail-header">
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Network size={14} color="#f59e0b" />
          链路使用情况
        </span>
        <button className="btn-close" onClick={onClose}>✕</button>
      </div>
      <div className="node-detail-body">
        <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, background: '#f8fafc', padding: '8px 10px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#475569' }}>{edgeData.srcLabel} → {edgeData.dstLabel}</span>
              <span style={{ color: '#2563eb', fontFamily: 'monospace', fontWeight: 600, fontSize: 13 }}>
                {formatSpeed(speedForward)} <span style={{ fontSize: 10, color: '#64748b', fontWeight: 'normal' }}>({getPercentage(speedForward, srcCapacity)}%)</span>
              </span>
            </div>
            <div style={{ height: 4, width: '100%', background: '#e2e8f0', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ height: '100%', background: '#3b82f6', width: `${getPercentage(speedForward, srcCapacity)}%`, transition: 'width 0.3s ease' }}></div>
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, background: '#f8fafc', padding: '8px 10px', borderRadius: 6, border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#475569' }}>{edgeData.dstLabel} → {edgeData.srcLabel}</span>
              <span style={{ color: '#16a34a', fontFamily: 'monospace', fontWeight: 600, fontSize: 13 }}>
                {formatSpeed(speedBackward)} <span style={{ fontSize: 10, color: '#64748b', fontWeight: 'normal' }}>({getPercentage(speedBackward, dstCapacity)}%)</span>
              </span>
            </div>
            <div style={{ height: 4, width: '100%', background: '#e2e8f0', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ height: '100%', background: '#22c55e', width: `${getPercentage(speedBackward, dstCapacity)}%`, transition: 'width 0.3s ease' }}></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function NetworkTopology() {
  const topology = useStore(s => s.topology)
  const selectedNode = useStore(s => s.selectedNode)
  const setSelectedNode = useStore(s => s.setSelectedNode)
  const activePathEdges = useStore(s => s.activePathEdges)
  const layoutMode = useStore(s => s.layoutMode)

  // 用 useNodesState / useEdgesState + useEffect 保证正确同步
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [selectedEdge, setSelectedEdge] = useState(null)
  
  // 记录上一次拓扑的 JSON，避免无意义的重绘导致的内存泄漏
  const [lastTopoJson, setLastTopoJson] = useState('')

  useEffect(() => {
    if (!topology) return
    const links = topology.links || []
    const topoNodes = topology.nodes || []
    
    // 简易深度比对（忽略时间戳等无关字段），加入 layoutMode 触发重新计算
    const currentJson = JSON.stringify({ nodes: topoNodes, links, layoutMode })
    if (currentJson === lastTopoJson) return
    setLastTopoJson(currentJson)
    
    setNodes(currentNodes => {
      const posMap = new Map(currentNodes.map(n => [n.id, n.position]))
      const calculatedNodes = layoutMode === 'tree' ? toFlowNodesTree(topoNodes, links) : toFlowNodesD3(topoNodes, links)
      
      const mergedNodes = calculatedNodes.map(n => {
        if (posMap.has(n.id)) {
          return { ...n, position: posMap.get(n.id) }
        }
        return n
      })
      
      setEdges(toFlowEdges(links, mergedNodes, activePathEdges))
      // 当切换布局时，忽略 posMap 强制使用新坐标
      if (lastTopoJson && JSON.parse(lastTopoJson).layoutMode !== layoutMode) {
        return calculatedNodes
      }
      return mergedNodes
    })
  }, [topology, layoutMode, setNodes, setEdges, activePathEdges])

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
            onNodeClick={(_, node) => { setSelectedNode(node.data); setSelectedEdge(null); }}
            onEdgeClick={(_, edge) => { setSelectedEdge(edge.data); setSelectedNode(null); }}
            onPaneClick={() => { setSelectedNode(null); setSelectedEdge(null); }}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
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

          {/* 边详情悬浮窗 */}
          {selectedEdge && (
            <EdgeDetailOverlay edgeData={selectedEdge} onClose={() => setSelectedEdge(null)} />
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
                            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 11, fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', background: '#f1f5f9', padding: '4px 8px', borderRadius: 6, fontWeight: 500 }}>
                              <span style={{ color: '#2563eb', minWidth: 36 }}>p={f.priority}</span>
                              <span style={{ color: '#334155', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
                              <span style={{ color: (f.actions?.length === 0 || (!f.actions && !f.instructions)) ? '#dc2626' : '#059669', fontWeight: 600 }}>
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
