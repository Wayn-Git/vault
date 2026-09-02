import { useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { api } from '../api.js'
import { useDismiss } from '../hooks/useDismiss.js'

/* Which model answers the next message.

   Providers come from providers.yaml, and each declares a default model. A
   model that is not the declared default is still legitimate -- any name the
   endpoint accepts works -- so the list is a shortcut, not a whitelist, and the
   field below it takes anything. */

export default function ModelMenu({ provider, model, onChange, onClose, scoped, placement = 'up' }) {
  const { health } = useApp()
  const ref = useRef(null)
  const [custom, setCustom] = useState(model || '')
  // The selected provider's live model list, so the field is a menu and not
  // just a text box. Best-effort: an endpoint that will not answer leaves the
  // datalist empty and the free-text field working exactly as before.
  const [models, setModels] = useState([])

  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}
  /* Configured and not answering. Having a key is not the same as being
     reachable: a local endpoint declares no key at all, so `has_key` called
     Ollama configured by definition and this menu offered it while nothing
     was listening on its port -- nine consecutive `All connection attempts
     failed` in the real database. Still listed, because the user configured
     it on purpose; picking one is what says why it will not work. */
  const unavailable = health?.providers_unavailable ?? {}

  useDismiss(ref, true, { onAway: onClose })

  useEffect(() => {
    let live = true
    if (!provider) { setModels([]); return }
    api.providerModels(provider)
      .then((r) => { if (live) setModels(r.models || []) })
      .catch(() => { if (live) setModels([]) })
    return () => { live = false }
  }, [provider])

  return (
    <div className={`menu menu--right${placement === "down" ? " menu--down" : ""}`} ref={ref} role="menu">
      <div className="menu-flyout-head">
        {scoped ? 'model for this conversation' : 'model for the next conversation'}
      </div>
      {providers.length === 0 && (
        <div className="menu-empty">
          No providers configured. Add one in Settings → Models.
        </div>
      )}
      {providers.map((name) => {
        const suggested = defaults[name]
        const current = name === provider
        const down = unavailable[name]
        return (
          <button
            key={name}
            type="button"
            className={`menu-row${current ? ' active' : ''}${down ? ' menu-row--down' : ''}`}
            title={down || undefined}
            onClick={() => {
              onChange({ provider: name, ...(suggested ? { model: suggested } : {}) })
              setCustom(suggested || '')
            }}
          >
            <span className="menu-gutter" />
            <span className="menu-label">
              {name}
              <span className="menu-hint">
                {down ? 'not answering' : (suggested || 'no default model')}
              </span>
            </span>
            {current && <Icon name="check" size={14} />}
          </button>
        )
      })}
      <div className="menu-sep" />
      <div className="menu-pad">
        <label className="menu-field-label" htmlFor="model-name">
          model name{models.length > 0 ? ` · ${models.length} from ${provider}${models.some((m) => m.free) ? `, ${models.filter((m) => m.free).length} free` : ''}` : ''}
        </label>
        <input
          id="model-name"
          className="menu-input"
          list="model-menu-models"
          value={custom}
          placeholder={models.length ? 'pick one, or type any name' : 'any name the endpoint accepts'}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && custom.trim()) { onChange({ model: custom.trim() }); onClose() }
          }}
        />
        <datalist id="model-menu-models">
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.free ? 'free — ' : ''}{m.id}</option>
          ))}
        </datalist>
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
