import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api } from '../api.js'

/* Automations — beta. A turn that runs without anyone typing.

   Two decisions are stated on the page rather than buried, because both are
   surprising and both are load-bearing:

   They run while PSOK is open, and only then. A daemon that kept them running
   with the server down would be running turns nothing could answer a permission
   prompt for.

   And an unattended turn cannot answer one, so it refuses: anything the user
   has not already approved standing comes back as `blocked`, naming the exact
   operation, so the fix is to approve that one thing rather than to give
   scheduled work a blanket exemption. */

const EVERY = [
  { minutes: 15, label: 'every 15 minutes' },
  { minutes: 30, label: 'every 30 minutes' },
  { minutes: 60, label: 'hourly' },
  { minutes: 60 * 4, label: 'every 4 hours' },
  { minutes: 60 * 12, label: 'twice a day' },
  { minutes: 60 * 24, label: 'daily' },
  { minutes: 60 * 24 * 7, label: 'weekly' },
]

const describe = (minutes) =>
  EVERY.find((e) => e.minutes === minutes)?.label
  ?? (minutes % 1440 === 0
    ? `every ${minutes / 1440} days`
    : minutes % 60 === 0 ? `every ${minutes / 60} hours` : `every ${minutes} minutes`)

/** "in 4 minutes", "3 hours ago" — a wall-clock time answers the wrong question. */
function when(iso) {
  if (!iso) return '—'
  const delta = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(delta)) return iso
  const mins = Math.round(Math.abs(delta) / 60000)
  const size = mins < 60
    ? `${Math.max(1, mins)} minute${mins === 1 ? '' : 's'}`
    : mins < 1440
      ? `${Math.round(mins / 60)} hour${Math.round(mins / 60) === 1 ? '' : 's'}`
      : `${Math.round(mins / 1440)} day${Math.round(mins / 1440) === 1 ? '' : 's'}`
  return delta >= 0 ? `in ${size}` : `${size} ago`
}

/* What this automation has actually done, run by run.

   Only the newest was reachable before: the backend overwrites
   `last_conversation_id` each time, so every earlier run became unreferenced the
   moment the next finished — findable only by scrolling the conversation rail
   the runs were flooding. They are out of that rail now, so this is the only
   place they live. */
