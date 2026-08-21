import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'

/* Which model answers the next message.

   Providers come from providers.yaml, and each declares a default model. A
   model that is not the declared default is still legitimate -- any name the
   endpoint accepts works -- so the list is a shortcut, not a whitelist, and the
   field below it takes anything. */

export default function ModelMenu({ provider, model, onChange, onClose, scoped }) {
  const { health } = useApp()
  const ref = useRef(null)
  const [custom, setCustom] = useState(model || '')

  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}

  useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key, true)
    }
  }, [onClose])

  return (
    <div className="menu menu--right" ref={ref} role="menu">
      <div className="menu-flyout-head">
        {scoped ? 'model for this conversation' : 'model for the next conversation'}
      </div>
      {providers.length === 0 && (
        <div className="menu-empty">
          No providers configured. Add one to ~/.psok/config/providers.yaml.
        </div>
      )}
      {providers.map((name) => {
        const suggested = defaults[name]
        const current = name === provider
        return (
          <button
            key={name}
            type="button"
            className={`menu-row${current ? ' active' : ''}`}
            onClick={() => {
              onChange({ provider: name, ...(suggested ? { model: suggested } : {}) })
              setCustom(suggested || '')
            }}
          >
            <span className="menu-gutter" />
            <span className="menu-label">
              {name}
              <span className="menu-hint">{suggested || 'no default model'}</span>
            </span>
            {current && <Icon name="check" size={14} />}
          </button>
        )
      })}
      <div className="menu-sep" />
      <div className="menu-pad">
        <label className="menu-field-label" htmlFor="model-name">model name</label>
        <input
          id="model-name"
          className="menu-input"
          value={custom}
          placeholder="any name the endpoint accepts"
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && custom.trim()) { onChange({ model: custom.trim() }); onClose() }
          }}
        />
        <button
          type="button"
          className="btn btn--primary btn--small"
          style={{ marginTop: 8 }}
          disabled={!custom.trim() || custom.trim() === model}
          onClick={() => { onChange({ model: custom.trim() }); onClose() }}
        >
          Use this model
        </button>
      </div>
    </div>
  )
}
