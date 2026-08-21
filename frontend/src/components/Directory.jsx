import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from './Icon.jsx'
import ServiceIcon from './ServiceIcon.jsx'
import { api } from '../api.js'
import { useApp } from '../store.jsx'

/* Everything PSOK can be given, in one browsable place.

   Skills come from their source repositories, read live: each card carries the
   name and description out of the real SKILL.md rather than a hand-written
   title that would drift the moment the source changed. Connectors come from
   the bundled MCP catalogue. Both install in one click, and both say plainly
   what they will need before they can work. */

const SORTS = [
  { id: 'name', label: 'Name' },
  { id: 'installed', label: 'Installed first' },
  { id: 'new', label: 'Not installed first' },
]

function Card({ icon, title, subtitle, description, badges, action, footer }) {
  return (
    <div className="dcard">
      <div className="dcard-top">
        {icon}
        <div className="dcard-heading">
          <span className="dcard-title">{title}</span>
          {subtitle && <span className="dcard-sub">{subtitle}</span>}
        </div>
        {action}
      </div>
      {description && <p className="dcard-desc">{description}</p>}
      {badges && <div className="dcard-badges">{badges}</div>}
      {footer}
    </div>
  )
}

function SkillGear({ skill, capability, onToggle, onRemove, busy }) {
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
        aria-label={`Manage ${skill.name}`}
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

export default function Directory() {
  const { overlay, setOverlay, caps, refreshCaps, setCapEnabled, busyCap, toast, setView, refreshHealth } = useApp()
  const open = typeof overlay === 'string' && overlay.startsWith('directory')
  const initialTab = overlay === 'directory:connectors' ? 'connectors' : 'skills'

  const [tab, setTab] = useState(initialTab)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState('new')
  const [filter, setFilter] = useState('all')
  const [installedSkills, setInstalledSkills] = useState([])
  const [catalogue, setCatalogue] = useState({ skills: [], error: null })
  const [connectors, setConnectors] = useState([])
  const [servers, setServers] = useState([])
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [catalogueLoading, setCatalogueLoading] = useState(false)

  const load = useCallback((refresh = false) => {
    const fail = (err) => toast(err.message, 'bad')
    api.skills().then((d) => setInstalledSkills(d.skills || [])).catch(fail).finally(() => setLoaded(true))
    api.mcpCatalogue().then(setConnectors).catch(fail)
    api.mcpServers().then(setServers).catch(fail)
    setCatalogueLoading(true)
    api.skillCatalogue(refresh)
      .then(setCatalogue)
      .catch((err) => setCatalogue({ skills: [], error: err.message }))
      .finally(() => setCatalogueLoading(false))
    refreshCaps()
  }, [refreshCaps, toast])

  useEffect(() => {
    if (!open) return
    setTab(initialTab)
    setQuery('')
    setLoaded(false)
    load()
  }, [open, initialTab, load])

  useEffect(() => {
    if (!open) return undefined
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setOverlay(null) } }
    document.addEventListener('keydown', key, true)
    return () => document.removeEventListener('keydown', key, true)
  }, [open, setOverlay])

  const install = useCallback(async (target, { overwrite = false, label } = {}) => {
    setBusy(label || target)
    try {
      const skill = await api.installSkill(target, overwrite)
      toast(`Installed /${skill.name}`, 'ok')
      setUrl('')
      load()
    } catch (err) {
      if (/already installed/.test(err.message)) {
        toast(`${err.message} — use Replace to update it`, 'amber')
      } else {
        toast(err.message, 'bad')
      }
    } finally {
      setBusy('')
    }
  }, [load, toast])

  const removeSkill = useCallback(async (name) => {
    try {
      await api.removeSkill(name)
      toast(`Uninstalled /${name}`, 'ok')
      load()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [load, toast])

  const addConnector = useCallback(async (entry) => {
    setBusy(entry.id)
    try {
      const result = await api.mcpAdd({ catalogue_id: entry.id })
      toast(
        result.needs_login ? `${result.name} added — sign in to finish` : `${result.name} added`,
        result.needs_login ? 'amber' : 'ok',
      )
      load()
      refreshHealth()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [load, refreshHealth, toast])

  // One row per skill, whether it came from disk, the catalogue, or both.
  const skillRows = useMemo(() => {
    const rows = new Map()
    for (const entry of catalogue.skills) {
      rows.set(entry.name, {
        name: entry.name,
        description: entry.description,
        publisher: entry.publisher,
        url: entry.url,
        installed: entry.installed,
      })
    }
    for (const skill of installedSkills) {
      const existing = rows.get(skill.name)
      rows.set(skill.name, {
        name: skill.name,
        description: skill.description || existing?.description || '',
        publisher: existing?.publisher || 'On this machine',
        url: existing?.url,
        installed: true,
        path: skill.path,
        version: skill.version,
      })
    }
    return [...rows.values()]
  }, [catalogue, installedSkills])

  const shownSkills = useMemo(() => {
    const q = query.trim().toLowerCase()
    let rows = skillRows.filter(
      (row) => !q || row.name.toLowerCase().includes(q) || (row.description || '').toLowerCase().includes(q),
    )
    if (filter === 'installed') rows = rows.filter((r) => r.installed)
    if (filter === 'available') rows = rows.filter((r) => !r.installed)
    const byName = (a, b) => a.name.localeCompare(b.name)
    if (sort === 'installed') rows = [...rows].sort((a, b) => Number(b.installed) - Number(a.installed) || byName(a, b))
    else if (sort === 'new') rows = [...rows].sort((a, b) => Number(a.installed) - Number(b.installed) || byName(a, b))
    else rows = [...rows].sort(byName)
    return rows
  }, [skillRows, query, filter, sort])

  const configuredNames = useMemo(() => new Set(servers.map((s) => s.name)), [servers])

  const shownConnectors = useMemo(() => {
    const q = query.trim().toLowerCase()
    let rows = connectors.filter(
      (c) => !q
        || c.title.toLowerCase().includes(q)
        || c.description.toLowerCase().includes(q)
        || c.category.toLowerCase().includes(q),
    )
    if (filter === 'installed') rows = rows.filter((c) => configuredNames.has(c.id))
    if (filter === 'available') rows = rows.filter((c) => !configuredNames.has(c.id))
    return rows
  }, [connectors, query, filter, configuredNames])

  const grouped = useMemo(() => {
    const groups = new Map()
    for (const entry of shownConnectors) {
      if (!groups.has(entry.category)) groups.set(entry.category, [])
      groups.get(entry.category).push(entry)
    }
    return [...groups.entries()]
  }, [shownConnectors])

  if (!open) return null

  const installedCount = skillRows.filter((r) => r.installed).length

  return (
    <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setOverlay(null) }}>
      <div className="dir" role="dialog" aria-modal="true" aria-label="Directory">
        <div className="dir-head">
          <span className="dir-title">Directory</span>
          <button
            type="button"
            className="dir-refresh"
            onClick={() => load(true)}
            title="Re-read the sources"
          >
            <Icon name="refresh" size={13} /> Refresh
          </button>
          <button type="button" className="icon-btn" onClick={() => setOverlay(null)} aria-label="Close">
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="dir-body">
          <nav className="dir-nav">
            <button
              type="button"
              className={`dir-nav-item${tab === 'skills' ? ' active' : ''}`}
              onClick={() => { setTab('skills'); setQuery('') }}
            >
              <Icon name="book" size={15} /> Skills
              <span className="dir-nav-count">{skillRows.length}</span>
            </button>
            <button
              type="button"
              className={`dir-nav-item${tab === 'connectors' ? ' active' : ''}`}
              onClick={() => { setTab('connectors'); setQuery('') }}
            >
              <Icon name="plug" size={15} /> Connectors
              <span className="dir-nav-count">{connectors.length}</span>
            </button>
          </nav>

          <div className="dir-main">
            <div className="dir-search">
              <Icon name="search" size={15} />
              <input
                autoFocus
                value={query}
                placeholder={tab === 'skills' ? 'Search skills…' : 'Search connectors…'}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search the directory"
              />
            </div>

            <div className="dir-tools">
              <span className="dir-chip">
                {tab === 'skills' ? `${installedCount} installed` : `${configuredNames.size} configured`}
              </span>
              <div className="dir-tools-right">
                <label className="dir-select">
                  Filter
                  <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                    <option value="all">All</option>
                    <option value="installed">{tab === 'skills' ? 'Installed' : 'Configured'}</option>
                    <option value="available">Not yet added</option>
                  </select>
                </label>
                {tab === 'skills' && (
                  <label className="dir-select">
                    Sort
                    <select value={sort} onChange={(e) => setSort(e.target.value)}>
                      {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                    </select>
                  </label>
                )}
              </div>
            </div>

            {tab === 'skills' ? (
              <>
                <div className="dir-install">
                  <Icon name="link" size={15} />
                  <input
                    value={url}
                    placeholder="…or paste a link to any SKILL.md"
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

                {catalogue.error && (
                  <div className="msg-note msg-note--warning" style={{ marginBottom: 12 }}>
                    <Icon name="info" size={14} />
                    <span>
                      The skill sources could not be read ({catalogue.error}). Installed skills are
                      still listed, and a direct link still installs.
                    </span>
                  </div>
                )}

                {(!loaded || catalogueLoading) && shownSkills.length === 0 && (
                  <div className="dir-empty">Reading the skill sources…</div>
                )}

                <div className="dir-grid">
                  {shownSkills.map((row) => {
                    const capability = (caps.skills ?? []).find((c) => c.name === row.name)
                    return (
                      <Card
                        key={row.name}
                        icon={<ServiceIcon name={row.name} kind="skill" size={34} />}
                        title={`/${row.name}`}
                        subtitle={`${row.publisher}${row.version ? ` · v${row.version}` : ''}`}
                        description={row.description}
                        action={row.installed ? (
                          <SkillGear
                            skill={row}
                            capability={capability}
                            busy={busyCap === `skill:${row.name}`}
                            onToggle={() => capability && setCapEnabled(capability, !capability.enabled)}
                            onRemove={() => removeSkill(row.name)}
                          />
                        ) : (
                          <button
                            type="button"
                            className="dcard-act"
                            title={`Install /${row.name}`}
                            aria-label={`Install ${row.name}`}
                            disabled={busy === row.url}
                            onClick={() => install(row.url, { label: row.url })}
                          >
                            <Icon name={busy === row.url ? 'refresh' : 'plus'} size={15} />
                          </button>
                        )}
                        badges={row.installed && (
                          <span className={`badge${capability?.enabled ? ' badge--ok' : ''}`}>
                            {capability?.enabled ? 'engaged' : 'installed'}
                          </span>
                        )}
                      />
                    )
                  })}
                  {loaded && !catalogueLoading && shownSkills.length === 0 && (
                    <div className="dir-empty">Nothing matches that.</div>
                  )}
                </div>
              </>
            ) : (
              <>
                {grouped.map(([category, entries]) => (
                  <section key={category} className="dir-section">
                    <div className="dir-section-head">
                      <span>{category}</span>
                      <span className="dir-section-count">{entries.length}</span>
                    </div>
                    <div className="dir-grid">
                      {entries.map((entry) => {
                        const configured = configuredNames.has(entry.id)
                        const server = servers.find((s) => s.name === entry.id)
                        return (
                          <Card
                            key={entry.id}
                            icon={<ServiceIcon name={entry.id} size={34} />}
                            title={entry.title}
                            subtitle={entry.requires || entry.transport}
                            description={entry.description}
                            action={configured ? (
                              <button
                                type="button"
                                className="dcard-act dcard-act--done"
                                title="Already added — open its settings"
                                onClick={() => { setView('mcp'); setOverlay(null) }}
                              >
                                <Icon name="check" size={15} />
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="dcard-act"
                                disabled={busy === entry.id}
                                title={`Add ${entry.title}`}
                                aria-label={`Add ${entry.title}`}
                                onClick={() => addConnector(entry)}
                              >
                                <Icon name={busy === entry.id ? 'refresh' : 'plus'} size={15} />
                              </button>
                            )}
                            badges={
                              <>
                                <span className="badge">{entry.auth === 'none' ? 'no sign-in' : entry.auth}</span>
                                {configured && server?.authorized === false && (
                                  <span className="badge badge--amber">needs sign-in</span>
                                )}
                                {configured && <span className="badge badge--ok">added</span>}
                              </>
                            }
                            footer={entry.setup_hint && (
                              <details className="dir-setup">
                                <summary>What this needs first</summary>
                                <pre>{entry.setup_hint}</pre>
                              </details>
                            )}
                          />
                        )
                      })}
                    </div>
                  </section>
                ))}
                {shownConnectors.length === 0 && <div className="dir-empty">Nothing matches that.</div>}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
