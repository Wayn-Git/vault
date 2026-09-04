import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'
import { useApp } from '../store.jsx'
import { forSettings } from '../nav.js'
import { useConfirm } from './ui/ConfirmDialog.jsx'
import Badge from './ui/Badge.jsx'
import BrandKit from './BrandKit.jsx'
import { useModalDismiss, onOverlayMouseDown } from '../hooks/useModalDismiss.js'
import { useFocusTrap } from '../hooks/useFocusTrap.js'

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
  // Not a rail page: this is edited twice a year, and it belongs beside the
  // other things that change how a turn behaves rather than beside the pages
  // you open every day.
  { id: 'brand', label: 'Brand', icon: 'star' },
  { id: 'permissions', label: 'Permissions', icon: 'key' },
  { id: 'data', label: 'Data', icon: 'trash' },
]

// Every one of these is a full view in the rail. The nav links to them so that
// looking for skills in the settings finds them, rather than finding a smaller
// second copy.
const PAGES = forSettings()

/* The three answers, in the order they are chosen. `system` first because it
   is the one that needs no decision — an application that opens in the wrong
   palette at 9am is one more thing to go and configure. */
const THEME_CHOICES = [
  { id: 'system', label: 'Match the system', hint: 'Follows the machine’s own light or dark setting' },
  { id: 'dark', label: 'Graphite', hint: 'The console, always' },
  { id: 'light', label: 'Paper', hint: 'The same panel with the light on' },
]

function General() {
  const { health, healthError, workspace, setWorkspace, theme, setTheme } = useApp()
  const [draft, setDraft] = useState(workspace || '')

  return (
    <div className="set-panel">
      <h3>Appearance</h3>
      <div className="theme-picker" role="radiogroup" aria-label="Colour theme">
        {THEME_CHOICES.map((choice) => (
          <button
            key={choice.id}
            type="button"
            role="radio"
            aria-checked={theme === choice.id}
            className={`theme-swatch theme-swatch--${choice.id}${theme === choice.id ? ' is-on' : ''}`}
            onClick={() => setTheme(choice.id)}
          >
            {/* The swatch is the palette itself rather than a word for it, so
                picking one is a comparison instead of a guess. */}
            <span className="theme-chip" aria-hidden="true">
              <i className="theme-chip-bg" />
              <i className="theme-chip-fg" />
              <i className="theme-chip-live" />
            </span>
            <span className="theme-swatch-text">
              <span className="theme-swatch-label">{choice.label}</span>
              <span className="theme-swatch-hint">{choice.hint}</span>
            </span>
            {theme === choice.id && <Icon name="check" size={14} />}
          </button>
        ))}
      </div>

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

      <IterationLimit />

      <DailyRhythm />

      <TurnNotifications />

    </div>
  )
}

/* A desktop notification when a turn finishes, for the long ones you tab away
 * from. Off by default -- it needs the browser's permission, which only a user
 * gesture can request -- and it only fires while this tab is in the background,
 * since a notification about the answer already on screen is just noise. */
function TurnNotifications() {
  const { notifyOnDone, setNotifyOnDone, toast } = useApp()

  const toggle = async () => {
    const { value, blocked } = await setNotifyOnDone(!notifyOnDone)
    if (blocked) {
      toast('Your browser blocked notifications — allow them for this site, then try again', 'amber')
    } else {
      toast(value ? 'You will be notified when a turn finishes' : 'Turn notifications off', 'ok')
    }
  }

  return (
    <>
      <h3>Notifications</h3>
      <p className="set-note">
        A desktop notification when a turn finishes, so you can tab away from a long one.
        Only fires while this tab is in the background; click it to jump back to the conversation.
      </p>
      <div className="set-rows">
        <div className="set-row">
          <span>
            Notify when a turn finishes
            <span className="set-sub">Uses your browser&apos;s notifications — it will ask permission once.</span>
          </span>
          <span className="set-row-tail">
            <button
              type="button"
              role="switch"
              aria-checked={notifyOnDone}
              className={`btn btn--small${notifyOnDone ? ' btn--primary' : ' btn--ghost'}`}
              onClick={toggle}
            >
              {notifyOnDone ? 'On' : 'Off'}
            </button>
          </span>
        </div>
      </div>
    </>
  )
}

