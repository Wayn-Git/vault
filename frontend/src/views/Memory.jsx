import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../gsapFx.js'
import { api, fmtDate } from '../api.js'

export default function Memory() {
  const rootRef = useRef(null)
  const { toast } = useApp()
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState('')
  const [filter, setFilter] = useState('')
  useViewEntrance(rootRef)

  const load = useCallback(async () => {
    try {
      setState(await api.memory())
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const toggle = async () => {
    setBusy('toggle')
    try {
      const next = await api.toggleMemory(!state.enabled)
      toast(next.enabled ? 'Memory on' : 'Memory off — nothing new will be recorded', 'ok')
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  const forget = async (fact) => {
    setBusy(`f${fact.id}`)
    try {
      await api.forgetMemory(fact.id)
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  const facts = (state?.facts ?? []).filter(
    (f) => !filter.trim() || f.fact.toLowerCase().includes(filter.trim().toLowerCase()),
  )
  const enabled = state?.enabled ?? false

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <div className="vheader-eyebrow">
              <span className={`led led--${enabled ? 'ok' : 'faint'}`} /> memory
            </div>
            <h1>What PSOK remembers</h1>
            <div className="vheader-sub">
              Standing facts, extracted after a turn and recalled in later conversations.
              Correcting one retires it rather than deleting it, so what PSOK believed —
              and when that changed — stays answerable.
            </div>
          </div>
          <div className="vheader-actions">
            <button
              type="button"
              className={`btn btn--small${enabled ? ' btn--primary' : ' btn--ghost'}`}
              disabled={busy === 'toggle' || !state}
              onClick={toggle}
            >
              {enabled ? 'Memory on' : 'Memory off'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={load}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        {!enabled && state && (
          <div className="msg-note msg-note--warning" style={{ marginBottom: 16 }} data-enter>
            <Icon name="info" size={14} />
            <span>
              Memory is switched off globally: nothing new is recorded and nothing below is
              recalled. Facts already held are kept, not deleted.
            </span>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', flexWrap: 'wrap' }} data-enter>
          <span className="badge badge--amber">{state?.facts?.length ?? 0} held</span>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="filter facts…"
            style={{
              background: 'var(--canvas-deep)', border: '1px solid var(--hairline)', borderRadius: 4,
              padding: '5px 10px', fontSize: 12, fontFamily: 'var(--font-mono)',
              color: 'var(--text-dim)', minWidth: 240,
            }}
          />
        </div>

        {state && facts.length === 0 && (
          <div className="card empty-state" data-enter>
            <Icon name="spark" size={22} />
            {state.facts.length === 0
              ? 'Nothing remembered yet. Tell PSOK something durable about you — a preference, a project, a constraint — and it will be recorded after the turn.'
              : 'No fact matches that filter.'}
          </div>
        )}

        {facts.length > 0 && (
          <div className="card card-pad" data-enter>
            <div className="card-title"><span className="led led--ok" /> live facts</div>
            {facts.map((f) => (
              <div className="server-row" key={f.id}>
                <span className="led led--ok" />
                <div style={{ minWidth: 0 }}>
                  <div className="server-name" style={{ whiteSpace: 'normal' }}>{f.fact}</div>
                  <div className="server-target">
                    id {f.id} · learned {fmtDate(f.created_at)}
                    {f.conversation_id ? ` · in conversation ${f.conversation_id.slice(0, 8)}` : ''}
                  </div>
                </div>
                <div className="server-actions">
                  <button
                    type="button"
                    className="btn btn--ghost btn--small"
                    disabled={busy === `f${f.id}`}
                    onClick={() => forget(f)}
                    title="Retire this fact — recall stops, the row is kept"
                  >
                    <Icon name="trash" size={13} /> {busy === `f${f.id}` ? '…' : 'Forget'}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