function RunHistory({ automation }) {
  const { setActiveId, setView } = useApp()
  const [runs, setRuns] = useState(null)
  const [open, setOpen] = useState(false)

  const load = useCallback(async () => {
    try {
      setRuns(await api.automationRuns(automation.id))
    } catch {
      setRuns([])
    }
  }, [automation.id])

  // Reload when a run finishes, so the list is not stale behind the status.
  useEffect(() => { if (open) load() }, [open, load, automation.last_run_at])

  const openRun = (id) => { setActiveId(id); setView('chat') }

  if (!automation.last_conversation_id) return null

  return (
    <div className="auto-runs">
      <button type="button" className="auto-open" onClick={() => openRun(automation.last_conversation_id)}>
        <Icon name="chat" size={12} /> Read what it did
      </button>
      <button type="button" className="auto-open" onClick={() => setOpen((o) => !o)}>
        <Icon name="clock" size={12} /> {open ? 'Hide earlier runs' : 'Earlier runs'}
      </button>
      {open && (
        <ul className="auto-run-list">
          {runs === null && <li className="auto-run-empty">Loading…</li>}
          {runs?.length === 0 && <li className="auto-run-empty">No runs kept yet.</li>}
          {runs?.map((run) => (
            <li key={run.id}>
              <button type="button" onClick={() => openRun(run.id)}>
                <span>{when(run.created_at)}</span>
                {run.id === automation.last_conversation_id && <span className="state">newest</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Composer({ onDone, onCancel }) {
  const { toast, health } = useApp()
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const [minutes, setMinutes] = useState(1440)
  const [busy, setBusy] = useState(false)
  const providers = health?.providers ?? []
  /* An automation is one model round trip per tool call, and a fifteen-step
     task multiplies whatever the model's latency is by fifteen. The columns for
     this have existed since automations shipped; nothing ever sent them, so
     every run went to the machine default however slow it was. */
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const defaultModel = health?.provider_defaults?.[provider] || ''

  const ready = name.trim() && prompt.trim()

  const create = async () => {
    if (!ready) return
    setBusy(true)
    try {
      await api.createAutomation({
        name,
        prompt,
        every_minutes: minutes,
        // Omitted, not blanked: the runner then picks the machine default at
        // run time rather than freezing today's default into the row.
        ...(provider ? { provider, model: model.trim() || defaultModel || null } : {}),
      })
      toast(`“${name.trim()}” will run ${describe(minutes)}`, 'ok')
      onDone()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cap-composer" data-enter>
      <div className="cap-composer-head">
        <span>New automation</span>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Cancel">
          <Icon name="x" size={15} />
        </button>
      </div>
      <div className="field">
        <label htmlFor="auto-name">Name</label>
        <input
          id="auto-name"
          autoFocus
          value={name}
          placeholder="Morning briefing"
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="auto-prompt">What it should do</label>
        <textarea
          id="auto-prompt"
          rows={5}
          value={prompt}
          placeholder={'Exactly what you would type into the composer.\n\nIt runs as an ordinary turn, in a conversation of its own.'}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="auto-every">How often</label>
        <select id="auto-every" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))}>
          {EVERY.map((e) => <option key={e.minutes} value={e.minutes}>{e.label}</option>)}
        </select>
        <span className="field-note">First run is one interval from now, not immediately.</span>
      </div>
      <div className="field">
        <label htmlFor="auto-provider">Model</label>
        <select
          id="auto-provider"
          value={provider}
          onChange={(e) => { setProvider(e.target.value); setModel('') }}
        >
          <option value="">
            {providers.length ? `Machine default (${providers[0]})` : 'Machine default'}
          </option>
          {providers.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        {provider && (
          <input
            value={model}
            placeholder={defaultModel || 'model name'}
            onChange={(e) => setModel(e.target.value)}
            style={{ marginTop: 8 }}
          />
        )}
        <span className="field-note">
          Most of a run is spent waiting on the model, not on tools — a run is one round trip
          per tool call. A faster provider is the shortest way to make this quicker.
        </span>
      </div>
      <div className="cap-composer-foot">
        <button type="button" className="btn btn--primary btn--small" disabled={!ready || busy} onClick={create}>
          {busy ? 'Saving…' : 'Create'}
        </button>
      </div>
    </div>
  )
}

export default function Automations() {
  const rootRef = useRef(null)
  const { toast, setView, setActiveId } = useApp()
  const [rows, setRows] = useState([])
  const [composing, setComposing] = useState(false)
  const [busy, setBusy] = useState('')
  const [loaded, setLoaded] = useState(false)
  useViewEntrance(rootRef)

  const load = useCallback(async () => {
    try {
      setRows((await api.automations()).automations || [])
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setLoaded(true)
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  // A run in flight changes `last_status` on the server, not here.
  useEffect(() => {
    if (!rows.some((r) => r.last_status === 'running')) return undefined
    const tick = setInterval(load, 4000)
    return () => clearInterval(tick)
  }, [rows, load])

  const act = useCallback(async (row, action) => {
    setBusy(`${row.id}:${action}`)
    try {
      if (action === 'run') {
        const result = await api.runAutomation(row.id)
        toast(
          result.status === 'ok' ? `“${row.name}” ran` : `“${row.name}”: ${result.summary}`,
          result.status === 'ok' ? 'ok' : result.status === 'blocked' ? 'amber' : 'bad',
        )
      } else if (action === 'toggle') {
        await api.updateAutomation(row.id, { enabled: !row.enabled })
      } else if (action === 'delete') {
        if (!window.confirm(`Delete “${row.name}”? The conversations it wrote are kept.`)) return
        await api.deleteAutomation(row.id)
        toast('Automation deleted', 'info')
      }
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [load, toast])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="cap-head" data-enter>
          <h1>Automations <span className="beta">beta</span></h1>
          <button
            type="button"
            className={`btn btn--pill${composing ? ' btn--ghost' : ' btn--primary'}`}
            onClick={() => setComposing((c) => !c)}
            aria-expanded={composing}
          >
            <Icon name={composing ? 'x' : 'plus'} size={14} /> New automation
          </button>
        </header>

        <div className="msg-note msg-note--warning" style={{ marginBottom: 20 }} data-enter>
          <Icon name="info" size={14} />
          <span>
            <strong style={{ fontWeight: 500 }}>What this is, exactly.</strong> A prompt and an
            interval. It runs as an ordinary turn in a conversation of its own, <strong>while
            PSOK is open</strong> — there is no daemon, so nothing runs when the server is down.
            An unattended turn has nobody to answer a permission prompt, so it does not raise
            one: anything you have not already approved with “don’t ask again” comes back
            <span className="mono"> blocked</span>, naming the operation it wanted. No cron
            expressions and no triggers other than the clock yet.
          </span>
        </div>

        {composing && <Composer onDone={() => { setComposing(false); load() }} onCancel={() => setComposing(false)} />}

        {loaded && rows.length === 0 && !composing && (
          <div className="card empty-state" data-enter>
            <Icon name="clock" size={22} />
            Nothing runs on its own yet. A good first one is something you already ask for by
            hand every day — a summary of what changed, or what is due.
          </div>
        )}

        <div className="auto-list">
          {rows.map((row) => (
            <div className={`auto-row${row.enabled ? '' : ' is-off'}`} key={row.id} data-enter>
              <div className="auto-main">
                <div className="auto-name">
                  {row.name}
                  <span className="state">{describe(row.every_minutes)}</span>
                </div>
                <p className="auto-prompt">{row.prompt}</p>
                <div className="auto-meta">
                  <span>{row.enabled ? `next ${when(row.next_run_at)}` : 'paused'}</span>
                  {row.last_run_at && (
                    <span className={`auto-last auto-last--${row.last_status}`}>
                      last run {when(row.last_run_at)} · {row.last_status}
                      {row.last_summary ? ` — ${row.last_summary}` : ''}
                    </span>
                  )}
                </div>
                <RunHistory automation={row} />
              </div>
              <div className="auto-actions">
                <button
                  type="button"
                  className="btn btn--small"
                  disabled={busy === `${row.id}:run` || row.last_status === 'running'}
                  onClick={() => act(row, 'run')}
                >
                  {busy === `${row.id}:run` || row.last_status === 'running' ? 'Running…' : 'Run now'}
                </button>
                <button
                  type="button"
                  className={`btn btn--small${row.enabled ? ' btn--ghost' : ' btn--primary'}`}
                  disabled={busy === `${row.id}:toggle`}
                  onClick={() => act(row, 'toggle')}
                >
                  {row.enabled ? 'Pause' : 'Resume'}
                </button>
                <button
                  type="button"
                  className="icon-btn"
                  title="Delete this automation"
                  aria-label={`Delete ${row.name}`}
                  disabled={busy === `${row.id}:delete`}
                  onClick={() => act(row, 'delete')}
                >
                  <Icon name="trash" size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