/* How many steps a single turn may take before it is made to wrap up.
 *
 * A turn spends one step per model round trip -- each tool call is a step -- so
 * a browse-search-read-act task eats several. Too low cuts multi-step work
 * short with "iteration limit reached"; too high lets a stuck loop run a while
 * before the time guard stops it. The last step always forces an answer, so
 * raising this buys more tool calls, not a longer dead end. */
/* When the briefing and the reviews are filed.
 *
 * Five knobs the server publishes as one nested `journal` object, because they
 * are read and saved together. Hours are local: seven means seven where you
 * are, on the same clock the reminders use. */
const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function DailyRhythm() {
  const { toast } = useApp()
  const [state, setState] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.settings()
      .then((s) => setState(s.journal))
      .catch((err) => toast(err.message, 'bad'))
  }, [toast])

  const save = async (patch) => {
    setSaving(true)
    try {
      const s = await api.updateSettings({ journal: patch })
      setState(s.journal)  // reflect the server's clamp
    } catch (err) { toast(err.message, 'bad') } finally { setSaving(false) }
  }

  if (!state) return null
  const hours = Array.from({ length: 24 }, (_, h) => h)

  return (
    <>
      <h3>Daily rhythm</h3>
      <p className="set-note">
        When the morning briefing and the evening check-in are filed. Both run while PSOK is
        open, on this machine&rsquo;s own clock. A day PSOK was never open for is simply not filed —
        you can write one at any time from Today.
      </p>
      <div className="set-rows">
        <div className="set-row">
          <span>
            Morning briefing
            <span className="set-sub">Written from your calendar, tasks, inbox and library</span>
          </span>
          <span className="set-row-tail">
            <select
              value={state.briefing_hour}
              disabled={saving}
              aria-label="Briefing hour"
              onChange={(e) => save({ briefing_hour: Number(e.target.value) })}
            >
              {hours.map((h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
            </select>
            <button
              type="button"
              className={`btn btn--small${state.briefing_enabled ? ' btn--primary' : ''}`}
              aria-pressed={state.briefing_enabled}
              disabled={saving}
              onClick={() => save({ briefing_enabled: !state.briefing_enabled })}
            >
              {state.briefing_enabled ? 'On' : 'Off'}
            </button>
          </span>
        </div>
        <div className="set-row">
          <span>
            Evening check-in
            <span className="set-sub">
              Filed with the day&rsquo;s real figures. Nothing is written up until you answer it.
            </span>
          </span>
          <span className="set-row-tail">
            <select
              value={state.review_hour}
              disabled={saving}
              aria-label="Review hour"
              onChange={(e) => save({ review_hour: Number(e.target.value) })}
            >
              {hours.map((h) => <option key={h} value={h}>{String(h).padStart(2, '0')}:00</option>)}
            </select>
            <button
              type="button"
              className={`btn btn--small${state.review_enabled ? ' btn--primary' : ''}`}
              aria-pressed={state.review_enabled}
              disabled={saving}
              onClick={() => save({ review_enabled: !state.review_enabled })}
            >
              {state.review_enabled ? 'On' : 'Off'}
            </button>
          </span>
        </div>
        <div className="set-row">
          <span>
            Weekly review
            <span className="set-sub">Rolls up that week&rsquo;s check-ins, at the review hour</span>
          </span>
          <span className="set-row-tail">
            <select
              value={state.weekly_weekday}
              disabled={saving}
              aria-label="Weekly review day"
              onChange={(e) => save({ weekly_weekday: Number(e.target.value) })}
            >
              {WEEKDAYS.map((day, i) => <option key={day} value={i}>{day}</option>)}
            </select>
            <button
              type="button"
              className={`btn btn--small${state.weekly_enabled ? ' btn--primary' : ''}`}
              aria-pressed={state.weekly_enabled}
              disabled={saving}
              onClick={() => save({ weekly_enabled: !state.weekly_enabled })}
            >
              {state.weekly_enabled ? 'On' : 'Off'}
            </button>
          </span>
        </div>
      </div>
    </>
  )
}

function IterationLimit() {
  const { toast } = useApp()
  const [value, setValue] = useState('')
  const [bounds, setBounds] = useState({ min: 4, max: 40, default: 16 })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.settings()
      .then((s) => {
        setValue(String(s.max_iterations))
        setBounds({ min: s.max_iterations_min, max: s.max_iterations_max, default: s.max_iterations_default })
      })
      .catch((err) => toast(err.message, 'bad'))
  }, [toast])

  const save = async () => {
    const n = Number(value)
    if (!Number.isFinite(n)) { toast('Enter a number', 'bad'); return }
    setSaving(true)
    try {
      const s = await api.updateSettings({ max_iterations: Math.round(n) })
      setValue(String(s.max_iterations))  // reflect the server's clamp
      toast(`Turns may now take up to ${s.max_iterations} steps`, 'ok')
    } catch (err) { toast(err.message, 'bad') } finally { setSaving(false) }
  }

  return (
    <>
      <h3>Steps per turn</h3>
      <p className="set-note">
        How many tool calls and model round trips one message may take before the turn is made
        to answer with what it has. Higher lets longer multi-step tasks finish;
        lower keeps turns short. Between {bounds.min} and {bounds.max}; default {bounds.default}.
      </p>
      <div className="set-inline">
        <input
          type="number"
          min={bounds.min}
          max={bounds.max}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') save() }}
        />
        <button type="button" className="btn btn--primary btn--small" disabled={saving} onClick={save}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </>
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
    // A custom entry is named after its host, and the host alone is not
    // enough to tell two endpoints apart -- `nameFor` needs the model too, or
    // it sends the server an empty name and the 400 that comes back names the
    // wrong field. Caught here, before the request, so the message points at
    // what is actually missing.
    if (custom && !model.trim()) {
      toast('Give it a model id — a custom provider is named from it', 'bad')
      return
    }
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

const ROLE_META = [
  { id: 'default', label: 'Go-to model', hint: 'The everyday default a new conversation starts on.' },
  { id: 'fast', label: 'Fast', hint: 'The quick, cheap model — hand-offs and the memory extractor.' },
  { id: 'heavy', label: 'Heavy', hint: 'What the fast model escalates to for hard reasoning.' },
]

/* Assign a provider and model to each job (the `tiers:` block of providers.yaml).
 *
 * The model field is a datalist, not a plain input: choosing a provider fetches
 * what its own API lists right now, so the user picks from what the endpoint
 * actually serves instead of retyping an id from a docs page. Free-flagged
 * models (OpenRouter pricing, a `:free` suffix) sort first and are marked. The
 * field still takes free text, because a brand-new model id beats a stale list. */
function RolesEditor({ providers, defaults, unavailable }) {
  const { toast, refreshHealth } = useApp()
  const [tiers, setTiers] = useState({})
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try { setTiers((await api.tiers()).tiers || {}) } catch (err) { toast(err.message, 'bad') }
  }, [toast])
  useEffect(() => { load() }, [load])

  const save = async (role, provider, model) => {
    if (!provider || !model?.trim()) return
    setBusy(role)
    try {
      await api.setTier(role, provider, model.trim())
      await load()
      refreshHealth?.()
      toast(`${role} → ${provider} · ${model.trim()}`, 'ok')
    } catch (err) { toast(err.message, 'bad') } finally { setBusy('') }
  }

  const clear = async (role) => {
    setBusy(role)
    try {
      await api.clearTier(role)
      await load()
      refreshHealth?.()
      toast(`${role} unassigned — it falls back to the conversation's model`, 'ok')
    } catch (err) { toast(err.message, 'bad') } finally { setBusy('') }
  }

  if (providers.length === 0) return null

  return (
    <>
      <h3>Roles</h3>
      <p className="set-note">
        Which model does which job. The go-to model is where a new conversation starts; an
        unassigned role falls back to the conversation&apos;s own model.
      </p>
      <div className="set-rows">
        {ROLE_META.map((role) => (
          <RoleRow
            key={role.id}
            role={role}
            current={tiers[role.id]}
            providers={providers}
            defaults={defaults}
            unavailable={unavailable}
            busy={busy === role.id}
            onSave={save}
            onClear={clear}
          />
        ))}
      </div>
    </>
  )
}

