import { useState, useRef, useEffect } from 'react'
import useStore from '../../store/useStore'
import {
  BrainCircuit, Search, Send, Clock, PlayCircle, Loader2,
  CheckCircle2, XCircle, AlertTriangle, Terminal,
  BarChart3, Globe2, ChevronDown, ChevronUp, Check, X
} from 'lucide-react'

const STATUS_ICONS = {
  pending: <Clock className="w-3 h-3" />,
  validating: <Search className="w-3 h-3" />,
  executing: <PlayCircle className="w-3 h-3" />,
  success: <CheckCircle2 className="w-3 h-3" />,
  failed: <XCircle className="w-3 h-3" />,
  rejected: <AlertTriangle className="w-3 h-3" />,
  confirmed: <Clock className="w-3 h-3" />,
}

const STATUS_LABEL = {
  pending: ['badge-pending', '排队中'],
  validating: ['badge-validating', '验证中'],
  executing: ['badge-executing', '执行中'],
  success: ['badge-success', '成功'],
  failed: ['badge-failed', '失败'],
  rejected: ['badge-rejected', '拒绝'],
  confirmed: ['badge-confirmed', '待确认'],
}

const LAYER_NAME = {
  schema: 'Schema',
  action_whitelist: '白名单',
  node_existence: '节点存在',
  param_range: '参数范围',
  safety: '安全检查',
  conflict: '置信度',
}

function ValidationReport({ report }) {
  if (!report) return null
  return (
    <div className="validation-report">
      {report.layers.map((layer, i) => (
        <div key={i} className="validation-layer">
          <span className={`vl-icon ${layer.passed ? 'text-success' : 'text-danger'}`}>
            {layer.passed ? <Check className="w-3 h-3" /> : <X className="w-3 h-3" />}
          </span>
          <span className="vl-label">{LAYER_NAME[layer.layer] || layer.layer}</span>
          <span className="vl-msg">{layer.message}</span>
        </div>
      ))}
    </div>
  )
}

