import { useState } from 'react'
import Icon from './Icon.jsx'
import { prettyJSON } from '../api.js'

export default function ToolCallCard({ call, running }) {
  const [open, setOpen] = useState(false)

  const status = call.status === 'error'
    ? <span className="badge badge--bad">error</span>
    : running
      ? <span className="badge badge--amber"><span className="led led--amber led--pulse" />running</span>
      : <span className="badge badge--ok">done</span>

  return (
    <div className="tool-card">
      <button type="button" className="tool-card-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="term" size={14} />
        <span className="tool-name">{call.name}</span>
        {status}
        <Icon
          name="chevron"
          size={13}
          style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 160ms ease' }}
        />
      </button>
      <div className={`tool-body${open ? ' open' : ''}`}>
        <div>
          <div className="tool-block">
            <span className="tool-block-label">arguments</span>
            <pre className="tool-json">{prettyJSON(call.arguments)}</pre>
            {call.content !== undefined && (
              <>
                <span className="tool-block-label">result</span>
                <pre className={`tool-json${call.status === 'error' ? ' tool-result--error' : ''}`}>
                  {String(call.content)}
                </pre>
              </>
            )}
            {running && (
              <span className="tool-block-label" style={{ color: 'var(--amber)' }}>
                <span className="led led--amber led--pulse" /> awaiting completion…
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}