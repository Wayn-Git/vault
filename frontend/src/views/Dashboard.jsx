import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api } from '../api.js'
import Skeleton from '../components/Skeleton.jsx'

/* What this machine is actually doing, read from `/api/health`.

   Every line here has to come from the response. It used to carry
   `guards armed (12 iterations, 40 tool calls)` as a literal string — true on
   the day it was typed, invisible the day someone changed `Guards` in
   `backend/agent/director.py`, and indistinguishable from the lines around it
   that were genuinely measured. A status page that prints one number it did not
   check is a status page you cannot trust about the others. */

const MODULES = [
  { id: 'chat', icon: 'chat', name: 'Agent chat', desc: 'Streaming turns, tool calls, permission prompts', meta: 'reason → act → observe' },
  { id: 'capabilities', icon: 'grid', name: 'Skills and connectors', desc: 'Catalogue, custom servers, OAuth logins, markdown skills', meta: 'flat tool namespace' },
  { id: 'memory', icon: 'spark', name: 'Memory', desc: 'Standing facts recalled across conversations', meta: 'extracted after a turn' },
  { id: 'logs', icon: 'logs', name: 'Audit log', desc: 'Every tool call, with the decision that allowed it', meta: 'redacted, immutable trail' },
]

function Line({ tag, tagClass = 't-tag', text }) {
  return (
    <div className="tele-line">
      <span className={tagClass}>{tag.padEnd(5, ' ')}</span> {text}
    </div>
  )
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

export default function Dashboard() {
  const rootRef = useRef(null)
  const { health, healthError, refreshHealth, setView, setCapabilitiesTab } = useApp()
  const [memory, setMemory] = useState(null)
  useViewEntrance(rootRef)

  const loadMemory = useCallback(async () => {
    try { setMemory(await api.memory()) } catch { setMemory(null) }
  }, [])

  useEffect(() => { loadMemory() }, [loadMemory])

  const awaiting = health?.connectors_awaiting_sign_in ?? []
  const broken = Object.entries(health?.connector_errors ?? {})
    .filter(([name]) => !awaiting.includes(name))
  const unavailable = Object.entries(health?.providers_unavailable ?? {})
  const tiers = Object.entries(health?.tiers ?? {})

  const lines = health
    ? [
        { tag: 'boot', text: 'PSOK — personal operating system' },
        { tag: 'ok', tagClass: 't-tag-ok', text: 'kernel: sqlite3 + FTS5 · secrets in the OS keychain' },
        {
          tag: unavailable.length ? 'warn' : 'ok',
          tagClass: unavailable.length ? 't-tag-bad' : 't-tag-ok',
          text: unavailable.length
            ? `providers: ${health.providers.join(', ')} — ${unavailable.map(([n, why]) => `${n} (${String(why).slice(0, 48)})`).join(', ')}`
            : `providers: ${health.providers.join(', ')}`,
        },
        {
          tag: 'tools',
          tagClass: 't-tag-ok',
          text: `${plural(health.tools, 'tool')} registered · ${plural(health.skills, 'skill')}`
            + (health.skill_errors ? ` · ${plural(health.skill_errors, 'skill failed to load', 'skills failed to load')}` : ''),
        },
        // `mcp_reconciled` is the difference between "not running" and "nothing
        // has asked it to run yet". Without it a server that has had no turn
        // reports every connector as broken, and none of them is.
        {
          tag: 'mcp',
          tagClass: broken.length ? 't-tag-bad' : health.mcp_reconciled ? 't-tag' : 't-tag',
          text: broken.length
            ? `connectors down: ${broken.map(([n, e]) => `${n} (${String(e).slice(0, 56)})`).join(' · ')}`
            : health.mcp_reconciled
              ? `${plural(health.mcp_tools ?? 0, 'connector tool')} live`
                + (awaiting.length ? ` · awaiting sign-in: ${awaiting.join(', ')}` : '')
              : 'connectors have not been started yet — the first turn starts them',
        },
        {
          tag: 'mem',
          tagClass: memory?.enabled ? 't-tag-ok' : 't-tag',
          text: memory
            ? `memory ${memory.enabled ? 'on' : 'off'} · ${plural(memory.facts.length, 'fact')} held`
            : 'memory: unavailable',
        },
        {
          tag: health.status === 'degraded' ? 'warn' : 'ok',
          tagClass: health.status === 'degraded' ? 't-tag-bad' : 't-tag-ok',
          text: `status: ${health.status === 'degraded' ? 'degraded — see connectors above' : 'nominal'}`,
        },
      ]
    : [
        { tag: 'boot', text: 'PSOK — personal operating system' },
        healthError
          ? { tag: 'err', tagClass: 't-tag-bad', text: `api unreachable: ${healthError}` }
          : { tag: 'wait', text: 'awaiting backend…' },
      ]

  const counters = [
    { key: 'providers', label: 'providers', count: health?.providers?.length ?? 0, sub: unavailable.length ? `${unavailable.length} not answering` : 'all answering' },
    { key: 'tools', label: 'tools', count: health?.tools ?? 0, sub: `${health?.mcp_tools ?? 0} from connectors` },
    { key: 'skills', label: 'skills', count: health?.skills ?? 0, sub: health?.skill_errors ? `${health.skill_errors} failed to load` : 'markdown, discovered' },
    { key: 'memory', label: 'memories', count: memory?.facts?.length ?? 0, sub: memory?.enabled === false ? 'switched off' : 'recalled every turn' },
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
                {/* A zero the page has not verified is a lie that looks like
                    a fact. Until health has answered, say nothing. */}
                <div className="stat-num">{health ? s.count : <Skeleton w={52} h={26} r={8} />}</div>
                <div className="stat-label">{s.label}</div>
                <div className="stat-sub">
                  {s.sub}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Which model does which job. The server has published this since
            escalation shipped and nothing read it, so the one place that could
            answer "what will Reasoning mode actually cost me" never did. */}
        {tiers.length > 0 && (
          <div className="card card-pad dash-tiers" data-enter>
            <div className="card-title">model tiers</div>
            <p className="set-note" style={{ marginTop: 0 }}>
              What each job runs on. The composer’s Reasoning mode, and the escalation the
              fast model asks for, both land on the heavy tier.
            </p>
            <div className="set-rows">
              {tiers.map(([name, tier]) => (
                <div className="set-row" key={name}>
                  <span>
                    {name}
                    <span className="set-sub">{tier.provider}</span>
                  </span>
                  <span className="set-row-tail mono">{tier.model}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Only when there is something to act on. A permanent "everything is
            fine" panel is a panel people stop reading. */}
        {(broken.length > 0 || awaiting.length > 0) && (
          <div className="card card-pad" data-enter style={{ marginTop: 18 }}>
            <div className="card-title">needs attention</div>
            <div className="set-rows">
              {broken.map(([name, err]) => (
                <div className="set-row" key={name}>
                  <span>
                    {name}
                    <span className="set-sub">{String(err).slice(0, 140)}</span>
                  </span>
                  <span className="set-row-tail">
                    <button
                      type="button"
                      className="btn btn--ghost btn--small"
                      onClick={() => { setCapabilitiesTab('connectors'); setView('capabilities') }}
                    >
                      Open
                    </button>
                  </span>
                </div>
              ))}
              {awaiting.map((name) => (
                <div className="set-row" key={name}>
                  <span>
                    {name}
                    <span className="set-sub">switched on, not signed in</span>
                  </span>
                  <span className="set-row-tail">
                    <button
                      type="button"
                      className="btn btn--ghost btn--small"
                      onClick={() => { setCapabilitiesTab('connectors'); setView('capabilities') }}
                    >
                      Sign in
                    </button>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

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
