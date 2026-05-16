import { useEffect, useRef } from 'react'
import useStore from '../store/useStore'

export function useWebSocket() {
  const wsRef = useRef(null)
  const { setTopology, addAlert, updateIntentRecord, setWsConnected } = useStore()

  useEffect(() => {
    let reconnectTimer = null

    function connect() {
      const ws = new WebSocket('ws://localhost:8000/ws')
      wsRef.current = ws

      ws.onopen = () => {
        setWsConnected(true)
        console.log('[WS] 已连接')
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          switch (msg.type) {
            case 'topology_update':
              setTopology(msg.data)
              break
            case 'alert':
              addAlert(msg.data)
              break
            case 'intent_update':
              updateIntentRecord(msg.data)
              break
            default:
              break
          }
        } catch (err) {
          console.warn('[WS] 消息解析失败:', err)
        }
      }

      ws.onclose = () => {
        setWsConnected(false)
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
