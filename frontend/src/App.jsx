import { useEffect } from 'react'
import useStore from './store/useStore'
import { useWebSocket } from './services/useWebSocket'
import NetworkTopology from './components/NetworkTopology/NetworkTopology'
import NetworkInfo from './components/NetworkInfo/NetworkInfo'
import IntentInput from './components/IntentInput/IntentInput'
import { RefreshCw, Globe2, Command } from 'lucide-react'

function Header() {
  const { wsConnected, networkStatus, refreshTopology } = useStore()
  const ryuOk = networkStatus.ryu_connected
  return (
    <header className="header">
      <div className="header-logo">
        <div className="logo-icon-wrapper">
          <Command size={18} strokeWidth={2.5} />
        </div>
        <span className="logo-text-main">IBN</span>
        <span className="logo-divider">/</span>
        <span className="logo-text-sub">Intent-Based Networking</span>
      </div>
      <div className="header-spacer" />
      <button
        className="btn btn-sm"
        onClick={refreshTopology}
        title="刷新拓扑"
      >
        <RefreshCw size={14} /> 刷新拓扑
      </button>
      <div className={`header-status ${ryuOk ? 'connected' : 'disconnected'}`}>
        <span className={`status-dot ${ryuOk ? 'live' : ''}`} />
        {ryuOk ? 'Ryu 已连接' : 'Ryu 未连接'}
      </div>
      <div className={`header-status ${wsConnected ? 'connected' : 'disconnected'}`}>
        <span className={`status-dot ${wsConnected ? 'live' : ''}`} />
        {wsConnected ? 'WebSocket 实时' : 'WebSocket 断开'}
      </div>
    </header>
  )
}

export default function App() {
  const fetchInitialData = useStore(s => s.fetchInitialData)
  useWebSocket()

  useEffect(() => {
    fetchInitialData()
  }, [])

  return (
    <div className="app-layout">
      <Header />

      {/* 左侧栏 — 网络信息（含 Tabs 和 Alerts）*/}
      <aside className="sidebar-left">
        <NetworkInfo />
      </aside>

      {/* 主区域 — 拓扑 */}
      <main className="main-area">
        <div className="topology-header">
          <div className="panel-header">
            <Globe2 size={18} className="text-muted" /> <span style={{ fontWeight: 600 }}>网络拓扑</span>
          </div>
          <div className="topology-actions">
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
              实时同步 · 每 5 秒刷新
            </span>
          </div>
        </div>
        <NetworkTopology />
      </main>

      {/* 右侧栏 — 意图 */}
      <aside className="sidebar-right">
        <IntentInput />
      </aside>
    </div>
  )
}
