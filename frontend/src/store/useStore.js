import { create } from 'zustand'
import api from '../services/api'

const useStore = create((set, get) => ({
  // ─── 网络状态 ─────────────────────────
  topology: { nodes: [], links: [] },
  networkStatus: { vm_connected: false, node_count: 0, link_count: 0, active_alerts: 0 },
  alerts: [],
  wsConnected: false,

  // ─── 意图历史 ─────────────────────────
  intentHistory: [],
  isProcessing: false,

  // ─── Actions ──────────────────────────
  setTopology: (topology) => set({ topology }),
  setNetworkStatus: (networkStatus) => set({ networkStatus }),
  addAlert: (alert) => set((s) => ({ alerts: [alert, ...s.alerts].slice(0, 50) })),
  setAlerts: (alerts) => set({ alerts }),
  setWsConnected: (v) => set({ wsConnected: v }),

  addIntentRecord: (record) => set((s) => ({
    intentHistory: [record, ...s.intentHistory].slice(0, 30),
  })),
  updateIntentRecord: (updated) => set((s) => ({
    intentHistory: s.intentHistory.map((r) => r.id === updated.id ? updated : r),
  })),

  submitIntent: async (text) => {
    if (get().isProcessing) return
    set({ isProcessing: true })
    try {
      const resp = await api.post('/intent/process', { text })
      const { intent_id } = resp.data
      // 插入 pending 记录，后续由 WebSocket 更新
      set((s) => ({
        intentHistory: [{
          id: intent_id,
          user_text: text,
          status: 'pending',
          created_at: Date.now() / 1000,
        }, ...s.intentHistory].slice(0, 30),
      }))
    } catch (e) {
      set((s) => ({
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

  confirmIntent: async (intentId) => {
    try {
      await api.post(`/intent/confirm/${intentId}`)
    } catch (e) {
      console.error('confirm error:', e)
    }
  },

  fetchInitialData: async () => {
    try {
      const [topoResp, statusResp, alertsResp] = await Promise.all([
        api.get('/topology'),
        api.get('/network/status'),
        api.get('/alerts'),
      ])
      set({
        topology: topoResp.data,
        networkStatus: statusResp.data,
        alerts: alertsResp.data.alerts || [],
      })
    } catch (e) {
      console.warn('初始数据加载失败:', e.message)
    }
  },

  refreshTopology: async () => {
    try {
      const resp = await api.post('/topology/refresh')
      set({ topology: resp.data })
    } catch (e) {
      console.warn('刷新拓扑失败:', e.message)
    }
  },
}))

export default useStore
