import { useCallback, useEffect, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { api } from '../api.js'

/* Voice, values, palette, fonts — and the block the model actually receives.
 *
 * The preview is not decoration. A settings page that stores a "voice" and then
 * does nothing visible with it is indistinguishable from one that quietly
 * dropped it, so the server returns `prompt_block` — the literal text appended
 * to the system prompt — and this renders it verbatim. Empty means empty: no
 * block is injected at all, and the preview says so. */

const LIST_HINT = 'One per line'

function Lines({ label, hint, value, onChange, rows = 3, placeholder }) {
  return (
    <label className="brand-field">
      <span>{label}</span>
      <textarea
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint ? <span className="field-note">{hint}</span> : null}
    </label>
  )
}

function Pairs({ label, hint, rows, keys, placeholders, onChange }) {
  const update = (index, key, next) => {
    const copy = rows.map((row) => ({ ...row }))
    copy[index] = { ...copy[index], [key]: next }
    onChange(copy)
  }
  return (
    <div className="brand-field">
      <span>{label}</span>
      <div className="brand-pairs">
        {rows.map((row, i) => (
          <div className="brand-pair" key={i}>
            <input
              value={row[keys[0]] || ''}
              placeholder={placeholders[0]}
              onChange={(e) => update(i, keys[0], e.target.value)}
            />
            <input
              value={row[keys[1]] || ''}
              placeholder={placeholders[1]}
              onChange={(e) => update(i, keys[1], e.target.value)}
            />
            {/* The user's own hex is data, so it is set inline. Everything
                around it comes from the theme tokens. */}
            {keys[1] === 'hex' && /^#[0-9a-fA-F]{3,8}$/.test(row.hex || '') ? (
              <span className="brand-swatch" style={{ background: row.hex }} aria-hidden="true" />
            ) : null}
            <button
              type="button"
              className="icon-btn"
              aria-label="Remove"
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        ))}
      </div>
      <button
        type="button"
        className="btn btn--ghost btn--small"
        onClick={() => onChange([...rows, { [keys[0]]: '', [keys[1]]: '' }])}
      >
        <Icon name="plus" size={13} /> Add
      </button>
      {hint ? <span className="field-note">{hint}</span> : null}
    </div>
  )
}

export default function BrandKit() {
  const { toast } = useApp()
  const [state, setState] = useState(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    try {
      const data = await api.brand()
      setState({
        ...data,
        values: (data.values || []).join('\n'),
        do: (data.do || []).join('\n'),
        dont: (data.dont || []).join('\n'),
      })
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const save = async () => {
    setSaving(true)
    try {
      // Sent as written; the server splits, trims and clamps, and hands back
      // the block it will use — so the preview is the server's rendering.
      const saved = await api.saveBrand({
        enabled: state.enabled,
        name: state.name,
        mission: state.mission,
        audience: state.audience,
        voice: state.voice,
        values: state.values,
        do: state.do,
        dont: state.dont,
        palette: (state.palette || []).filter((p) => p.name || p.hex),
        fonts: (state.fonts || []).filter((f) => f.role || f.family),
      })
      setState({
        ...saved,
        values: (saved.values || []).join('\n'),
        do: (saved.do || []).join('\n'),
        dont: (saved.dont || []).join('\n'),
      })
      toast(saved.prompt_block ? 'Brand saved and in use' : 'Brand saved — nothing to inject yet', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setSaving(false)
    }
  }

  if (!state) return <p className="set-note">Loading…</p>
  const set = (patch) => setState({ ...state, ...patch })

  return (
    <>
      <h3>Your voice</h3>
      <p className="set-note">
        Used when PSOK writes <em>for</em> you — a post, an email, copy, a caption — and not when
        it answers you. Everything here is optional; an empty kit adds nothing to the prompt.
      </p>

      <div className="set-row">
        <span>
          Use this when writing
          <span className="set-sub">Switch off to keep it stored but out of the prompt</span>
        </span>
        <span className="set-row-tail">
          <button
            type="button"
            className={`btn btn--small${state.enabled ? ' btn--primary' : ''}`}
            aria-pressed={state.enabled}
            onClick={() => set({ enabled: !state.enabled })}
          >
            {state.enabled ? 'On' : 'Off'}
          </button>
        </span>
      </div>

      <label className="brand-field">
        <span>Name</span>
        <input value={state.name || ''} placeholder="Ember Studio"
          onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label className="brand-field">
        <span>Audience</span>
        <input value={state.audience || ''} placeholder="independent designers, 25–40"
          onChange={(e) => set({ audience: e.target.value })} />
      </label>
      <Lines
        label="Mission" rows={2} value={state.mission || ''}
        placeholder="What you are actually for, in one sentence."
        onChange={(v) => set({ mission: v })}
      />
      <Lines
        label="Voice" rows={3} value={state.voice || ''}
        placeholder="Plain, specific, a little dry. Short sentences. No hype."
        hint="The single most useful field — describe how you sound, not what you sell."
        onChange={(v) => set({ voice: v })}
      />
      <Lines label="Values" hint={LIST_HINT} value={state.values} onChange={(v) => set({ values: v })} />
      <Lines label="Always" hint={LIST_HINT} value={state.do}
        placeholder={'name the trade-off\nuse their own words back'}
        onChange={(v) => set({ do: v })} />
      <Lines label="Never" hint={LIST_HINT} value={state.dont}
        placeholder={'exclamation marks\nthe word "revolutionary"'}
        onChange={(v) => set({ dont: v })} />

      <Pairs
        label="Palette" hint="Name and hex, for anything PSOK builds you"
        rows={state.palette || []} keys={['name', 'hex']}
        placeholders={['ink', '#0a0a0b']}
        onChange={(rows) => set({ palette: rows })}
      />
      <Pairs
        label="Fonts" hint="Role and family"
        rows={state.fonts || []} keys={['role', 'family']}
        placeholders={['display', 'Space Grotesk']}
        onChange={(rows) => set({ fonts: rows })}
      />

      <div className="set-inline">
        <button type="button" className="btn btn--primary btn--small" disabled={saving} onClick={save}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>

      <h3>What the model is told</h3>
      <p className="set-note">
        The exact text appended to the system prompt on every turn. Saved changes appear here
        as the server renders them.
      </p>
      {state.prompt_block ? (
        <pre className="brand-preview">{state.prompt_block}</pre>
      ) : (
        <p className="set-note">
          <Icon name="info" size={13} /> Nothing is injected. Fill in at least one field — the
          voice is the one that changes the most.
        </p>
      )}
    </>
  )
}
