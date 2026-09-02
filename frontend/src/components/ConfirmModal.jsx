import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api, prettyJSON } from '../api.js'
import { useFocusTrap } from '../hooks/useFocusTrap.js'

/* The turn is suspended while this is up, so answering it has to be as fast as
   the keyboard: Enter allows, Escape denies, R arms "remember". The Allow
   button takes focus on mount for the same reason -- the answer should never
   require finding the mouse. */

export default function ConfirmModal({ pending, onDecide }) {
  const [remember, setRemember] = useState(false)
  const [busy, setBusy] = useState(null)
  const allowRef = useRef(null)
  const panelRef = useRef(null)
  const item = pending.length ? pending[pending.length - 1] : null

  // The gate refuses to honour a standing preference for a sensitive path, so
  // offering to store one here would be offering something that does nothing.
  // Read above the hooks because the keyboard shortcut has to know it too.
  const sensitive = /sensitive path/i.test(item?.reason || '')

  useFocusTrap(panelRef, Boolean(item))

  const decide = useCallback(async (target, allow) => {
    if (!target) return
    setBusy(target.id)
    try {
      await api.decideConfirmation(target.id, { allow, remember })
      onDecide(target.id)
    } catch (err) {
      // the turn may have resolved on its own; drop it either way
      onDecide(target.id, err.message)
    } finally {
      setBusy(null)
      setRemember(false)
    }
  }, [onDecide, remember])

  useEffect(() => {
    if (!item) return undefined
    allowRef.current?.focus()
    const key = (e) => {
      /* A modifier means the chord belongs to the browser or to the operating
         system, never to this dialog. Without this check `r` swallowed Ctrl+R
         and Cmd+R, so the page could not be reloaded while a permission prompt
         was up — and a prompt is exactly when someone reaches for reload. */
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const typing = e.target?.tagName === 'INPUT'
        || e.target?.tagName === 'TEXTAREA'
        || e.target?.isContentEditable
      if (typing && e.key !== 'Escape') return
      if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); decide(item, true) }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); decide(item, false) }
      // Only when a preference can actually be stored: on a sensitive path the
      // gate refuses to honour one, so the checkbox is disabled and a shortcut
      // that silently flipped it would be a control that does nothing.
      else if (!sensitive && e.key.toLowerCase?.() === 'r') { e.preventDefault(); setRemember((r) => !r) }
    }
    document.addEventListener('keydown', key, true)
    return () => document.removeEventListener('keydown', key, true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item, decide, sensitive])

  if (!item) return null

  // The default reason restates the sentence above it word for word. Only a
  // reason that says something new -- an escalation, a sensitive path -- earns
  // the space.
  const reason = item.reason && !/^\S+ is rated \w+ risk\.?$/.test(item.reason.trim())
    ? item.reason
    : null

  return (
    <div className="modal-overlay confirm-overlay">
      <div className="modal confirm-modal" ref={panelRef} role="dialog" aria-modal="true" aria-label="Permission required">
        <div className="modal-head">
          <div>
            <div className="vheader-eyebrow">permission gate</div>
            <div className="modal-title">Approve tool call?</div>
          </div>
        </div>

        <div className={`msg-note ${sensitive ? 'msg-note--error' : 'msg-note--guard'}`} style={{ marginBottom: 14 }}>
          <Icon name="key" size={15} />
          <span>
            <strong className="mono">{item.tool_name}</strong> is a <strong>{item.risk}</strong>-risk operation.
            {reason ? ` ${reason}.` : ''}
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
            style={{ accentColor: 'var(--confirm)', marginTop: 2 }}
          />
          <span>
            Remember this decision for{' '}
            <strong className="mono" style={{ color: 'var(--text)' }}>{item.operation_key || item.tool_name}</strong>
            <kbd className="kbd" style={{ marginLeft: 6 }}>R</kbd>
            <span style={{ display: 'block', color: 'var(--text-faint)', marginTop: 3 }}>
              {sensitive
                ? 'Not available here: a path like this always asks, and no stored preference can silence it.'
                : 'The operation key, not the tool name — approving a read-only command does not approve a destructive one.'}
            </span>
          </span>
        </label>

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            type="button"
            ref={allowRef}
            className="btn btn--primary"
            disabled={busy === item.id}
            onClick={() => decide(item, true)}
          >
            <Icon name="check" size={15} /> Allow <kbd className="kbd">Enter</kbd>
          </button>
          <button type="button" className="btn btn--danger" disabled={busy === item.id} onClick={() => decide(item, false)}>
            <Icon name="x" size={15} /> Deny <kbd className="kbd">Esc</kbd>
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