function IntentBubble({ record }) {
  const confirmIntent = useStore(s => s.confirmIntent)
  const [showDev, setShowDev] = useState(false)
  const [badgeClass, badgeLabel] = STATUS_LABEL[record.status] || ['badge-pending', record.status]
  const isLoading = ['pending', 'validating', 'executing'].includes(record.status)

  return (
    <div className="intent-entry">
      {/* 用户输入 */}
      <div className="bubble bubble-user">{record.user_text}</div>

      {/* 系统回复 */}
      <div className="intent-system-wrapper">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span className={`intent-status-badge ${badgeClass}`}>
            {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : STATUS_ICONS[record.status]}
            {badgeLabel}
            {record.llm_retries > 0 && ` (重试${record.llm_retries}次)`}
          </span>
        </div>

        {record.parsed_intent && (
          <div className="bubble bubble-system">
            <div className="parsed-intent-title">
              {record.parsed_intent.explanation}
            </div>
            <div className="parsed-intent-meta">
              操作: <code>{record.parsed_intent.action}</code>
              {record.parsed_intent.source_node && ` | 源: ${record.parsed_intent.source_node}`}
              {record.parsed_intent.target_node && ` | 目: ${record.parsed_intent.target_node}`}
            </div>
          </div>
        )}

        {record.validation_report && (
          <ValidationReport report={record.validation_report} />
        )}

        {record.status === 'confirmed' && (
          <div className="bubble bubble-warning">
            <div className="flex items-center gap-2 mb-2">
              <AlertTriangle className="w-4 h-4" />
              <span>这是高危操作，请确认是否执行？</span>
            </div>
            <div className="confirm-actions">
              <button
                className="btn btn-primary btn-sm"
                onClick={() => confirmIntent(record.id)}
              >确认执行</button>
              <button className="btn btn-sm">取消</button>
            </div>
          </div>
        )}

        {record.status === 'failed' && record.error_message && (
          <div className="bubble bubble-error">
            <XCircle className="w-4 h-4 inline mr-1" />
            {record.error_message}
          </div>
        )}

        {record.status === 'success' && record.execution_result && (() => {
          const result = record.execution_result
          if (result.type === 'stats') {
            return (
              <div className="bubble bubble-system">
                <div className="result-header text-success">
                  <BarChart3 className="w-4 h-4" />
                  {result.target} 流量统计
                </div>
                {result.summary ? (
                  <pre className="code-block">{result.summary}</pre>
                ) : (
                  <span className="text-muted">暂无流量数据（尝试在 Mininet 中 ping 一下）</span>
                )}
                {result.data && result.data.length > 0 && result.data[0].ports && (
                  <div className="text-muted mt-1 text-xs">
                    端口数: {result.data[0].ports.length}
                  </div>
                )}
              </div>
            )
          }
          if (result.type === 'topology') {
            return (
              <div className="bubble bubble-system">
                <div className="result-header text-success">
                  <Globe2 className="w-4 h-4" />
                  {result.message}
                </div>
              </div>
            )
          }
          return (
            <div className="bubble bubble-system text-success flex items-center gap-1.5">
              <CheckCircle2 className="w-4 h-4" />
              策略已成功下发到 Ryu 控制器
              {result.has_rollback && ' (支持回滚)'}
            </div>
          )
        })()}

        {/* 开发者详情按钮 */}
        <div className="dev-toggle-container">
          <button 
            className="btn-dev-toggle" 
            onClick={() => setShowDev(!showDev)}
          >
            <Terminal className="w-3 h-3" />
            {showDev ? '隐藏开发者详情' : '开发者详情'}
            {showDev ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>

        {/* 开发者详情面板 */}
        {showDev && (
          <div className="bubble bubble-dev">
            <div className="dev-section-title">// 意图解析结果</div>
            <pre className="dev-code">
              {JSON.stringify(record.parsed_intent || {}, null, 2)}
            </pre>
            
            {record.execution_result?.policy && (
              <>
                <div className="dev-section-title mt-2">// 下发网络策略</div>
                <pre className="dev-code">
                  {JSON.stringify(record.execution_result.policy, null, 2)}
                </pre>
              </>
            )}
            
            {record.execution_result?.vm_response && (
              <>
                <div className="dev-section-title mt-2">// 控制器响应</div>
                <pre className="dev-code">
                  {JSON.stringify(record.execution_result.vm_response, null, 2)}
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
  const { submitIntent, isProcessing, intentHistory } = useStore()
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [intentHistory.length])

  const handleSubmit = async () => {
    const t = text.trim()
    if (!t || isProcessing) return
    setText('')
    await submitIntent(t)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const SUGGESTIONS = [
    '查看 s1 的流量统计',
    '限制 h1 到 h3 带宽为 5Mbps',
    '封锁 h2 和 h4 之间的通信',
  ]

  return (
    <>
      <div className="intent-header">
        <div className="intent-title">
          <BrainCircuit className="w-4 h-4 text-primary" />
          意图交互
        </div>
        <div className="intent-subtitle">使用自然语言编排网络策略</div>
      </div>

      <div className="intent-history">
        {intentHistory.length === 0 && (
          <div className="intent-suggestions">
            <div className="suggestions-title">快速尝试：</div>
            {SUGGESTIONS.map((s, i) => (
              <div
                key={i}
                className="suggestion-chip"
                onClick={() => setText(s)}
              >
                {s}
              </div>
            ))}
          </div>
        )}
        {[...intentHistory].reverse().map(record => (
          <IntentBubble key={record.id} record={record} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="intent-input-area">
        <div className="intent-input-wrapper">
          <textarea
            ref={textareaRef}
            className="intent-textarea"
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述你的网络操作需求..."
            rows={1}
            disabled={isProcessing}
          />
          <button
            className="intent-send-btn"
            onClick={handleSubmit}
            disabled={!text.trim() || isProcessing}
            title="发送 (Enter)"
          >
            {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
        <div className="intent-hint">
          Enter 发送 · Shift+Enter 换行
        </div>
      </div>
    </>
  )
}
