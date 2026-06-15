import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import useStore from '../../store/useStore'
import {
  BrainCircuit, Search, Clock, Zap, CheckCircle2, XCircle, AlertTriangle, Network,
  ArrowRightLeft, Activity, ShieldAlert, CheckSquare, Clock4, TrendingUp, CornerDownRight,
  ActivitySquare, Trash2, Send, Lightbulb, ChevronDown, ChevronUp, ChevronRight, ShieldCheck
} from 'lucide-react'

const STATUS_CONFIG = {
  pending:               { cls: 'badge-pending',    label: '排队中',   icon: <Clock size={12} /> },
  parsing:               { cls: 'badge-validating', label: '解析中',   icon: <Search size={12} /> },
  executing:             { cls: 'badge-executing',  label: '执行中',   icon: <Zap size={12} /> },
  success:               { cls: 'badge-success',    label: '成功',     icon: <CheckCircle2 size={12} /> },
  failed:                { cls: 'badge-failed',     label: '失败',     icon: <XCircle size={12} /> },
  conflict:              { cls: 'badge-conflict',   label: '策略冲突', icon: <AlertTriangle size={12} /> },
  clarification:         { cls: 'badge-warning',   label: '需要补充', icon: <Search size={12} /> },
  chat:                  { cls: 'badge-pending',    label: '对话',     icon: <BrainCircuit size={12} /> },
  awaiting_confirmation: { cls: 'badge-warning',   label: '待确认',   icon: <AlertTriangle size={12} /> },
}

const ACTION_ICONS = {
  query_topology: <Network size={14} />,
  query_flows: <ArrowRightLeft size={14} />,
  query_port_stats: <Activity size={14} />,
  block_traffic: <ShieldAlert size={14} />,
  allow_traffic: <CheckSquare size={14} />,
  rate_limit: <Clock4 size={14} />,
  set_priority: <TrendingUp size={14} />,
  redirect_traffic: <CornerDownRight size={14} />,
  clear_flows: <Trash2 size={14} />,
  add_flow: <CheckSquare size={14} />,
  delete_flow: <Trash2 size={14} />,
  load_balance: <ActivitySquare size={14} />,
  vlan: <Network size={14} />,
}

// 快捷操作模板
const QUICK_ACTIONS = [
  { label: '负载均衡', text: '为 H1 和 H2 之间的双向流量开启多路径负载均衡', icon: <ArrowRightLeft size={12} /> },
  { label: '访问控制', text: '单向拒绝 H1 访问 H3 的 SSH 服务', icon: <ShieldAlert size={12} /> },
  { label: '批量限速', text: '除了 H3 外，将 H1 到所有主机的带宽限制在 5M', icon: <Clock4 size={12} /> },
  { label: '划分VLAN', text: '把 H1 和 H2 划分到 VLAN 10', icon: <Network size={12} /> },
  { label: '流量标记', text: '把 H1 到 H2 的视频流量的 DSCP 标记设为 46', icon: <ActivitySquare size={12} /> },
  { label: '恢复通信', text: '恢复 H1 和 H3 的通信', icon: <CheckSquare size={12} /> },
  { label: '优先覆盖', text: '以 800 的高优先级阻断 H1 和 H2 的通信', icon: <TrendingUp size={12} /> },
  { label: '清除流表', text: '清空全网所有交换机的流表', icon: <Trash2 size={12} /> },
]

