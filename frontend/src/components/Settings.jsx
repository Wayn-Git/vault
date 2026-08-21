import { useCallback, useEffect, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'
import { useApp } from '../store.jsx'
import { connectorState } from './PlusMenu.jsx'

/* One place for everything that is a setting rather than a conversation.

   The full views still exist and do more; these panels are the short version,
   reachable without leaving the chat you are in. */

const SECTIONS = [
  { id: 'general', label: 'General', icon: 'sliders', group: 'Settings' },
  { id: 'models', label: 'Models', icon: 'cpu', group: 'Settings' },
  { id: 'permissions', label: 'Permissions', icon: 'key', group: 'Settings' },
  { id: 'skills', label: 'Skills', icon: 'book', group: 'Customise' },
  { id: 'connectors', label: 'Connectors', icon: 'plug', group: 'Customise' },
  { id: 'memory', label: 'Memory', icon: 'spark', group: 'Customise' },
]

function General() {
  const { health, healthError, workspace, setWorkspace, setView, setOverlay } = useApp()
  const [draft, setDraft] = useState(workspace || '')

  return (
    <div className="set-panel">
      <h3>This machine</h3>
      <div className="set-rows">
        <div className="set-row">
          <span>API</span>
          <span className={healthError ? 'set-bad' : 'set-ok'}>
            {healthError ? healthError : `reachable · ${health?.status ?? 'unknown'}`}
          </span>
        </div>
        <div className="set-row">
          <span>Tools</span><span>{health?.tools ?? '—'} builtin + connected</span>
        </div>
        <div className="set-row">
          <span>Skills</span>
          <span>{health?.skills ?? '—'} installed{health?.skill_errors ? `, ${health.skill_errors} broken` : ''}</span>
        </div>
        <div className="set-row">
          <span>Connector tools</span><span>{health?.mcp_tools ?? 0} live</span>
        </div>
      </div>

      <h3>Working directory</h3>
      <p className="set-note">
        File and shell tools are confined here. Empty means the directory the API was started in.
      </p>
      <div className="set-inline">
        <input value={draft} placeholder="~/notes" onChange={(e) => setDraft(e.target.value)} />
        <button type="button" className="btn btn--primary btn--small" onClick={() => setWorkspace(draft.trim())}>
          Save
        </button>
      </div>

      <h3>Elsewhere</h3>
      <div className="set-links">
        <button type="button" className="btn btn--ghost btn--small" onClick={() => { setView('logs'); setOverlay(null) }}>
          <Icon name="logs" size={13} /> Activity log
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => { setView('tasks'); setOverlay(null) }}>
          <Icon name="check" size={13} /> Tasks and calendar
        </button>
      </div>
    </div>
  )
}

