import { useEffect } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { SHORTCUTS, pretty } from '../keys.js'

export default function Shortcuts() {
  const { overlay, setOverlay } = useApp()
  const open = overlay === 'shortcuts'

  useEffect(() => {
    if (!open) return
    const key = (e) => { if (e.key === 'Escape') setOverlay(null) }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [open, setOverlay])

  if (!open) return null

  const groups = SHORTCUTS.reduce((acc, s) => {
    (acc[s.group] ||= []).push(s)
    return acc
  }, {})

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => { if (e.target === e.currentTarget) setOverlay(null) }}
    >
      <div className="modal shortcuts-modal" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts">
        <div className="modal-head">
          <div>
            <div className="vheader-eyebrow"><Icon name="keyboard" size={14} /> keyboard</div>
            <div className="modal-title">Shortcuts</div>
          </div>
          <button type="button" className="icon-btn" onClick={() => setOverlay(null)} aria-label="Close">
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="shortcuts-grid">
          {Object.entries(groups).map(([group, rows]) => (
            <section key={group}>
              <h3 className="shortcuts-group">{group}</h3>
              {rows.map((row) => (
                <div key={`${group}-${row.binding}-${row.label}`} className="shortcut-row">
                  <span className="shortcut-keys">
                    {pretty(row.binding).map((k, i) => <kbd key={i} className="kbd">{k}</kbd>)}
                  </span>
                  <span className="shortcut-label">{row.label}</span>
                </div>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
