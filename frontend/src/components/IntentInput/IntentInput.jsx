import { useState, useRef, useEffect } from 'react'
import useStore from '../../store/useStore'

const STATUS_LABEL = {
  pending: ['badge-pending', '排队中'],
  validating: ['badge-validating', '验证中'],
  executing: ['badge-executing', '执行中'],
  success: ['badge-success', '✓ 成功'],
  failed: ['badge-failed', '✗ 失败'],
  rejected: ['badge-rejected', '⚠ 拒绝'],
  confirmed: ['badge-confirmed', '⏳ 待确认'],
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
          <span className="vl-icon">{layer.passed ? '✅' : '❌'}</span>
          <span className="vl-label">{LAYER_NAME[layer.layer] || layer.layer}</span>
          <span className="vl-msg">{layer.message}</span>
        </div>
      ))}
    </div>
  )
}

function IntentBubble({ record }) {
  const confirmIntent = useStore(s => s.confirmIntent)
  const [badgeClass, badgeLabel] = STATUS_LABEL[record.status] || ['badge-pending', record.status]

  return (
    <div className="intent-entry">
      {/* 用户输入 */}
      <div className="bubble bubble-user">{record.user_text}</div>

      {/* 系统回复 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className={`intent-status-badge ${badgeClass}`}>
          {['pending', 'validating', 'executing'].includes(record.status) && (
            <span className="spinner" style={{ width: 10, height: 10 }} />
          )}
          {badgeLabel}
          {record.llm_retries > 0 && ` (重试${record.llm_retries}次)`}
        </span>

        {record.parsed_intent && (
          <div className="bubble bubble-system">
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {record.parsed_intent.explanation}
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
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
          <div>
            <div className="bubble bubble-system" style={{ marginBottom: 6, borderColor: 'var(--color-warning)' }}>
              ⚠️ 这是高危操作，请确认是否执行？
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
          <div className="bubble bubble-error" style={{ fontSize: 12 }}>
            {record.error_message}
          </div>
        )}

        {record.status === 'success' && record.execution_result && (() => {
          const result = record.execution_result
          // ── 查询类结果：展示数据 ──────────────────────────
          if (result.type === 'stats') {
            return (
              <div className="bubble bubble-system" style={{ fontSize: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-success)' }}>
                  📊 {result.target} 流量统计
                </div>
                {result.summary ? (
                  <pre style={{
                    margin: 0, fontFamily: 'monospace', fontSize: 11,
                    background: 'var(--color-bg-sidebar)', padding: '6px 8px',
                    borderRadius: 4, whiteSpace: 'pre-wrap',
                  }}>
                    {result.summary}
                  </pre>
                ) : (
                  <span style={{ color: 'var(--color-text-muted)' }}>暂无流量数据（尝试在 Mininet 中 ping 一下）</span>
                )}
                {result.data && result.data.length > 0 && result.data[0].ports && (
                  <div style={{ marginTop: 6, color: 'var(--color-text-muted)' }}>
                    端口数: {result.data[0].ports.length}
                  </div>
                )}
              </div>
            )
          }
          if (result.type === 'topology') {
            return (
              <div className="bubble bubble-system" style={{ fontSize: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--color-success)' }}>
                  🌐 {result.message}
                </div>
              </div>
            )
          }
          // ── 执行类结果：策略下发状态 ────────────────────────
          return (
            <div className="bubble bubble-system" style={{ fontSize: 11, color: 'var(--color-success)' }}>
              ✅ 策略已成功下发到 Ryu 控制器
              {result.has_rollback && ' (支持回滚)'}
            </div>
          )
        })()}

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
        <div className="intent-title">🧠 意图输入</div>
        <div className="intent-subtitle">用自然语言描述网络操作</div>
      </div>

      <div className="intent-history">
        {intentHistory.length === 0 && (
          <div style={{ padding: '16px 0' }}>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
              快速示例：
            </div>
            {SUGGESTIONS.map((s, i) => (
              <div
                key={i}
                onClick={() => setText(s)}
                style={{
                  padding: '8px 10px',
                  background: 'var(--color-bg-sidebar)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-sm)',
                  marginBottom: 6,
                  cursor: 'pointer',
                  fontSize: 12,
                  color: 'var(--color-text-secondary)',
                  transition: 'var(--transition)',
                }}
                onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--color-primary)'}
                onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--color-border)'}
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
        <div className="intent-input-row">
          <textarea
            ref={textareaRef}
            className="intent-textarea"
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="描述你的网络操作需求..."
            rows={2}
            disabled={isProcessing}
          />
          <button
            className="intent-send-btn"
            onClick={handleSubmit}
            disabled={!text.trim() || isProcessing}
            title="发送 (Enter)"
          >
            {isProcessing ? <span className="spinner" /> : '↑'}
          </button>
        </div>
        <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 6 }}>
          Enter 发送 · Shift+Enter 换行
        </div>
      </div>
    </>
  )
}
