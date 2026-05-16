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
      {/* React Flow 必须有 Handle 才能渲染边 */}
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
      <Handle type="target" position={Position.Left}   style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right}  style={{ opacity: 0 }} />
      <span className="topo-node-icon">{isSwitch ? '🔀' : '💻'}</span>
      <span className="topo-node-label">{data.label}</span>
      {data.ip && <span className="topo-node-ip">{data.ip}</span>}
    </div>
  )
}

const nodeTypes = { topoNode: TopoNode }

// ─── 自动布局算法 ─────────────────────────────────────
function toFlowNodes(nodes) {
  const switches = nodes.filter(n => n.type === 'switch')
  const hosts    = nodes.filter(n => n.type === 'host')
  const result   = []

  const cx = 450, cy = 280

  // 交换机：圆形排列在中间
  switches.forEach((sw, i) => {
    const angle = (i / Math.max(switches.length, 1)) * 2 * Math.PI - Math.PI / 2
    const r = switches.length === 1 ? 0 : 140
    result.push({
      id: sw.id,
      type: 'topoNode',
      position: {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
      },
      data: { ...sw },
    })
  })

  // 主机：外圈排列
  hosts.forEach((h, i) => {
    const angle = (i / Math.max(hosts.length, 1)) * 2 * Math.PI - Math.PI / 2
    const r = 290
    result.push({
      id: h.id,
      type: 'topoNode',
      position: {
        x: cx + r * Math.cos(angle),
        y: cy + r * Math.sin(angle),
      },
      data: { ...h },
    })
  })

  return result
}

function toFlowEdges(links) {
  return links.map(link => ({
    id: link.id,
    source: String(link.source),
    target: String(link.target),
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
  }))
}

export default function NetworkTopology() {
  const topology = useStore(s => s.topology)

  // 用 useNodesState / useEdgesState + useEffect 保证正确同步
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  useEffect(() => {
    if (!topology) return
    setNodes(toFlowNodes(topology.nodes || []))
    setEdges(toFlowEdges(topology.links || []))
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
