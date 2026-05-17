import { useEffect, useMemo } from 'react'
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
  Handle, Position,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import useStore from '../../store/useStore'

// ─── 自定义节点 ──────────────────────────────────────
function TopoNode({ data, selected }) {
  const isSwitch = data.type === 'switch'
  return (
    <div className={`topo-node ${isSwitch ? 'node-switch' : 'node-host'} ${selected ? 'selected' : ''}`}>
      {/* 顶部端口 (Target + Source 叠加) */}
      <Handle type="target" position={Position.Top} id="t-left"   style={{ left: '25%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-left"  style={{ left: '25%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="target" position={Position.Top} id="t-center" style={{ left: '50%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-center" style={{ left: '50%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="target" position={Position.Top} id="t-right"  style={{ left: '75%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="source" position={Position.Top} id="st-right" style={{ left: '75%', width: 6, height: 6, opacity: 0 }} />

      {/* 底部端口 (Source + Target 叠加) */}
      <Handle type="source" position={Position.Bottom} id="b-left"   style={{ left: '25%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-left"  style={{ left: '25%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="b-center" style={{ left: '50%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-center" style={{ left: '50%', width: 6, height: 6, opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} id="b-right"  style={{ left: '75%', width: 6, height: 6, background: '#6366f1', border: '1px solid #fff' }} />
      <Handle type="target" position={Position.Bottom} id="tb-right" style={{ left: '75%', width: 6, height: 6, opacity: 0 }} />
      <span className="topo-node-icon">{isSwitch ? '🔀' : '💻'}</span>
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


function toFlowEdges(links, flowNodes = []) {
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

    return {
      id: link.id,
      source: sId,
      target: tId,
      sourceHandle: sHandle,
      targetHandle: tHandle,
    type: 'smoothstep', // 使用带圆角的折线，更适合网络拓扑
    animated: link.state === 'up',
    style: {
      stroke: link.state === 'down'     ? '#ef4444'
            : link.state === 'degraded' ? '#f59e0b'
            : '#6366f1',
      strokeWidth: 2,
      strokeDasharray: link.state === 'down' ? '6,4' : undefined,
    },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6366f1' },
    label: link.utilization_pct != null
      ? `${link.utilization_pct.toFixed(0)}%`
      : undefined,
    }
  })
}

export default function NetworkTopology() {
  const topology = useStore(s => s.topology)

  // 用 useNodesState / useEdgesState + useEffect 保证正确同步
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    if (!topology) return
    const links = topology.links || []
    const newNodes = toFlowNodes(topology.nodes || [], links)
    setNodes(newNodes)
    setEdges(toFlowEdges(links, newNodes))
  }, [topology])

  const isEmpty = !topology?.nodes?.length

  return (
    <div className="topology-canvas">
      {isEmpty ? (
        <div className="empty-topology">
          <div className="empty-topology-icon">🌐</div>
          <div className="empty-topology-text">暂无拓扑数据</div>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            请确认 VM Agent 正在运行
          </div>
        </div>
      ) : (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.2}
          maxZoom={2.5}
          attributionPosition="bottom-right"
        >
          <Background color="#e2e8f0" gap={20} size={1} />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={n => n.data?.type === 'switch' ? '#6366f1' : '#16a34a'}
            maskColor="rgba(248,250,252,0.8)"
            style={{ border: '1px solid #e2e8f0', borderRadius: 8 }}
          />
        </ReactFlow>
      )}
    </div>
  )
}
