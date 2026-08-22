import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import ServiceIcon from '../../components/ServiceIcon.jsx'
import { useApp } from '../../store.jsx'
import { api } from '../../api.js'

/* Skills: the ones on this machine and the ones that could be, in one list.

   Installed and installable used to be two surfaces — a view for what you had,
   an overlay for what you could get — and a skill that existed in both showed
   up twice with different controls. One row per skill now, whatever its origin,
   carrying whichever actions actually apply to it. */

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'installed', label: 'Installed' },
  { id: 'available', label: 'Not installed' },
]

/* A skill is a name, a description and an instruction. Writing one used to mean
   composing YAML frontmatter by hand into a file whose path had to match the
   name inside it; these are the three fields that are actually the skill, and
   the backend writes the file. */
function Composer({ onDone, onCancel }) {
  const { toast } = useApp()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instruction, setInstruction] = useState('')
  const [busy, setBusy] = useState(false)

  const slug = name.trim().toLowerCase().replace(/\s+/g, '-')
  const ready = slug && description.trim() && instruction.trim()

  const create = async (overwrite = false) => {
    if (!ready) return
    setBusy(true)
    try {
      const skill = await api.createSkill({ name, description, instruction, overwrite })
      toast(`Wrote /${skill.name}`, 'ok')
      onDone()
    } catch (err) {
      if (/already installed/.test(err.message)) toast(`${err.message} — Replace overwrites it`, 'amber')
      else toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="cap-composer" data-enter>
      <div className="cap-composer-head">
        <span>New skill</span>
        <button type="button" className="icon-btn" onClick={onCancel} aria-label="Cancel">
          <Icon name="x" size={15} />
        </button>
      </div>
      <div className="field">
        <label htmlFor="skill-name">Name</label>
        <input
          id="skill-name"
          autoFocus
          value={name}
          placeholder="release notes"
          onChange={(e) => setName(e.target.value)}
        />
        {slug && slug !== name.trim() && (
          <span className="field-note">saved as <span className="mono">/{slug}</span></span>
        )}
      </div>
      <div className="field">
        <label htmlFor="skill-desc">Description</label>
        <input
          id="skill-desc"
          value={description}
          placeholder="When to reach for this — the agent reads this to decide"
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="skill-body">Instruction</label>
        <textarea
          id="skill-body"
          rows={7}
          value={instruction}
          placeholder={'What to do, in the order to do it.\n\nMarkdown. This is the whole body of the SKILL.md.'}
          onChange={(e) => setInstruction(e.target.value)}
        />
      </div>
      <div className="cap-composer-foot">
        <button type="button" className="btn btn--primary btn--small" disabled={!ready || busy} onClick={() => create(false)}>
          {busy ? 'Writing…' : 'Create'}
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          disabled={!ready || busy}
          title="Overwrite an installed skill of the same name"
          onClick={() => create(true)}
        >
          Replace
        </button>
      </div>
    </div>
  )
}

function Gear({ name, capability, onToggle, onRemove, busy }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return undefined
    const away = () => setOpen(false)
    document.addEventListener('click', away)
    return () => document.removeEventListener('click', away)
  }, [open])

  return (
    <span className="dcard-gear-wrap">
      <button
        type="button"
        className="dcard-act"
        title="Manage this skill"
        aria-label={`Manage ${name}`}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
      >
        <Icon name="sliders" size={15} />
      </button>
      {open && (
        <div className="dcard-menu" onClick={(e) => e.stopPropagation()}>
          <button
            type="button"
            className="menu-row"
            disabled={busy || !capability}
            onClick={() => { onToggle(); setOpen(false) }}
          >
            <span className="menu-gutter" />
            <span className="menu-label">{capability?.enabled ? 'Stand down' : 'Engage'}</span>
          </button>
          <button
            type="button"
            className="menu-row danger"
            onClick={() => { onRemove(); setOpen(false) }}
          >
            <span className="menu-gutter" />
            <span className="menu-label">Uninstall</span>
          </button>
        </div>
      )}
    </span>
  )
}

