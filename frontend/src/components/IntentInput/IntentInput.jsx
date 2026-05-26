import { useState, useRef, useEffect } from 'react'
import useStore from '../../store/useStore'
import {
  BrainCircuit, Search, Clock, Zap, CheckCircle2, XCircle, AlertTriangle, Network,
  ArrowRightLeft, Activity, ShieldAlert, CheckSquare, Clock4, TrendingUp, CornerDownRight,
  ActivitySquare, Trash2, Send, Lightbulb, ChevronDown, ChevronUp, ChevronRight
} from 'lucide-react'

const STATUS_CONFIG = {
  pending:   { cls: 'badge-pending',   label: '排队中',  icon: <Clock size={12} /> },
  parsing:   { cls: 'badge-validating', label: '解析中', icon: <Search size={12} /> },
  executing: { cls: 'badge-executing', label: '执行中',  icon: <Zap size={12} /> },
  success:   { cls: 'badge-success',   label: '成功',    icon: <CheckCircle2 size={12} /> },
  failed:    { cls: 'badge-failed',    label: '失败',    icon: <XCircle size={12} /> },
}

const ACTION_ICONS = {
  query_topology:   <Network size={14} />,
  query_flows:      <ArrowRightLeft size={14} />,
  query_port_stats: <Activity size={14} />,
  block_traffic:    <ShieldAlert size={14} />,
  allow_traffic:    <CheckSquare size={14} />,
  rate_limit:       <Clock4 size={14} />,
  set_priority:     <TrendingUp size={14} />,
  redirect_traffic: <CornerDownRight size={14} />,
  clear_flows:      <Trash2 size={14} />,
}

// 快捷操作模板
const QUICK_ACTIONS = [
  { label: '查看拓扑', text: '显示当前网络拓扑结构', icon: <Network size={12} /> },
  { label: '查看流表', text: '查看所有交换机的流表', icon: <ArrowRightLeft size={12} /> },
  { label: '端口统计', text: '查看所有交换机的端口流量统计', icon: <Activity size={12} /> },
  { label: '隔离主机', text: '隔离 h1 和 h3 的通信', icon: <ShieldAlert size={12} /> },
  { label: '带宽限速', text: '限制 h2 到 h4 的带宽为 5Mbps', icon: <Clock4 size={12} /> },
  { label: '恢复通信', text: '恢复 h1 和 h3 的通信', icon: <CheckSquare size={12} /> },
  { label: '高优先级', text: '给 h1 到 h2 的流量设置优先级 300', icon: <TrendingUp size={12} /> },
]

