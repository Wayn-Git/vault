import { useCallback, useEffect, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'
import { useApp } from '../store.jsx'

/* Settings, and only settings.

   This used to carry a second, shorter Skills page, a second Connectors page
   and a second Memory page alongside the ones in the rail. Two implementations
   of one thing is two things to keep in step and one more place to look, and
   the short version was always the one missing whatever you had come for --
   the Connectors panel here could not finish an OAuth sign-in, so the answer
   to half of what it showed you was "open the full view".

   What is left is what has nowhere else to live. The pages themselves are
   listed below the settings, and picking one goes there rather than drawing a
   worse copy of it inside a dialog. */

const SECTIONS = [
  { id: 'general', label: 'General', icon: 'sliders' },
  { id: 'models', label: 'Models', icon: 'cpu' },
  { id: 'permissions', label: 'Permissions', icon: 'key' },
  { id: 'data', label: 'Data', icon: 'trash' },
]

// Every one of these is a full view in the rail. The nav links to them so that
// looking for skills in the settings finds them, rather than finding a smaller
// second copy.
const PAGES = [
  { id: 'capabilities', label: 'Skills & connectors', icon: 'grid' },
  { id: 'automations', label: 'Automations', icon: 'clock' },
  { id: 'memory', label: 'Memory', icon: 'spark' },
  { id: 'tasks', label: 'Tasks', icon: 'check' },
  { id: 'logs', label: 'Activity', icon: 'logs' },
]

function General() {
  const { health, healthError, workspace, setWorkspace } = useApp()
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

    </div>
  )
}

/* Add a provider, and store its key.
 *
 * This panel used to say "configured in ~/.psok/config/providers.yaml", which
 * is a strange thing for an interface to say about a file whose every field it
 * knows: the base URL, the model id and the page the key comes from are all in
 * the catalogue. So the form writes the entry rather than describing it.
 *
 * The key goes straight to the server and into the OS keychain. Nothing sends
 * one back, so a saved provider shows "key stored" and never the key -- the
 * same rule the connector credential form already holds to. */