export default function SkillsTab({ query, newOpen, setNewOpen }) {
  const { toast, caps, refreshCaps, setCapEnabled, busyCap } = useApp()
  const [installed, setInstalled] = useState([])
  const [errors, setErrors] = useState([])
  const [catalogue, setCatalogue] = useState({ skills: [], error: null })
  const [filter, setFilter] = useState('all')
  const [busy, setBusy] = useState('')
  const [importing, setImporting] = useState(false)
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(true)

  const load = useCallback((refresh = false) => {
    const fail = (err) => toast(err.message, 'bad')
    setLoading(true)
    api.skills()
      .then((d) => { setInstalled(d.skills || []); setErrors(d.errors || []) })
      .catch(fail)
    api.skillCatalogue(refresh)
      .then(setCatalogue)
      .catch((err) => setCatalogue({ skills: [], error: err.message }))
      .finally(() => setLoading(false))
    refreshCaps()
  }, [refreshCaps, toast])

  useEffect(() => { load() }, [load])

  const install = useCallback(async (target, { overwrite = false } = {}) => {
    setBusy(target)
    try {
      const skill = await api.installSkill(target, overwrite)
      toast(`Installed /${skill.name}`, 'ok')
      setUrl('')
      load()
    } catch (err) {
      if (/already installed/.test(err.message)) toast(`${err.message} — Replace updates it`, 'amber')
      else toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [load, toast])

  const remove = useCallback(async (name) => {
    try {
      await api.removeSkill(name)
      toast(`Uninstalled /${name}`, 'ok')
      load()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [load, toast])

  // One row per skill, whether it came from disk, the catalogue, or both.
  const rows = useMemo(() => {
    const all = new Map()
    for (const entry of catalogue.skills) {
      all.set(entry.name, {
        name: entry.name,
        description: entry.description,
        publisher: entry.publisher,
        url: entry.url,
        installed: entry.installed,
      })
    }
    for (const skill of installed) {
      const existing = all.get(skill.name)
      all.set(skill.name, {
        name: skill.name,
        description: skill.description || existing?.description || '',
        publisher: existing?.publisher || 'On this machine',
        url: existing?.url,
        installed: true,
        version: skill.version,
      })
    }
    return [...all.values()]
  }, [catalogue, installed])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = rows.filter(
      (r) => !q || r.name.toLowerCase().includes(q) || (r.description || '').toLowerCase().includes(q),
    )
    if (filter === 'installed') list = list.filter((r) => r.installed)
    if (filter === 'available') list = list.filter((r) => !r.installed)
    // Installed first: what you have is what you are most often here to change.
    return [...list].sort(
      (a, b) => Number(b.installed) - Number(a.installed) || a.name.localeCompare(b.name),
    )
  }, [rows, query, filter])

  const engaged = (caps.skills ?? []).filter((c) => c.enabled).length

  return (
    <>
      <div className="cap-actions" data-enter>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          onClick={() => { setImporting((i) => !i); setNewOpen(false) }}
          aria-expanded={importing}
        >
          <Icon name="link" size={14} /> Import a link
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={() => load(true)}>
          <Icon name="refresh" size={14} /> Rescan
        </button>
        <div className="cap-filter">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              className={`conn-tab${filter === f.id ? ' active' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span className="cap-count">{installed.length} installed · {engaged} engaged</span>
      </div>

      {newOpen && <Composer onDone={() => { setNewOpen(false); load() }} onCancel={() => setNewOpen(false)} />}

      {importing && (
        <div className="dir-install" data-enter>
          <Icon name="link" size={15} />
          <input
            autoFocus
            value={url}
            placeholder="A link to any SKILL.md"
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && url.trim()) install(url.trim()) }}
            aria-label="Skill URL"
          />
          <button
            type="button"
            className="btn btn--primary btn--small"
            disabled={busy === url.trim() || !url.trim()}
            onClick={() => install(url.trim())}
          >
            Install
          </button>
          <button
            type="button"
            className="btn btn--ghost btn--small"
            disabled={busy === url.trim() || !url.trim()}
            onClick={() => install(url.trim(), { overwrite: true })}
            title="Replace an installed skill of the same name"
          >
            Replace
          </button>
        </div>
      )}

      {catalogue.error && (
        <div className="msg-note msg-note--warning" style={{ marginBottom: 12 }} data-enter>
          <Icon name="info" size={14} />
          <span>
            The skill sources could not be read ({catalogue.error}). Installed skills are still
            listed, a direct link still installs, and New skill still writes one.
          </span>
        </div>
      )}

      {loading && shown.length === 0 && <div className="dir-empty">Reading the skill sources…</div>}

      <div className="dir-grid" data-enter>
        {shown.map((row) => {
          const capability = (caps.skills ?? []).find((c) => c.name === row.name)
          return (
            <div className="dcard" key={row.name}>
              <div className="dcard-top">
                <ServiceIcon name={row.name} kind="skill" size={34} />
                <div className="dcard-heading">
                  <span className="dcard-title">/{row.name}</span>
                  <span className="dcard-sub">{row.publisher}{row.version ? ` · v${row.version}` : ''}</span>
                </div>
                {row.installed ? (
                  <Gear
                    name={row.name}
                    capability={capability}
                    busy={busyCap === `skill:${row.name}`}
                    onToggle={() => capability && setCapEnabled(capability, !capability.enabled)}
                    onRemove={() => remove(row.name)}
                  />
                ) : (
                  <button
                    type="button"
                    className="dcard-act"
                    title={`Install /${row.name}`}
                    aria-label={`Install ${row.name}`}
                    disabled={busy === row.url}
                    onClick={() => install(row.url)}
                  >
                    <Icon name={busy === row.url ? 'refresh' : 'plus'} size={15} />
                  </button>
                )}
              </div>
              <p className="dcard-desc">{row.description}</p>
              {row.installed && (
                <div className="dcard-badges">
                  <span className={`badge${capability?.enabled ? ' badge--ok' : ''}`}>
                    {capability?.enabled ? 'engaged' : 'installed'}
                  </span>
                </div>
              )}
            </div>
          )
        })}
        {!loading && shown.length === 0 && <div className="dir-empty">Nothing matches that.</div>}
      </div>

      {errors.length > 0 && (
        <section data-enter style={{ marginTop: 24 }}>
          <div className="cap-section-head"><span>Failed to load</span><span>{errors.length}</span></div>
          <div className="card card-pad" style={{ display: 'grid', gap: 10 }}>
            {errors.map((e, i) => (
              <div key={i} className="msg-note msg-note--error" style={{ padding: '8px 12px' }}>
                <Icon name="x" size={14} />
                <span className="mono" style={{ wordBreak: 'break-all' }}>{e.path}</span>
                <span style={{ marginLeft: 'auto' }}>{e.error}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <p className="conn-foot" data-enter>
        An engaged skill is offered to the agent every turn. Typing <span className="mono">/name</span> engages
        one for a single message, whether or not it is engaged standing.
      </p>
    </>
  )
}
