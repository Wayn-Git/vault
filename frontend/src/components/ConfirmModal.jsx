import { useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import Icon from './Icon.jsx'
import { api, prettyJSON } from '../api.js'

export default function ConfirmModal({ pending, onDecide }) {
  const [remember, setRemember] = useState(false)
  const [busy, setBusy] = useState(null)

  useGSAP(
    () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      const modal = document.querySelector('.confirm-modal')
      const overlay = document.querySelector('.confirm-overlay')
      if (modal) {
        gsap.fromTo(modal, { autoAlpha: 0, y: 14, scale: 0.98 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.28, ease: 'power2.out' })
      }
      if (overlay) {
        gsap.fromTo(overlay, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.18 })
      }
    },
    { dependencies: [pending.length] },
  )

  if (!pending.length) return null

  const decide = async (item, allow) => {
    setBusy(item.id)
    try {
      await api.decideConfirmation(item.id, { allow, remember })
      onDecide(item.id)
    } catch (err) {
      // the turn may have resolved on its own; drop it either way
      onDecide(item.id, err.message)
    } finally {
      setBusy(null)
      setRemember(false)
    }
  }

  const item = pending[pending.length - 1]
  // The gate refuses to honour a standing preference for a sensitive path, so
  // offering to store one here would be offering something that does nothing.
  const sensitive = /sensitive path/i.test(item.reason || '')

  return (
    <div className="modal-overlay confirm-overlay">
      <div className="modal confirm-modal" role="dialog" aria-modal="true" aria-label="Permission required">
        <div className="modal-head">
          <div>
            <div className="vheader-eyebrow">
              <span className="led led--amber led--pulse" /> permission gate
            </div>
            <div className="modal-title">Approve tool call?</div>
          </div>
        </div>

        <div className={`msg-note ${sensitive ? 'msg-note--error' : 'msg-note--guard'}`} style={{ marginBottom: 14 }}>
          <Icon name="key" size={15} />
          <span>
            <strong className="mono">{item.tool_name}</strong> is a <strong>{item.risk}</strong>-risk operation.
            {item.reason ? ` ${item.reason}.` : ''}
          </span>
        </div>

        <div className="tool-card" style={{ maxWidth: '100%', marginBottom: 14 }}>
          <div className="tool-block">
            <span className="tool-block-label">arguments</span>
            <pre className="tool-json">{prettyJSON(item.arguments)}</pre>
          </div>
        </div>

        <label
          style={{
            display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 16,
            fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-dim)',
            cursor: sensitive ? 'not-allowed' : 'pointer',
          }}
        >
          <input
            type="checkbox"
            checked={remember && !sensitive}
            onChange={(e) => setRemember(e.target.checked)}
            disabled={sensitive}
            style={{ accentColor: 'var(--clay)', marginTop: 2 }}
          />
          <span>
            Remember this decision for{' '}
            <strong className="mono" style={{ color: 'var(--text)' }}>{item.operation_key || item.tool_name}</strong>
            <span style={{ display: 'block', color: 'var(--text-faint)', marginTop: 3 }}>
              {sensitive
                ? 'Not available here: a path like this always asks, and no stored preference can silence it.'
                : 'The operation key, not the tool name — approving a read-only command does not approve a destructive one.'}
            </span>
          </span>
        </label>

        <div style={{ display: 'flex', gap: 10 }}>
          <button type="button" className="btn btn--primary" disabled={busy === item.id} onClick={() => decide(item, true)}>
            <Icon name="check" size={15} /> Allow
          </button>
          <button type="button" className="btn btn--danger" disabled={busy === item.id} onClick={() => decide(item, false)}>
            <Icon name="x" size={15} /> Deny
          </button>
        </div>

        {pending.length > 1 && (
          <p className="mono" style={{ marginTop: 14, fontSize: 11, color: 'var(--text-faint)' }}>
            {pending.length} request{pending.length > 1 ? 's' : ''} waiting — the newest is shown first.
          </p>
        )}
      </div>
    </div>
  )
}