function Models() {
  const { health, conversations, activeId, refreshConvs, toast } = useApp()
  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}
  const active = conversations.find((c) => c.id === activeId)

  const apply = async (patch) => {
    if (!activeId) return
    try {
      await api.updateConversation(activeId, patch)
      refreshConvs()
      toast('Model changed for this conversation', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }

  return (
    <div className="set-panel">
      <h3>Providers</h3>
      <p className="set-note">
        Configured in <span className="mono">~/.psok/config/providers.yaml</span>. Keys live in the OS
        keychain; the file holds only a reference.
      </p>
      <div className="set-rows">
        {providers.length === 0 && <div className="set-row"><span>none configured</span></div>}
        {providers.map((name) => (
          <div className="set-row" key={name}>
            <span>{name}</span>
            <span className="mono">{defaults[name] || 'no default model'}</span>
          </div>
        ))}
      </div>

      {active && (
        <>
          <h3>This conversation</h3>
          <div className="set-inline">
            <select value={active.provider} onChange={(e) => apply({ provider: e.target.value, model: defaults[e.target.value] || active.model })}>
              {providers.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
            <input
              key={active.model}
              defaultValue={active.model}
              onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
              onBlur={(e) => { if (e.target.value.trim() && e.target.value !== active.model) apply({ model: e.target.value.trim() }) }}
            />
          </div>
          <p className="set-note">The adapter is resolved fresh every turn, so this takes effect immediately.</p>
        </>
      )}
    </div>
  )
}

function Permissions() {
  const { toast } = useApp()
  const [rows, setRows] = useState([])

  const load = useCallback(async () => {
    try { setRows(await api.standingApprovals()) } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

  return (
    <div className="set-panel">
      <h3>Runs without asking</h3>
      <p className="set-note">
        Kept by operation key rather than tool name — approving a read-only shell command never
        approved a destructive one.
      </p>
      {rows.length === 0 && <div className="set-empty">Nothing is approved in advance. Every gated call asks.</div>}
      <div className="set-rows">
        {rows.map((row) => (
          <div className="set-row" key={row.operation_key}>
            <span className="mono">{row.operation_key}</span>
            <span className="set-row-tail">
              <span className="badge">{row.risk_level}</span>
              <button
                type="button"
                className="btn btn--ghost btn--small"
                onClick={async () => {
                  try {
                    await api.revokeApproval(row.operation_key)
                    toast(`${row.operation_key} will ask again`, 'ok')
                    load()
                  } catch (err) { toast(err.message, 'bad') }
                }}
              >
                Revoke
              </button>
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function Skills() {
  const { caps, setCapEnabled, busyCap, setOverlay, setView } = useApp()
  const skills = caps.skills ?? []
  return (
    <div className="set-panel">
      <h3>Skills</h3>
      <p className="set-note">
        An engaged skill is offered to the agent every turn; <span className="mono">/name</span> engages
        one for a single message.
      </p>
      <div className="set-rows">
        {skills.length === 0 && <div className="set-empty">Nothing installed.</div>}
        {skills.map((skill) => (
          <div className="set-row" key={skill.name}>
            <span>
              /{skill.name}
              <span className="set-sub">{skill.description}</span>
            </span>
            <button
              type="button"
              className={`btn btn--small${skill.enabled ? ' btn--primary' : ' btn--ghost'}`}
              disabled={busyCap === `skill:${skill.name}`}
              onClick={() => setCapEnabled(skill, !skill.enabled)}
            >
              {skill.enabled ? 'On' : 'Off'}
            </button>
          </div>
        ))}
      </div>
      <div className="set-links">
        <button type="button" className="btn btn--small" onClick={() => setOverlay('directory:skills')}>
          <Icon name="plus" size={13} /> Browse and install
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => { setView('skills'); setOverlay(null) }}>
          Open the full view
        </button>
      </div>
    </div>
  )
}

function Connectors() {
  const { caps, setCapEnabled, busyCap, setOverlay, setView, toast } = useApp()
  const [servers, setServers] = useState([])

  const load = useCallback(async () => {
    try { setServers(await api.mcpServers()) } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

  const connectors = caps.connectors ?? []

  return (
    <div className="set-panel">
      <h3>Connectors</h3>
      <table className="set-table">
        <thead>
          <tr><th>Connector</th><th>Type</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {servers.length === 0 && (
            <tr><td colSpan={4} className="set-empty">Nothing configured yet.</td></tr>
          )}
          {servers.map((server) => {
            const cap = connectors.find((c) => c.name === server.name)
            const state = cap ? connectorState(cap, busyCap === `connector:${server.name}`) : null
            return (
              <tr key={server.name}>
                <td>{server.name}</td>
                <td className="mono">{server.transport}</td>
                <td>
                  <span className={`led led--${state?.dot ?? 'faint'}`} />
                  {server.oauth && server.authorized === false ? 'needs sign-in' : state?.label ?? 'off'}
                </td>
                <td className="set-table-actions"><div className="set-table-actions-inner">
                  {server.oauth && server.authorized === false && (
                    <button
                      type="button"
                      className="btn btn--small"
                      onClick={() => { setView('mcp'); setOverlay(null) }}
                    >
                      Sign in
                    </button>
                  )}
                  {cap && (
                    <button
                      type="button"
                      className={`btn btn--small${cap.enabled ? ' btn--primary' : ' btn--ghost'}`}
                      disabled={busyCap === `connector:${server.name}`}
                      onClick={() => setCapEnabled(cap, !cap.enabled)}
                    >
                      {cap.enabled ? 'Disconnect' : 'Connect'}
                    </button>
                  )}
                </div></td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <div className="set-links">
        <button type="button" className="btn btn--small" onClick={() => setOverlay('directory:connectors')}>
          <Icon name="plus" size={13} /> Add connector
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => { setView('mcp'); setOverlay(null) }}>
          Open the full view
        </button>
      </div>
    </div>
  )
}

function Memory() {
  const { toast, setView, setOverlay } = useApp()
  const [state, setState] = useState(null)

  const load = useCallback(async () => {
    try { setState(await api.memory()) } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

  return (
    <div className="set-panel">
      <h3>Memory</h3>
      <p className="set-note">
        Standing facts, extracted after a turn and recalled in later conversations. Forgetting one
        retires it: what PSOK believed, and when that changed, stays answerable.
      </p>
      <div className="set-inline">
        <button
          type="button"
          className={`btn btn--small${state?.enabled ? ' btn--primary' : ' btn--ghost'}`}
          disabled={!state}
          onClick={async () => {
            const next = await api.toggleMemory(!state.enabled)
            setState((s) => ({ ...s, enabled: next.enabled }))
          }}
        >
          {state?.enabled ? 'Remembering' : 'Not remembering'}
        </button>
        <span className="set-note" style={{ margin: 0 }}>{state?.facts?.length ?? 0} facts held</span>
      </div>
      <div className="set-rows">
        {(state?.facts ?? []).slice(0, 6).map((fact) => (
          <div className="set-row" key={fact.id}><span>{fact.fact}</span></div>
        ))}
      </div>
      <div className="set-links">
        <button type="button" className="btn btn--ghost btn--small" onClick={() => { setView('memory'); setOverlay(null) }}>
          Open the full view
        </button>
      </div>
    </div>
  )
}

const PANELS = {
  general: General,
  models: Models,
  permissions: Permissions,
  skills: Skills,
  connectors: Connectors,
  memory: Memory,
}

export default function Settings() {
  const { overlay, setOverlay } = useApp()
  const [section, setSection] = useState('general')
  const open = overlay === 'settings'

  useEffect(() => {
    if (!open) return undefined
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOverlay(null) } }
    document.addEventListener('keydown', key, true)
    return () => document.removeEventListener('keydown', key, true)
  }, [open, setOverlay])

  if (!open) return null
  const Panel = PANELS[section] || General
  let lastGroup = null

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOverlay(null) }}>
      <div className="settings" role="dialog" aria-modal="true" aria-label="Settings">
        <nav className="set-nav">
          {SECTIONS.map((item) => {
            const header = item.group !== lastGroup ? item.group : null
            lastGroup = item.group
            return (
              <div key={item.id}>
                {header && <div className="set-nav-group">{header}</div>}
                <button
                  type="button"
                  className={`set-nav-item${section === item.id ? ' active' : ''}`}
                  onClick={() => setSection(item.id)}
                >
                  <Icon name={item.icon} size={15} /> {item.label}
                </button>
              </div>
            )
          })}
        </nav>
        <div className="set-content">
          <div className="set-head">
            <span className="set-title">{SECTIONS.find((s) => s.id === section)?.label}</span>
            <button type="button" className="icon-btn" onClick={() => setOverlay(null)} aria-label="Close">
              <Icon name="x" size={16} />
            </button>
          </div>
          <Panel />
        </div>
      </div>
    </div>
  )
}