function ConfirmationCard({ result, isOverride }) {
  const [loading, setLoading] = useState(false)
  const [done, setDone] = useState(false)
  const [doneMsg, setDoneMsg] = useState('')

  // 复用与 api.js 相同的 baseURL 逻辑，确保请求打到后端 :8000 而不是 Vite :5173
  const API_BASE = import.meta.env.VITE_API_BASE_URL || `http://${window.location.hostname}:8000/api`

  const handleAction = async (cancel) => {
    setLoading(true)
    try {
      const url = `${API_BASE}/intent/confirm/${result.token}${cancel ? '?cancel=true' : ''}`
      const res = await fetch(url, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setDone(true)
      setDoneMsg(cancel ? '已取消' : (data.message || '确认成功，请等待执行结果'))
    } catch (e) {
      setDone(true)
      setDoneMsg('请求失败: ' + e.message)
    } finally {
      setLoading(false)
    }
  }

  if (done) {
    return (
      <div className="bubble bubble-system" style={{ borderLeft: isOverride ? '3px solid #f97316' : '3px solid #ef4444' }}>
        <div style={{ fontSize: 13, color: '#6b7280' }}>{doneMsg}</div>
      </div>
    )
  }

  const title = isOverride ? '⚠️ 检测到旧策略，是否替换？' : '高危操作，需要确认'
  const confirmLabel = isOverride ? '替换旧策略' : '确认执行（危险）'
  const accentColor = isOverride ? '#ea580c' : '#dc2626'

  return (
    <div className={`bubble bubble-system confirm-card ${isOverride ? 'is-override' : 'is-risk'}`}>
      {/* 标题 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700, color: accentColor, fontSize: 13 }}>
        <AlertTriangle size={14} /> {title}
      </div>

      {/* 风险描述 */}
      <div style={{ fontSize: 12, color: '#374151', marginTop: 2, lineHeight: 1.5 }}>
        {result.risk_description}
      </div>

      {/* OVERRIDE 时展示旧/新策略对比 */}
      {isOverride && result.old_policy && Object.keys(result.old_policy).length > 0 && (
        <div className="confirm-compare-grid">
          <div className="confirm-box old-policy">
            <div style={{ fontWeight: 700, color: '#b91c1c', marginBottom: 4 }}>旧策略</div>
            <div style={{ color: '#7f1d1d', fontFamily: 'monospace' }}>
              {result.old_policy.description || result.old_policy.id?.slice(0, 12) + '…'}
            </div>
            {result.old_policy.action_params && Object.keys(result.old_policy.action_params).length > 0 && (
              <pre style={{ margin: '4px 0 0', fontSize: 10, color: '#92400e', whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(result.old_policy.action_params, null, 2)}
              </pre>
            )}
          </div>
          <div className="confirm-box new-policy">
            <div style={{ fontWeight: 700, color: '#15803d', marginBottom: 4 }}>新策略</div>
            <div style={{ color: '#14532d', fontFamily: 'monospace' }}>
              {result.new_intent?.action}
            </div>
            {result.new_intent?.action_params && Object.keys(result.new_intent.action_params).length > 0 && (
              <pre style={{ margin: '4px 0 0', fontSize: 10, color: '#166534', whiteSpace: 'pre-wrap' }}>
                {JSON.stringify(result.new_intent.action_params, null, 2)}
              </pre>
            )}
          </div>
        </div>
      )}

      {/* 操作按钮 */}
      <div className="confirm-actions">
        <button
          onClick={() => handleAction(false)}
          disabled={loading}
          className={`confirm-btn confirm-btn-primary ${isOverride ? 'override' : 'risk'}`}
        >
          {loading ? '处理中…' : confirmLabel}
        </button>
        <button
          onClick={() => handleAction(true)}
          disabled={loading}
          className="confirm-btn confirm-btn-cancel"
        >
          取消
        </button>
      </div>
    </div>
  )
}

function ResultDisplay({ result, action }) {
  if (!result) return null

  // 幂等跳过（DUPLICATE）
  if (result.type === 'duplicate_skip') {
    return (
      <div className="bubble bubble-system" style={{ borderLeft: '3px solid #34d399' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, color: '#059669' }}>
          <CheckCircle2 size={14} /> 策略已存在，无需重复下发
        </div>
        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 4 }}>{result.message}</div>
      </div>
    )
  }

  // 待确认操作（confirmation_required）
  if (result.type === 'confirmation_required') {
    const isOverride = result.confirmation_type === 'override'
    const accentColor = isOverride ? '#f97316' : '#ef4444'
    const accentBg    = isOverride ? '#fff7ed' : '#fef2f2'
    const borderColor = isOverride ? '#fed7aa' : '#fecaca'
    return (
      <ConfirmationCard result={result} accentColor={accentColor} accentBg={accentBg} borderColor={borderColor} isOverride={isOverride} />
    )
  }

  // 澄清需求
  if (result.type === 'clarification') {
    return (
      <div className="bubble bubble-system" style={{ borderLeft: '3px solid #8b5cf6' }}>
        <div className="result-header" style={{ color: '#8b5cf6', display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
          <BrainCircuit size={14} /> 需要补充说明
        </div>
        <div style={{ marginTop: 8, fontSize: 13, color: 'var(--color-text-primary)', whiteSpace: 'pre-wrap' }}>
          {result.reason}
        </div>
        <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {(result.options || []).map((opt, i) => (
            <button 
              key={i} 
              className="suggestion-chip" 
              style={{ 
                textAlign: 'left', 
                display: 'flex', 
                flexDirection: 'column', 
                gap: 6, 
                padding: '12px 14px',
                fontFamily: 'inherit',
                border: '1px solid #c4b5fd',
                background: '#fcfaff'
              }}
              onClick={() => {
                const inputEl = document.querySelector('.intent-textarea')
                if (inputEl) {
                  window.dispatchEvent(new CustomEvent('fill-intent', { detail: opt.suggested_input }))
                }
              }}
            >
              <div style={{ fontWeight: 600, color: '#6d28d9', fontSize: 13, fontFamily: 'inherit' }}>{opt.label}</div>
              <div style={{ fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap', lineHeight: 1.5, fontFamily: 'inherit' }}>{opt.description}</div>
            </button>
          ))}
        </div>
      </div>
    )
  }

  if (result.success === false) {
    return (
      <div className="bubble bubble-error" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
          <XCircle size={14} /> 执行失败
        </div>
        <div style={{ fontSize: 12 }}>
          {result.error || result.message || '未知错误'}
        </div>
      </div>
    )
  }

  // query_topology 结果
  if (result.type === 'query_topology') {
    const nodes = result.data?.nodes || []
    const switches = nodes.filter(n => n.type === 'switch').length
    const hosts = nodes.filter(n => n.type === 'host').length
    return (
      <div className="bubble bubble-system">
        <div className="result-header" style={{ color: '#60a5fa' }}>
          <Network size={16} /> {result.message}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 5 }}>
          {[['交换机', switches, '#60a5fa'], ['主机', hosts, '#34d399']].map(([l, v, c]) => (
            <div key={l} style={{ background: '#f8fafc', borderRadius: 6, padding: '6px 12px', textAlign: 'center', border: '1px solid #e2e8f0' }}>
              <div style={{ fontSize: 16, fontWeight: 800, color: c }}>{v}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>{l}</div>
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
        <div className="result-header" style={{ color: '#60a5fa' }}>
          <ArrowRightLeft size={16} /> {result.message}
        </div>
        <div style={{ marginTop: 5, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {Object.entries(flows).map(([dpid, entries]) => (
            <div key={dpid} style={{ fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ color: '#60a5fa', fontFamily: 'monospace' }}>dpid={dpid}</span>
              <span style={{ color: '#64748b' }}>{entries.length} 条规则</span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 6 }}>
          ← 切换左侧「流表」Tab 查看详情
        </div>
      </div>
    )
  }

  // query_port_stats 结果
  if (result.type === 'query_port_stats') {
    return (
      <div className="bubble bubble-system">
        <div className="result-header" style={{ color: '#fbbf24' }}>
          <Activity size={16} /> {result.message}
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 4 }}>
          ← 切换左侧「端口统计」Tab 查看详情
        </div>
      </div>
    )
  }

  // 策略冲突结果
  if (result.type === 'conflict') {
    const conflicts = result.conflicts || []
    const severityLabel = {
      mutually_exclusive: '互斥',
      duplicate: '重复',
      override: '覆盖',
    }
    return (
      <div className="bubble bubble-conflict">
        <div className="result-header" style={{ color: '#ea580c', display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
          <AlertTriangle size={14} /> 策略冲突检测
        </div>
        <div style={{ fontSize: 12, marginBottom: 8, color: '#9a3412' }}>
          {result.message}
        </div>
        {conflicts.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {conflicts.map((c, i) => (
              <div key={i} className="conflict-item">
                <span className={`conflict-severity severity-${c.severity}`}>
                  {severityLabel[c.severity] || c.severity}
                </span>
                <div style={{ flex: 1, fontSize: 11 }}>
                  <div style={{ fontWeight: 600, color: '#7c2d12', marginBottom: 2 }}>
                    {c.existing_description || c.description}
                  </div>
                  <div style={{ color: '#92400e', fontFamily: 'monospace' }}>
                    ID: {c.policy_id?.slice(0, 8)}…
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // 助手对话回复（兜底，一般不会触发）
  if (result.type === 'chat') {
    return (
      <div className="bubble bubble-system" style={{ whiteSpace: 'pre-wrap', lineHeight: '1.5' }}>
        <div className="result-header" style={{ color: '#8b5cf6', display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
          <BrainCircuit size={14} /> 助手回复
        </div>
        <div className="chat-markdown-body" style={{ marginTop: 8, fontSize: 13, color: 'var(--color-text-primary)' }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.message}</ReactMarkdown>
        </div>
      </div>
    )
  }


  // 控制类操作成功结果
  const controlColors = {
    block_traffic: '#f97316',     // orange-500
    allow_traffic: '#34d399',     // emerald-400
    rate_limit: '#f59e0b',        // amber-500
    set_priority: '#10b981',      // emerald-500
    redirect_traffic: '#60a5fa',  // blue-400
    clear_flows: '#64748b',       // slate-500
    add_flow: '#34d399',          // emerald-400
    delete_flow: '#f43f5e',       // rose-500
    load_balance: '#a855f7',      // purple-500
  }
  const color = controlColors[result.type] || '#34d399'

  return (
    <div className="bubble bubble-system">
      <div className="result-header" style={{ color, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
        {ACTION_ICONS[result.type] || <CheckCircle2 size={14} />} {result.message}
      </div>

      <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px dashed var(--color-border)', fontSize: 12 }}>
        {result.installed_on && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <span style={{ color: 'var(--color-text-muted)', width: 60 }}>下发节点:</span>
            <span style={{ color: 'var(--color-text-primary)' }}>{result.installed_on.join(', ')}</span>
          </div>
        )}
        {result.meter_id && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <span style={{ color: 'var(--color-text-muted)', width: 60 }}>Meter ID:</span>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'monospace' }}>#{result.meter_id} ({result.rate_kbps}Kbps)</span>
          </div>
        )}
        {result.src_mac && (
          <div style={{ display: 'flex', gap: 8, marginBottom: 4 }}>
            <span style={{ color: 'var(--color-text-muted)', width: 60 }}>匹配链路:</span>
            <span style={{ color: 'var(--color-text-primary)', fontFamily: 'monospace' }}>{result.src_mac} ↔ {result.dst_mac}</span>
          </div>
        )}
      </div>

      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
        ← 请在左侧「活跃策略」中查看规则详情
      </div>
    </div>
  )
}

function IntentBubble({ record }) {
  const [showDev, setShowDev] = useState(false)
  // 从执行结果中推断真实状态（冲突时覆盖 success 状态）
  const effectiveStatus = (() => {
    if (['pending', 'parsing', 'executing'].includes(record.status)) return record.status
    if (record.execution_result?.type === 'conflict') return 'conflict'
    if (record.execution_result?.type === 'clarification') return 'clarification'
    if (record.execution_result?.type === 'confirmation_required') return 'awaiting_confirmation'
    if (record.execution_result?.type === 'duplicate_skip') return 'success'
    return record.status
  })()
  const cfg = STATUS_CONFIG[effectiveStatus] || STATUS_CONFIG.pending
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
            <div className="parsed-intent-title" style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--color-text-primary)' }}>
              {ACTION_ICONS[intent.action] || <CheckSquare size={14} />} {intent.explanation}
            </div>
            <div className="parsed-intent-meta" style={{ marginTop: 6 }}>
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
        <div className="dev-toggle-container" style={{ textAlign: 'left', paddingLeft: 4 }}>
          <button className="btn-dev-toggle" onClick={() => setShowDev(!showDev)}>
            {showDev ? <ChevronUp size={12} /> : <ChevronDown size={12} />} {showDev ? '隐藏底层详情' : '查看底层详情'}
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

  useEffect(() => {
    const handleFillIntent = (e) => {
      setText(e.detail)
      const inputEl = document.querySelector('.intent-textarea')
      if (inputEl) inputEl.focus()
    }
    window.addEventListener('fill-intent', handleFillIntent)
    return () => window.removeEventListener('fill-intent', handleFillIntent)
  }, [])

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
            placeholder="描述你的网络管理需求"
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
