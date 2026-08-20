import { useEffect, useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import Icon from './components/Icon.jsx'
import { useApp } from './store.jsx'
import { useMotionToggler } from './gsapFx.js'
import Dashboard from './views/Dashboard.jsx'
import Chat from './views/Chat.jsx'
import Mcp from './views/Mcp.jsx'
import Skills from './views/Skills.jsx'
import Memory from './views/Memory.jsx'
import Logs from './views/Logs.jsx'

const NAV = [
  { id: 'chat', label: 'Chat' },
  { id: 'mcp', label: 'Connectors' },
  { id: 'skills', label: 'Skills' },
  { id: 'memory', label: 'Memory' },
  { id: 'logs', label: 'Activity' },
  { id: 'dash', label: 'Status' },
]

const VIEWS = { dash: Dashboard, chat: Chat, mcp: Mcp, skills: Skills, memory: Memory, logs: Logs }

function Topbar() {
  const { view, setView, health, healthError } = useApp()
  const degraded = health?.status === 'degraded'
  const led = healthError ? 'bad' : health ? (degraded ? 'amber' : 'ok') : 'faint'
  const label = healthError
    ? 'offline'
    : health
      ? degraded ? 'degraded' : `${health.tools} tools`
      : 'connecting'

  return (
    <header className="topbar">
      <button type="button" className="brand" onClick={() => setView('chat')}>
        <span className="brand-mark"><Icon name="cpu" size={20} /></span>
        <span className="brand-name">PSOK</span>
        <span className="brand-sub">personal os</span>
      </button>
      <nav className="topnav">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`topnav-item${view === item.id ? ' active' : ''}`}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className="topbar-status">
        <span className={`led led--${led}${led === 'ok' ? '' : ' led--pulse'}`} />
        {label}
      </div>
    </header>
  )
}

function Toasts() {
  const { toasts } = useApp()
  return (
    <div className="toast-wrap">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          <span className={`led led--${t.tone === 'bad' ? 'bad' : t.tone === 'ok' ? 'ok' : 'amber'}`} />
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { view } = useApp()
  const mainRef = useRef(null)
  useMotionToggler()

  const Active = VIEWS[view] || Chat

  useGSAP(
    () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      const el = mainRef.current
      gsap.set(el, { autoAlpha: 0, y: 8 })
      gsap.to(el, { autoAlpha: 1, y: 0, duration: 0.5, ease: 'expo.out' })
    },
    { scope: mainRef, dependencies: [view] },
  )

  useEffect(() => {
    document.title = 'PSOK · personal operating system'
  }, [])

  return (
    <div className="shell">
      <Topbar />
      <main className="main" ref={mainRef} key={view}>
        <Active />
      </main>
      <Toasts />
    </div>
  )
}
