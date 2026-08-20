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
import Logs from './views/Logs.jsx'

const NAV = [
  { id: 'dash', label: 'Status', icon: 'dash' },
  { id: 'chat', label: 'Chat', icon: 'chat' },
  { id: 'mcp', label: 'MCP', icon: 'plug' },
  { id: 'skills', label: 'Skills', icon: 'book' },
  { id: 'logs', label: 'Logs', icon: 'logs' },
]

const VIEWS = { dash: Dashboard, chat: Chat, mcp: Mcp, skills: Skills, logs: Logs }

function Rail() {
  const { view, setView, health, healthError, refreshHealth } = useApp()
  const online = health !== null
  const led = healthError ? 'bad' : online ? 'ok' : 'faint'
  const label = healthError
    ? 'api offline'
    : online
      ? `api ok · ${health.providers?.length ?? 0} provider${(health.providers?.length ?? 0) === 1 ? '' : 's'}`
      : 'api offline'

  return (
    <aside className="rail">
      <div className="rail-brand">
        <div className="rail-brand-mark">
          <Icon name="cpu" size={17} />
        </div>
        <div>
          <div className="rail-brand-name">PSOK</div>
          <div className="rail-brand-sub">personal os</div>
        </div>
      </div>
      <nav className="rail-nav">
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`rail-item${view === item.id ? ' active' : ''}`}
            onClick={() => setView(item.id)}
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="rail-foot">
        <span className={`led led--${led}`} />
        <span>{label}</span>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          style={{ marginLeft: 'auto', padding: '2px 6px' }}
          onClick={refreshHealth}
          title="Refresh status"
        >
          <Icon name="refresh" size={13} />
        </button>
      </div>
    </aside>
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

  const Active = VIEWS[view] || Dashboard

  useGSAP(
    () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      const el = mainRef.current
      gsap.set(el, { autoAlpha: 0, y: 10 })
      gsap.to(el, { autoAlpha: 1, y: 0, duration: 0.28, ease: 'power2.out' })
    },
    { scope: mainRef, dependencies: [view] },
  )

  useEffect(() => {
    document.title = 'PSOK · personal operating system'
  }, [])

  return (
    <div className="shell">
      <Rail />
      <main className="main" ref={mainRef} key={view}>
        <Active />
      </main>
      <Toasts />
    </div>
  )
}