import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../gsapFx.js'
import { api } from '../api.js'

export default function Skills() {
  const rootRef = useRef(null)
  const { toast } = useApp()
  const [data, setData] = useState(null)
  useViewEntrance(rootRef)

  const load = useCallback(async () => {
    try {
      setData(await api.skills())
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const skills = data?.skills ?? []
  const errors = data?.errors ?? []

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <div className="vheader-eyebrow">
              <span className="led led--amber" /> sys / knowledge
            </div>
            <h1>Skills</h1>
            <div className="vheader-sub">
              Markdown skill files discovered on disk. The agent reads the ones it needs
              through the ordinary view_file tool — no invoke_skill, by design.
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--ghost" onClick={load}>
              <Icon name="refresh" size={15} /> Rescan
            </button>
          </div>
        </header>

        <div style={{ display: 'flex', gap: 8, marginBottom: 16 }} data-enter>
          <span className="badge badge--amber">{skills.length} discovered</span>
          {errors.length > 0 && <span className="badge badge--bad">{errors.length} broken</span>}
        </div>

        {skills.length === 0 && !errors.length && (
          <div className="card empty-state" data-enter>
            <Icon name="book" size={22} />
            No skills found. Create ~/.psok/skills/&lt;name&gt;/SKILL.md with YAML frontmatter
            (name + description) and rescan.
          </div>
        )}

        <div className="skill-grid">
          {skills.map((s) => (
            <div className="skill-card" key={s.path} data-enter>
              <div className="skill-name">
                <span className={`led led--${s.version ? 'ok' : 'info'}`} />
                {s.name}
                {s.version && <span className="badge">v{s.version}</span>}
              </div>
              <div className="skill-desc">{s.description}</div>
              <div className="skill-path">{s.path}</div>
            </div>
          ))}
        </div>

        {errors.length > 0 && (
          <div style={{ marginTop: 30 }} data-enter>
            <div className="card-title"><span className="led led--bad" /> failed to load</div>
            <div className="card card-pad" style={{ display: 'grid', gap: 10 }}>
              {errors.map((e, i) => (
                <div key={i} className="msg-note msg-note--error" style={{ padding: '8px 12px' }}>
                  <Icon name="x" size={14} />
                  <span className="mono" style={{ wordBreak: 'break-all' }}>{e.path}</span>
                  <span style={{ marginLeft: 'auto' }}>{e.error}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}