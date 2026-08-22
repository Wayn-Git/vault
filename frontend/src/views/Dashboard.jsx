import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api } from '../api.js'

const MODULES = [
  { id: 'chat', icon: 'chat', name: 'Agent chat', desc: 'Streaming turns, tool calls, permission prompts', meta: 'reason → act → observe' },
  { id: 'capabilities', icon: 'grid', name: 'Skills and connectors', desc: 'Catalogue, custom servers, OAuth logins, markdown skills', meta: 'flat tool namespace' },
  { id: 'memory', icon: 'spark', name: 'Memory', desc: 'Standing facts recalled across conversations', meta: 'extracted after a turn' },
  { id: 'logs', icon: 'logs', name: 'Audit log', desc: 'Every tool call, with the decision that allowed it', meta: 'redacted, immutable trail' },
]

function Line({ tag, tagClass = 't-tag', text }) {
  return (
    <div className="tele-line">
      <span className={tagClass}>{tag.padEnd(5, '\u00a0')}</span> {text}
    </div>
  )
}

export default function Dashboard() {
  const rootRef = useRef(null)
  const { health, healthError, refreshHealth, setView } = useApp()
  const [memory, setMemory] = useState(null)
  useViewEntrance(rootRef)

  const loadMemory = useCallback(async () => {
    try { setMemory(await api.memory()) } catch { setMemory(null) }
  }, [])

  useEffect(() => { loadMemory() }, [loadMemory])

  const lines = health
    ? [
        { tag: 'boot', text: 'PSOK v0.1.0 — personal operating system' },
        { tag: 'ok', tagClass: 't-tag-ok', text: 'kernel: sqlite3 + FTS5 · keychain secrets' },
        { tag: 'ok', tagClass: 't-tag-ok', text: `providers: ${health.providers.join(', ')}` },
        { tag: 'ok', tagClass: 't-tag-ok', text: `${health.tools} tools registered · ${health.skills} skills · ${health.skill_errors} skill errors` },
        { tag: 'agent', text: 'loop online · guards armed (12 iterations, 40 tool calls)' },
        {
          tag: 'mcp',
          tagClass: Object.keys(health.connector_errors ?? {}).length ? 't-tag-bad' : 't-tag',
          text: Object.keys(health.connector_errors ?? {}).length
            ? `connectors down: ${Object.entries(health.connector_errors).map(([n, e]) => `${n} (${String(e).slice(0, 60)})`).join(' · ')}`
            : `${health.mcp_tools ?? 0} connector tools live · switch servers on in MCP`,
        },
        {
          tag: 'mem',
          tagClass: memory?.enabled ? 't-tag-ok' : 't-tag',
          text: memory
            ? `memory ${memory.enabled ? 'on' : 'off'} · ${memory.facts.length} fact${memory.facts.length === 1 ? '' : 's'} held`
            : 'memory: unavailable',
        },
        {
          tag: health.status === 'degraded' ? 'warn' : 'ok',
          tagClass: health.status === 'degraded' ? 't-tag-bad' : 't-tag-ok',
          text: `status: ${health.status === 'degraded' ? 'degraded — see connectors above' : 'nominal'}`,
          typing: true,
        },
      ]
    : [
        { tag: 'boot', text: 'PSOK v0.1.0 — personal operating system' },
        healthError
          ? { tag: 'err', tagClass: 't-tag-bad', text: `api unreachable: ${healthError}` }
          : { tag: 'wait', text: 'awaiting backend…' },
      ]

  const counters = [
    { key: 'providers', label: 'providers', count: health?.providers?.length ?? 0, sub: 'configured in providers.yaml' },
    { key: 'tools', label: 'tools', count: health?.tools ?? 0, sub: `${health?.mcp_tools ?? 0} from connectors` },
    { key: 'skills', label: 'skills', count: health?.skills ?? 0, sub: health?.skill_errors ? `${health.skill_errors} failed to load` : 'markdown, discovered' },
    { key: 'memory', label: 'memories', count: memory?.facts?.length ?? 0, sub: memory?.enabled === false ? 'switched off' : 'recalled every turn', bad: memory?.enabled === false },
  ]

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <h1>Everything, on one machine</h1>
            <div className="vheader-sub">
              One agent over your files, shell, tasks, calendar and connected services.
              Your data stays in a SQLite file here; your secrets stay in the keychain.
            </div>
          </div>
          <div className="vheader-actions">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={() => { refreshHealth(); loadMemory() }}
            >
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        <div className="dash-grid">
          <div data-enter>
            <div className="tele">
              <div className="tele-bar">
                system
                <span style={{ marginLeft: 'auto' }}>live</span>
              </div>
              <div className="tele-body">
                {lines.map((l, i) => <Line key={i} {...l} />)}
              </div>
            </div>
          </div>

          <div className="stat-grid" data-enter>
            {counters.map((s) => (
              <div className="stat" key={s.key}>
                <div className="stat-num">{s.count}</div>
                <div className="stat-label">{s.label}</div>
                <div className="stat-sub">
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