import { useState, useEffect } from 'react'
import useStore from '../../store/useStore'
import api from '../../services/api'
import { ShieldAlert, Clock4, CornerDownRight, TrendingUp, RefreshCw, CheckCircle2, Settings } from 'lucide-react'
import './PolicyPanel.css'

const POLICY_TYPE_CONFIG = {
  block: { label: '隔离', icon: <ShieldAlert size={14} />, color: '#fc814a' },
  rate_limit: { label: '限速', icon: <Clock4 size={14} />, color: '#f6e05e' },
  redirect: { label: '重定向', icon: <CornerDownRight size={14} />, color: '#63b3ed' },
  priority: { label: '优先级', icon: <TrendingUp size={14} />, color: '#68d391' },
}

function PolicyCard({ policy, onRevoke }) {
  const [revoking, setRevoking] = useState(false)
  const cfg = POLICY_TYPE_CONFIG[policy.policy_type] || { label: policy.policy_type, icon: <Settings size={14} />, color: '#a0aec0' }
  const age = policy.created_at ? Math.floor((Date.now() / 1000 - policy.created_at) / 60) : null

  const handleRevoke = async () => {
    if (revoking) return
    setRevoking(true)
    try {
      await onRevoke(policy.id)
    } finally {
      setRevoking(false)
    }
  }

  return (
    <div className="policy-card" style={{ '--policy-color': cfg.color }}>
      <div className="policy-card-header">
        <span className="policy-icon">{cfg.icon}</span>
        <span className="policy-type-label" style={{ color: cfg.color }}>{cfg.label}</span>
        {age !== null && <span className="policy-age">{age < 1 ? '刚刚' : `${age}分钟前`}</span>}
        <button
          className={`policy-revoke-btn ${revoking ? 'revoking' : ''}`}
          onClick={handleRevoke}
          disabled={revoking}
          title="撤销此策略"
        >
          {revoking ? '...' : '撤销'}
        </button>
      </div>
      <div className="policy-description">{policy.description}</div>
      {(policy.src_host || policy.dst_host) && (
        <div className="policy-hosts">
          {policy.src_host && <span className="host-tag">{policy.src_host}</span>}
          {policy.src_host && policy.dst_host && <span className="host-arrow">↔</span>}
          {policy.dst_host && <span className="host-tag">{policy.dst_host}</span>}
        </div>
      )}
      {policy.meter_ids?.length > 0 && (
        <div className="policy-meta">Meter: #{policy.meter_ids.join(', #')}</div>
      )}
    </div>
  )
}

export default function PolicyPanel() {
  const policies = useStore(s => s.policies) || []
  const setPolicies = useStore(s => s.setPolicies)
  const [loading, setLoading] = useState(false)

  const fetchPolicies = async () => {
    setLoading(true)
    try {
      const resp = await api.get('/policies')
      setPolicies(resp.data.policies || [])
    } catch (e) {
      console.error('获取策略失败:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchPolicies()
  }, [])

  useEffect(() => {
    const unsub = useStore.subscribe(
      state => state.lastPolicyUpdate,
      () => fetchPolicies()
    )
    return unsub
  }, [])

  const handleRevoke = async (policyId) => {
    try {
      await api.delete(`/policies/${policyId}`)
      setPolicies(policies.filter(p => p.id !== policyId))
    } catch (e) {
      console.error('撤销失败:', e)
    }
  }

  return (
    <div className="policy-panel">
      <div className="policy-panel-header">
        <span className="policy-panel-title">
          活跃策略
          {policies.length > 0 && (
            <span className="policy-count-badge">{policies.length}</span>
          )}
        </span>
        <button className="policy-refresh-btn" onClick={fetchPolicies} disabled={loading} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          {loading ? <RefreshCw size={12} className="spin-icon" /> : <RefreshCw size={12} />}
        </button>
      </div>

      {policies.length === 0 ? (
        <div className="policy-empty">
          <div className="policy-empty-icon"><CheckCircle2 size={32} /></div>
          <div>暂无自定义策略</div>
          <div className="policy-empty-sub">通过意图输入来添加策略</div>
        </div>
      ) : (
        <div className="policy-list">
          {policies.map(p => (
            <PolicyCard key={p.id} policy={p} onRevoke={handleRevoke} />
          ))}
        </div>
      )}
    </div>
  )
}
