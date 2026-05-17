import { useEffect, useRef } from 'react'
import useStore from '../store/useStore'

export function useWebSocket() {
  const wsRef = useRef(null)
  useEffect(() => {
    let reconnectTimer = null

    function connect() {
      const WS_BASE = import.meta.env.VITE_WS_BASE_URL || `ws://${window.location.hostname}:8000/ws`
      const ws = new WebSocket(WS_BASE)
      wsRef.current = ws

      ws.onopen = () => {
        useStore.getState().setWsConnected(true)
        console.log('[WS] 已连接')
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          const state = useStore.getState()
          switch (msg.type) {
            case 'topology_update':
              state.setTopology(msg.data)
              break
            case 'alert':
              state.addAlert(msg.data)
              break
            case 'intent_update':
              state.updateIntentRecord(msg.data)
              break
            default:
              break
          }
        } catch (err) {
          console.warn('[WS] 消息解析失败:', err)
        }
      }

      ws.onclose = () => {
        useStore.getState().setWsConnected(false)
        console.log('[WS] 连接断开，5s 后重连...')
        reconnectTimer = setTimeout(connect, 5000)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      wsRef.current?.close()
    }
  }, [])

  // 保持心跳
  useEffect(() => {
    const timer = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send('ping')
      }
    }, 30000)
    return () => clearInterval(timer)
  }, [])
}