function AddProviderForm({ preset, onDone, onCancel }) {
  const { toast } = useApp()
  const [model, setModel] = useState(preset?.default_model || '')
  const [baseUrl, setBaseUrl] = useState(preset?.base_url || '')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)

  const custom = !preset
  const needsKey = custom || !preset.local

  const save = async () => {
    setBusy(true)
    try {
      const result = await api.addProvider({
        name: preset ? preset.slug : (model && baseUrl ? nameFor(baseUrl) : ''),
        base_url: baseUrl.trim() || null,
        default_model: model.trim() || null,
        api_key: key.trim() ? key.trim() : null,
      })
      // Says what is still missing rather than claiming success: an entry with
      // no key is listed and not offered, and silence about that is how a
      // provider ends up in the picker and fails on the first round trip.
      if (result.needs_key) toast(`${result.name} added — it still needs a key`, 'amber')
      else if (result.needs_model) toast(`${result.name} added — pick a model for it`, 'amber')
      else toast(`${result.name} is ready`, 'ok')
      onDone()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="set-panel set-subpanel">
      <h3>{preset ? `Add ${preset.label}` : 'Add a provider'}</h3>
      {preset?.note && <p className="set-note">{preset.note}</p>}

      {custom && (
        <div className="field">
          <label htmlFor="prov-url">Base URL</label>
          <input
            id="prov-url"
            value={baseUrl}
            placeholder="http://localhost:8000/v1"
            onChange={(e) => setBaseUrl(e.target.value)}
          />
          <span className="hint">
            Any OpenAI-compatible endpoint works with no adapter — vLLM, LM Studio, a proxy.
          </span>
        </div>
      )}

      <div className="field">
        <label htmlFor="prov-model">Model</label>
        <input
          id="prov-model"
          value={model}
          placeholder={preset?.default_model || 'model id'}
          onChange={(e) => setModel(e.target.value)}
        />
        {preset?.docs_url && (
          <span className="hint">
            <a href={preset.docs_url} target="_blank" rel="noreferrer">See this provider’s models</a>
          </span>
        )}
      </div>

      {needsKey && (
        <div className="field">
          <label htmlFor="prov-key">API key</label>
          <input
            id="prov-key"
            type="password"
            value={key}
            autoComplete="off"
            placeholder={preset ? `stored as psok/${preset.slug}` : 'stored in the OS keychain'}
            onChange={(e) => setKey(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) save() }}
          />
          <span className="hint">
            Goes straight into the OS keychain. providers.yaml holds only a reference to it
            {preset?.keys_url && (
              <> — <a href={preset.keys_url} target="_blank" rel="noreferrer">get one here</a></>
            )}
            .
          </span>
        </div>
      )}

      <div className="set-inline">
        <button type="button" className="btn btn--primary btn--small" disabled={busy} onClick={save}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="btn btn--ghost btn--small" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// A custom endpoint still needs a name to be keyed by. Its host is the one
// thing the user has already typed that is both stable and recognisable.
function nameFor(baseUrl) {
  try {
    return new URL(baseUrl).hostname.replace(/^www\./, '').replace(/[^a-z0-9._-]/gi, '-').toLowerCase()
  } catch {
    return ''
  }
}

function Models() {
  const { health, conversations, activeId, refreshConvs, refreshHealth, toast } = useApp()
  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}
  const unavailable = health?.providers_unavailable ?? {}
  const active = conversations.find((c) => c.id === activeId)

  const [catalogue, setCatalogue] = useState([])
  const [configured, setConfigured] = useState([])
  const [adding, setAdding] = useState(null)

  const load = useCallback(async () => {
    try {
      const data = await api.providers()
      setCatalogue(data.catalogue)
      setConfigured(data.configured)
    } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

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

  const remove = async (name) => {
    try {
      await api.removeProvider(name)
      toast(`${name} removed — its key stays in the keychain`, 'ok')
      load()
      refreshHealth?.()
    } catch (err) { toast(err.message, 'bad') }
  }

  const finish = () => { setAdding(null); load(); refreshHealth?.() }

  const unlisted = catalogue.filter((p) => !p.listed)

  return (
    <div className="set-panel">
      <h3>Providers</h3>
      <p className="set-note">
        Keys live in the OS keychain; <span className="mono">providers.yaml</span> holds only a
        reference. A provider with no key is listed and not offered.
      </p>
      <div className="set-rows">
        {configured.length === 0 && <div className="set-row"><span>none configured</span></div>}
        {configured.map((p) => (
          <div className="set-row" key={p.name}>
            <span>
              {p.name}
              <span className="set-sub">{p.default_model || 'no default model'}</span>
            </span>
            <span className="set-row-tail">
              {!p.has_key && <span className="badge">needs a key</span>}
              {p.has_key && !p.available && (
                <span className="badge" title={p.unavailable_reason}>not answering</span>
              )}
              {p.has_key && p.available && <span className="badge">ready</span>}
              <button
                type="button"
                className="btn btn--ghost btn--small"
                onClick={() => remove(p.name)}
              >
                Remove
              </button>
            </span>
          </div>
        ))}
      </div>

      {/* A provider that has a key and still cannot answer is the case `has_key`
          alone could never see: a local endpoint declares no key at all, so it
          reported itself configured while nothing was listening on its port. */}
      {Object.entries(unavailable).map(([name, reason]) => (
        <p className="set-note" key={name}>{name}: {reason}</p>
      ))}

      {adding !== null ? (
        <AddProviderForm
          preset={adding || null}
          onDone={finish}
          onCancel={() => setAdding(null)}
        />
      ) : (
        <>
          <h3>Add one</h3>
          <div className="set-rows">
            {unlisted.map((p) => (
              <div className="set-row" key={p.slug}>
                <span>
                  {p.label}
                  {p.note && (
                    <span className="set-sub">{p.note}</span>
                  )}
                </span>
                <span className="set-row-tail">
                  <button
                    type="button"
                    className="btn btn--ghost btn--small"
                    onClick={() => setAdding(p)}
                  >
                    Add
                  </button>
                </span>
              </div>
            ))}
            <div className="set-row">
              <span>
                Something else
                <span className="set-sub">Any OpenAI-compatible endpoint — vLLM, LM Studio, a proxy.</span>
              </span>
              <span className="set-row-tail">
                <button
                  type="button"
                  className="btn btn--ghost btn--small"
                  onClick={() => setAdding(false)}
                >
                  Add
                </button>
              </span>
            </div>
          </div>
        </>
      )}

      {active && (
        <>
          <h3>This conversation</h3>
          <div className="set-inline">
            <select value={active.provider} onChange={(e) => apply({ provider: e.target.value, model: defaults[e.target.value] || active.model })}>
              {providers.map((p) => (
                <option key={p} value={p} disabled={p in unavailable}>
                  {p}{p in unavailable ? ' — not answering' : ''}
                </option>
              ))}
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

/* A destructive row that asks by asking again.
 *
 * Same shape as the rail's delete: the second click is the confirmation. A
 * modal here would be friction on a button nobody presses by accident, and an
 * undo this interface cannot honour would be a lie. The count is shown before
 * the click so "clear everything" is never a guess about how much everything
 * is. */
function DangerRow({ label, note, count, confirmLabel, onConfirm }) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)

  // Disarm as soon as attention moves, so a click primed minutes ago cannot be
  // completed by a stray one later.
  useEffect(() => {
    if (!armed) return undefined
    const timer = setTimeout(() => setArmed(false), 6000)
    return () => clearTimeout(timer)
  }, [armed])

  return (
    <div className="set-row">
      <span>
        {label}
        <span className="set-note" style={{ display: 'block', margin: 0 }}>{note}</span>
      </span>
      <span className="set-row-tail">
        <span className="badge">{count == null ? '—' : count}</span>
        <button
          type="button"
          className={armed ? 'btn btn--danger btn--small' : 'btn btn--ghost btn--small'}
          disabled={busy || count === 0}
          onClick={async () => {
            if (!armed) { setArmed(true); return }
            setBusy(true)
            try { await onConfirm() } finally { setBusy(false); setArmed(false) }
          }}
        >
          {busy ? 'Clearing…' : armed ? confirmLabel : 'Clear'}
        </button>
      </span>
    </div>
  )
}

function Data() {
  const { toast, conversations, refreshConvs, deleteAllConversations } = useApp()
  const [facts, setFacts] = useState(null)

  const load = useCallback(async () => {
    try { setFacts((await api.memory()).facts.length) } catch { setFacts(null) }
  }, [])

  useEffect(() => { load() }, [load])

  return (
    <div className="set-panel">
      <h3>Clear stored data</h3>
      <p className="set-note">
        Both are immediate and cannot be undone. Tasks, the activity trail, indexed documents
        and your signed-in accounts are not touched by either.
      </p>
      <div className="set-rows">
        <DangerRow
          label="Conversations"
          note="Every conversation and its transcript. Automation runs are kept."
          count={conversations.length}
          confirmLabel="Click again to delete all"
          onConfirm={async () => { await deleteAllConversations(); refreshConvs() }}
        />
        <DangerRow
          label="Memories"
          note="Every fact PSOK has remembered about you. It stops recalling them."
          count={facts}
          confirmLabel="Click again to forget all"
          onConfirm={async () => {
            try {
              const { superseded } = await api.forgetAllMemories()
              toast(`Forgot ${superseded} fact${superseded === 1 ? '' : 's'}`, 'ok')
              load()
            } catch (err) { toast(err.message, 'bad') }
          }}
        />
      </div>
    </div>
  )
}

const PANELS = {
  general: General,
  models: Models,
  permissions: Permissions,
  data: Data,
}

export default function Settings() {
  const { overlay, setOverlay, setView } = useApp()
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

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOverlay(null) }}>
      <div className="settings" role="dialog" aria-modal="true" aria-label="Settings">
        <nav className="set-nav">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`set-nav-item${section === item.id ? ' active' : ''}`}
              onClick={() => setSection(item.id)}
            >
              <Icon name={item.icon} size={15} /> {item.label}
            </button>
          ))}
          <div className="set-nav-group">Pages</div>
          {PAGES.map((page) => (
            <button
              key={page.id}
              type="button"
              className="set-nav-item set-nav-item--away"
              onClick={() => { setView(page.id); setOverlay(null) }}
            >
              <Icon name={page.icon} size={15} /> {page.label}
              <Icon name="chevron" size={12} className="set-nav-away" />
            </button>
          ))}
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