function RoleRow({ role, current, providers, defaults, unavailable, busy, onSave, onClear }) {
  const [provider, setProvider] = useState(current?.provider || providers[0] || '')
  const [model, setModel] = useState(current?.model || '')
  const [models, setModels] = useState([])

  // Re-sync when the saved assignment changes underneath the editor.
  useEffect(() => {
    setProvider(current?.provider || providers[0] || '')
    setModel(current?.model || '')
  }, [current, providers])

  // The provider's live model list, best-effort. An endpoint that will not
  // answer just leaves the datalist empty and the free-text field working.
  useEffect(() => {
    let live = true
    if (!provider) { setModels([]); return }
    api.providerModels(provider)
      .then((r) => { if (live) setModels(r.models || []) })
      .catch(() => { if (live) setModels([]) })
    return () => { live = false }
  }, [provider])

  const listId = `models-${role.id}`
  const dirty = provider !== (current?.provider || '') || model !== (current?.model || '')

  return (
    <div className="set-role-row">
      <div className="set-role-head">
        <span>{role.label}</span>
        <span className="set-sub">{role.hint}</span>
      </div>
      <div className="set-role-controls">
        <select
          value={provider}
          onChange={(e) => { setProvider(e.target.value); setModel(defaults[e.target.value] || '') }}
        >
          {providers.map((p) => (
            <option key={p} value={p} disabled={p in unavailable}>
              {p}{p in unavailable ? ' — not answering' : ''}
            </option>
          ))}
        </select>
        <input
          list={listId}
          value={model}
          placeholder={defaults[provider] || 'model id'}
          onChange={(e) => setModel(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && dirty) onSave(role.id, provider, model) }}
        />
        <datalist id={listId}>
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.free ? 'free — ' : ''}{m.id}</option>
          ))}
        </datalist>
        <button
          type="button"
          className="btn btn--small btn--primary"
          disabled={busy || !dirty || !model.trim()}
          onClick={() => onSave(role.id, provider, model)}
        >
          {busy ? 'Saving…' : 'Save'}
        </button>
        {current && (
          <button
            type="button"
            className="btn btn--ghost btn--small"
            disabled={busy}
            onClick={() => onClear(role.id)}
          >
            Clear
          </button>
        )}
      </div>
      {models.length > 0 && (
        <span className="set-sub">
          {models.length} model{models.length === 1 ? '' : 's'} from its API
          {models.some((m) => m.free) ? ` · ${models.filter((m) => m.free).length} free` : ''}
        </span>
      )}
    </div>
  )
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
  // Per-provider Ping result: name -> { available, latency_ms, reason } or
  // 'busy' while the request is in flight. Kept here rather than in the row so
  // "Ping all" can fill every row at once.
  const [pinged, setPinged] = useState({})

  const load = useCallback(async () => {
    try {
      const data = await api.providers()
      setCatalogue(data.catalogue)
      setConfigured(data.configured)
    } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

  const pingOne = useCallback(async (name) => {
    setPinged((m) => ({ ...m, [name]: 'busy' }))
    try {
      const r = await api.pingProvider(name)
      setPinged((m) => ({ ...m, [name]: r }))
      refreshHealth?.()
    } catch (err) {
      setPinged((m) => ({ ...m, [name]: { available: false, reason: err.message } }))
    }
  }, [refreshHealth])

  const pingAll = useCallback(async () => {
    setPinged((m) => {
      const busy = { ...m }
      for (const p of configured) busy[p.name] = 'busy'
      return busy
    })
    try {
      const { results } = await api.pingAll()
      setPinged(results)
      refreshHealth?.()
    } catch (err) { toast(err.message, 'bad') }
  }, [configured, refreshHealth, toast])

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
      <div className="set-head-row">
        <h3>Providers</h3>
        {configured.length > 0 && (
          <button type="button" className="btn btn--ghost btn--small" onClick={pingAll}>
            Ping all
          </button>
        )}
      </div>
      <p className="set-note">
        Keys live in the OS keychain; <span className="mono">providers.yaml</span> holds only a
        reference. A provider with no key is listed and not offered. Ping checks the endpoint
        now, whatever the badge last remembered.
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
              {!p.has_key && <Badge>needs a key</Badge>}
              {p.has_key && !p.available && (
                <Badge title={p.unavailable_reason}>not answering</Badge>
              )}
              {p.has_key && p.available && <Badge>ready</Badge>}
              {pinged[p.name] === 'busy' && <span className="set-sub">pinging…</span>}
              {pinged[p.name] && pinged[p.name] !== 'busy' && (
                <Badge title={pinged[p.name].reason || undefined}>
                  {pinged[p.name].available
                    ? `answered${pinged[p.name].latency_ms != null ? ` · ${pinged[p.name].latency_ms}ms` : ''}`
                    : 'no answer'}
                </Badge>
              )}
              <button
                type="button"
                className="btn btn--ghost btn--small"
                disabled={pinged[p.name] === 'busy'}
                onClick={() => pingOne(p.name)}
              >
                Ping
              </button>
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

      <RolesEditor providers={providers} defaults={defaults} unavailable={unavailable} />

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
              <Badge>{row.risk_level}</Badge>
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
 * An undo this interface cannot honour would be a lie, so this asks first --
 * the count is shown before the click so "clear everything" is never a guess
 * about how much everything is. */
function DangerRow({ label, note, count, confirmLabel, onConfirm }) {
  const [busy, setBusy] = useState(false)
  const confirm = useConfirm()

  return (
    <div className="set-row">
      <span>
        {label}
        <span className="set-note" style={{ display: 'block', margin: 0 }}>{note}</span>
      </span>
      <span className="set-row-tail">
        <Badge>{count == null ? '—' : count}</Badge>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          disabled={busy || count === 0}
          onClick={async () => {
            const ok = await confirm({
              title: `Clear ${label.toLowerCase()}?`,
              description: `${note} This cannot be undone.`,
              confirmLabel,
              tone: 'danger',
            })
            if (!ok) return
            setBusy(true)
            try { await onConfirm() } finally { setBusy(false) }
          }}
        >
          {busy ? 'Clearing…' : 'Clear'}
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
          confirmLabel="Delete all"
          onConfirm={async () => { await deleteAllConversations(); refreshConvs() }}
        />
        <DangerRow
          label="Memories"
          note="Every fact PSOK has remembered about you. It stops recalling them."
          count={facts}
          confirmLabel="Forget all"
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
  brand: BrandKit,
  permissions: Permissions,
  data: Data,
}

export default function Settings() {
  const { overlay, setOverlay, setView } = useApp()
  const [section, setSection] = useState('general')
  const open = overlay === 'settings'
  const panelRef = useRef(null)
  const close = useCallback(() => setOverlay(null), [setOverlay])

  useModalDismiss(open, close)
  useFocusTrap(panelRef, open)

  if (!open) return null
  const Panel = PANELS[section] || General

  return (
    <div className="modal-overlay" onMouseDown={onOverlayMouseDown(close)}>
      <div className="settings" ref={panelRef} role="dialog" aria-modal="true" aria-label="Settings">
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
