import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'
import api from '../services/api'

const useStore = create(subscribeWithSelector((set, get) => ({
  // ─── 网络拓扑 ──────────────────────────────
  topology: { nodes: [], links: [] },
  networkStatus: { ryu_connected: false, node_count: 0, link_count: 0, active_alerts: 0 },
  alerts: [],
  wsConnected: false,

  // ─── 意图历史 ──────────────────────────────
  intentHistory: [],
  isProcessing: false,
  isInitialLoading: true,

  // ─── 策略状态（用于触发 PolicyPanel 刷新）──
  lastPolicyUpdate: null,

  // ─── UI 状态 ───────────────────────────────
  selectedNode: null,
  activePathEdges: [],

  // ─── Actions ──────────────────────────────
  setSelectedNode: (node) => set({ selectedNode: node }),

  setTopology: (topology) => set({ topology }),

  setNetworkStatus: (networkStatus) => set({ networkStatus }),

  addAlert: (alert) => set(s => ({ alerts: [alert, ...s.alerts].slice(0, 50) })),

  setWsConnected: (v) => set({ wsConnected: v }),

  triggerPolicyUpdate: () => set({ lastPolicyUpdate: Date.now() }),

  triggerPathAnimation: (source, target, via = null) => {
    const topo = get().topology
    if (!topo?.links) return

    const links = topo.links
    const activeIds = new Set()

    const findEdgeId = (n1, n2) => {
      const link = links.find(l =>
        (l.source === n1 && l.target === n2) || (l.target === n1 && l.source === n2)
      )
      return link ? link.id : null
    }

    if (source && target) {
      if (via) {
        const e1 = findEdgeId(source, via)
        const e2 = findEdgeId(via, target)
        if (e1) activeIds.add(e1)
        if (e2) activeIds.add(e2)
      } else {
        const sourceLink = links.find(l => l.source === source || l.target === source)
        const targetLink = links.find(l => l.source === target || l.target === target)
        if (sourceLink) activeIds.add(sourceLink.id)
        if (targetLink) activeIds.add(targetLink.id)
        if (sourceLink && targetLink) {
          const sw1 = sourceLink.source === source ? sourceLink.target : sourceLink.source
          const sw2 = targetLink.source === target ? targetLink.target : targetLink.source
          if (sw1 !== sw2) {
            const isl = findEdgeId(sw1, sw2) || findEdgeId(sw1, 's1') || findEdgeId(sw2, 's1')
            if (isl) activeIds.add(isl)
          }
        }
      }
    }

    if (activeIds.size > 0) {
      set({ activePathEdges: Array.from(activeIds) })
      setTimeout(() => set({ activePathEdges: [] }), 4000)
    }
  },

  // ─── 意图记录管理 ──────────────────────────
  addIntentRecord: (record) => set(s => ({
    intentHistory: [record, ...s.intentHistory].slice(0, 30),
  })),

  updateIntentRecord: (updated) => {
    const oldRecord = get().intentHistory.find(r => r.id === updated.id)

    // 执行成功后触发路径动画
    if (oldRecord && oldRecord.status !== 'success' && updated.status === 'success') {
      const intent = updated.parsed_intent
      if (intent) {
        const animActions = ['ping_test', 'allow_traffic', 'redirect_traffic', 'block_traffic']
        if (animActions.includes(intent.action)) {
          get().triggerPathAnimation(intent.src_host, intent.dst_host)
        }
        // 控制类操作成功后刷新策略
        const controlActions = ['block_traffic', 'allow_traffic', 'rate_limit', 'set_priority', 'redirect_traffic', 'clear_flows']
        if (controlActions.includes(intent.action)) {
          get().triggerPolicyUpdate()
        }
      }
    }

    set(s => ({
      intentHistory: s.intentHistory.map(r => r.id === updated.id ? updated : r),
    }))
  },

  // ─── 意图提交 ──────────────────────────────
  submitIntent: async (text) => {
    if (get().isProcessing) return
    set({ isProcessing: true })
    try {
      const resp = await api.post('/intent/process', { text })
      const { intent_id } = resp.data
      set(s => {
        // 如果 WebSocket 已经推送了该 ID，则不重复添加
        if (s.intentHistory.some(r => r.id === intent_id)) return s
        return {
          intentHistory: [{
            id: intent_id,
            user_text: text,
            status: 'pending',
            created_at: Date.now() / 1000,
          }, ...s.intentHistory].slice(0, 30),
        }
      })
    } catch (e) {
      set(s => ({
        intentHistory: [{
          id: `err_${Date.now()}`,
          user_text: text,
          status: 'failed',
          error_message: e.response?.data?.detail || e.message,
          created_at: Date.now() / 1000,
        }, ...s.intentHistory],
      }))
    } finally {
      set({ isProcessing: false })
    }
  },

  // ─── 初始数据加载 ──────────────────────────
  fetchInitialData: async () => {
    try {
      const [topoResp, statusResp, historyResp] = await Promise.all([
        api.get('/topology'),
        api.get('/health'),
        api.get('/intent/records').catch(() => ({ data: [] })),
      ])
      set({
        topology: topoResp.data,
        networkStatus: statusResp.data,
        intentHistory: historyResp.data || [],
      })
    } catch (e) {
      console.warn('初始数据加载失败:', e.message)
    } finally {
      set({ isInitialLoading: false })
    }
  },

  // ─── 刷新拓扑 ──────────────────────────────
  refreshTopology: async () => {
    try {
      const resp = await api.post('/topology/refresh')
      set({ topology: resp.data })
    } catch (e) {
      console.warn('刷新拓扑失败:', e.message)
    }
  },
})))

export default useStore