function ResultDisplay({ result, action }) {
  if (!result) return null

  // query_topology 结果
  if (result.type === 'query_topology') {
    const nodes = result.data?.nodes || []
    const switches = nodes.filter(n => n.type === 'switch').length
    const hosts = nodes.filter(n => n.type === 'host').length
    return (
      <div className="bubble bubble-system">
        <div className="result-header" style={{ color: '#63b3ed' }}>
          <Network size={16} /> {result.message}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 5 }}>
          {[['交换机', switches, '#63b3ed'], ['主机', hosts, '#68d391']].map(([l, v, c]) => (
            <div key={l} style={{ background: 'rgba(255,255,255,0.05)', borderRadius: 6, padding: '4px 10px', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: c }}>{v}</div>
              <div style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{l}</div>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // query_flows 结果
  if (result.type === 'query_flows') {
    const flows = result.data || {}
    return (
      <div className="bubble bubble-system">
        <div className="result-header" style={{ color: '#63b3ed' }}>
          <ArrowRightLeft size={16} /> {result.message}
        </div>
        <div style={{ marginTop: 5, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {Object.entries(flows).map(([dpid, entries]) => (
            <div key={dpid} style={{ fontSize: 11, display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ color: '#63b3ed', fontFamily: 'monospace' }}>dpid={dpid}</span>
              <span style={{ color: 'var(--color-text-muted)' }}>{entries.length} 条规则</span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
          ← 切换左侧「流表」Tab 查看详情
        </div>
      </div>
    )
  }

  // query_port_stats 结果
  if (result.type === 'query_port_stats') {
    return (
      <div className="bubble bubble-system">
        <div className="result-header" style={{ color: '#f6e05e' }}>
          <Activity size={16} /> {result.message}
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
          ← 切换左侧「端口统计」Tab 查看详情
        </div>
      </div>
    )
  }

  // 控制类操作成功结果
  const controlColors = {
    block_traffic: '#fc814a',
    allow_traffic: '#48bb78',
    rate_limit: '#f6e05e',
    set_priority: '#68d391',
    redirect_traffic: '#63b3ed',
    clear_flows: '#a0aec0',
  }
  const color = controlColors[result.type] || '#48bb78'

  return (
    <div className="bubble bubble-system">
      <div className="result-header" style={{ color }}>
        {ACTION_ICONS[result.type] || <CheckCircle2 size={16} />} {result.message}
      </div>
      {result.installed_on && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
          已下发到: {result.installed_on.join(', ')}
        </div>
      )}
      {result.meter_id && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
          Meter ID: #{result.meter_id} | {result.rate_kbps}Kbps
        </div>
      )}
      {result.src_mac && (
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2, fontFamily: 'monospace' }}>
          {result.src_mac} ↔ {result.dst_mac}
        </div>
      )}
      <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
        ← 切换左侧「活跃策略」Tab 查看详情
      </div>
    </div>
  )
}

function IntentBubble({ record }) {
  const [showDev, setShowDev] = useState(false)
  const cfg = STATUS_CONFIG[record.status] || STATUS_CONFIG.pending
  const isLoading = ['pending', 'parsing', 'executing'].includes(record.status)
  const intent = record.parsed_intent

  return (
    <div className="intent-entry">
      {/* 用户输入 */}
      <div className="bubble bubble-user">{record.user_text}</div>

      {/* 系统回复区 */}
      <div className="intent-system-wrapper">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span className={`intent-status-badge ${cfg.cls}`}>
            {isLoading ? <span className="spin-icon">⟳</span> : cfg.icon}
            {cfg.label}
            {record.llm_retries > 0 && ` (重试${record.llm_retries}次)`}
          </span>
        </div>

        {/* 解析结果气泡 */}
        {intent && (
          <div className="bubble bubble-system">
            <div className="parsed-intent-title">
              {ACTION_ICONS[intent.action] || <CheckSquare size={14} />} {intent.explanation}
            </div>
            <div className="parsed-intent-meta">
              <code>{intent.action}</code>
              {intent.src_host && ` | 源: ${intent.src_host}`}
              {intent.dst_host && ` | 目标: ${intent.dst_host}`}
              {intent.target_switch && ` | 交换机: ${intent.target_switch}`}
            </div>
          </div>
        )}

        {/* 执行结果 —— 成功或失败时均尝试 ResultDisplay 渲染 */}
        {record.execution_result && (
          <ResultDisplay result={record.execution_result} action={intent?.action} />
        )}

        {/* 纯文本错误兜底：仅在无 execution_result 时显示 */}
        {record.status === 'failed' && !record.execution_result && record.error_message && (
          <div className="bubble bubble-error" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <XCircle size={14} /> {record.error_message}
          </div>
        )}


        {/* 开发者详情 */}
        <div className="dev-toggle-container">
          <button className="btn-dev-toggle" onClick={() => setShowDev(!showDev)}>
            {showDev ? <ChevronUp size={12} /> : <ChevronDown size={12} />} {showDev ? '隐藏详情' : '查看详情'}
          </button>
        </div>

        {showDev && (
          <div className="bubble bubble-dev">
            <div className="dev-section-title">// 解析结果</div>
            <pre className="dev-code">{JSON.stringify(intent || {}, null, 2)}</pre>
            {record.execution_result && (
              <>
                <div className="dev-section-title mt-2">// 执行结果</div>
                <pre className="dev-code">
                  {JSON.stringify(record.execution_result, null, 2).slice(0, 1000)}
                </pre>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default function IntentInput() {
  const [text, setText] = useState('')
  const [showQuickActions, setShowQuickActions] = useState(false)
  const { submitIntent, isProcessing, intentHistory } = useStore()
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [intentHistory.length])

  const handleSubmit = async () => {
    const t = text.trim()
    if (!t || isProcessing) return
    setText('')
    setShowQuickActions(false)
    await submitIntent(t)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleQuickAction = (actionText) => {
    setText(actionText)
    setShowQuickActions(false)
  }

  return (
    <>
      <div className="intent-header">
        <div className="intent-title">
          <BrainCircuit size={18} className="text-primary" /> 意图交互
        </div>
        <div className="intent-subtitle">用自然语言控制 SDN 网络</div>
      </div>

      <div className="intent-history">
        {intentHistory.length === 0 && (
          <div style={{ padding: '16px 0' }}>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
              <Lightbulb size={14} /> 快捷操作
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {QUICK_ACTIONS.map((a, i) => (
                <button
                  key={i}
                  className="suggestion-chip"
                  onClick={() => handleQuickAction(a.text)}
                  style={{ display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {a.icon} {a.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {[...intentHistory].reverse().map(record => (
          <IntentBubble key={record.id} record={record} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="intent-input-area">
        {/* 快捷操作展开 */}
        {intentHistory.length > 0 && (
          <div style={{ marginBottom: 6 }}>
            <button
              className="btn-dev-toggle"
              onClick={() => setShowQuickActions(!showQuickActions)}
              style={{ width: '100%', justifyContent: 'center' }}
            >
              <Lightbulb size={12} /> 快捷操作 {showQuickActions ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {showQuickActions && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 5 }}>
                {QUICK_ACTIONS.map((a, i) => (
                  <button
                    key={i}
                    className="suggestion-chip"
                    onClick={() => handleQuickAction(a.text)}
                    style={{ fontSize: 10, display: 'flex', alignItems: 'center', gap: 4 }}
                  >
                    {a.icon} {a.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="intent-input-wrapper">
          <textarea
            className="intent-textarea"
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述你的网络管理需求，例如：隔离 h1 和 h3 的通信"
            rows={2}
            disabled={isProcessing}
          />
          <button
            className="intent-send-btn"
            onClick={handleSubmit}
            disabled={!text.trim() || isProcessing}
            title="发送 (Enter)"
          >
            {isProcessing ? <span className="spin-icon"><Clock size={16} /></span> : <Send size={16} />}
          </button>
        </div>
        <div className="intent-hint">Enter 发送 · Shift+Enter 换行</div>
      </div>
    </>
  )
}
