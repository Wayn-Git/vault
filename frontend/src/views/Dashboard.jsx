import { useRef } from 'react'
import { useGSAP } from '@gsap/react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { animateCounter, useViewEntrance } from '../gsapFx.js'

const MODULES = [
  { id: 'chat', icon: 'chat', name: 'Agent chat', desc: 'Streaming turns, tool calls, permission prompts', meta: 'reason → act → observe' },
  { id: 'mcp', icon: 'plug', name: 'MCP servers', desc: 'Catalogue, custom servers, OAuth logins', meta: 'flat tool namespace' },
  { id: 'skills', icon: 'book', name: 'Skills', desc: 'Markdown skill discovery', meta: 'progressive disclosure' },
  { id: 'logs', icon: 'logs', name: 'Audit log', desc: 'Every tool call, with the decision that allowed it', meta: 'redacted, immutable trail' },
]

function BootLine({ time, tag, tagClass = 't-tag', text, typing = false }) {
  return (
    <div className="tele-line" data-enter>
      <span className="t-time">[{time}]</span> <span className={tagClass}>{tag}</span> {text}
      {typing && <span className="tele-cursor" />}
    </div>
  )
}

export default function Dashboard() {
  const rootRef = useRef(null)
  const { health, healthError, refreshHealth, setView } = useApp()
  const numRefs = useRef({})
  useViewEntrance(rootRef)

  useGSAP(
    () => {
      const counters = Object.entries(numRefs.current)
      if (!counters.length || !health) return
      counters.forEach(([, el]) => {
        const target = Number(el.dataset.count || 0)
        animateCounter(el, target, 0.9)
      })
    },
    { scope: rootRef, dependencies: [health] },
  )

  const lines = health
    ? [
        { tag: 'boot', text: 'PSOK v0.1.0 — personal operating system' },
        { tag: 'ok', tagClass: 't-tag-ok', text: 'kernel: sqlite3 + FTS5 · keychain secrets' },
        { tag: 'ok', tagClass: 't-tag-ok', text: `providers: ${health.providers.join(', ')}` },
        { tag: 'ok', tagClass: 't-tag-ok', text: `${health.tools} tools registered · ${health.skills} skills · ${health.skill_errors} skill errors` },
        { tag: 'agent', text: 'loop online · guards armed (12 iterations, 40 tool calls)' },
        { tag: 'mcp', text: 'servers: per mcp.yaml · connect from MCP module' },
        { tag: 'ok', tagClass: 't-tag-ok', text: 'status: nominal', typing: true },
      ]
    : [
        { tag: 'boot', text: 'PSOK v0.1.0 — personal operating system' },
        healthError
          ? { tag: 'err', tagClass: 't-tag-bad', text: `api unreachable: ${healthError}` }
          : { tag: 'wait', text: 'awaiting backend…', typing: true },
      ]

  const counters = [
    { key: 'providers', label: 'providers', count: health?.providers?.length ?? 0, sub: 'configured in providers.yaml' },
    { key: 'tools', label: 'tools', count: health?.tools ?? 0, sub: 'flat namespace, gated' },
    { key: 'skills', label: 'skills', count: health?.skills ?? 0, sub: 'markdown, discovered' },
    { key: 'errors', label: 'skill errors', count: health?.skill_errors ?? 0, sub: health?.skill_errors ? 'fix frontmatter' : 'none' },
  ]

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <div className="vheader-eyebrow">
              <span className="led led--amber led--pulse" /> sys / status
            </div>
            <h1>Your personal operating system</h1>
            <div className="vheader-sub">
              One agent over your files, shell, tasks, calendar and connected services. Local-first, single-user.
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--ghost" onClick={refreshHealth}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        <div className="dash-grid">
          <div data-enter>
            <div className="tele">
              <div className="tele-bar">
                <span className="led led--amber led--pulse" />
                boot sequence
                <span style={{ marginLeft: 'auto' }}>tty0</span>
              </div>
              <div className="tele-body">
                {lines.map((l, i) => (
                  <BootLine key={i} time={String(i).padStart(2, '0') + ':00.000'} {...l} />
                ))}
              </div>
            </div>
          </div>

          <div className="stat-grid" data-enter>
            {counters.map((s) => (
              <div className="stat" key={s.key}>
                <div className="stat-num" ref={(el) => { numRefs.current[s.key] = el }} data-count={s.count}>
                  0
                </div>
                <div className="stat-label">{s.label}</div>
                <div className="stat-sub">
                  <span className={`led led--${s.key === 'errors' && s.count ? 'bad' : 'ok'}`} />
                  {s.sub}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="dash-modules">
          {MODULES.map((m) => (
            <button key={m.id} type="button" className="module-row" data-enter onClick={() => setView(m.id)}>
              <div className="module-icon">
                <Icon name={m.icon} size={19} />
              </div>
              <div>
                <div className="module-name">{m.name}</div>
                <div className="module-desc">{m.desc}</div>
              </div>
              <div className="module-meta">{m.meta}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}