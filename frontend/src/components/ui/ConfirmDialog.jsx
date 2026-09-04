import { useEffect, useRef, useState } from 'react'
import Icon from '../Icon.jsx'
import { useModalDismiss, onOverlayMouseDown } from '../../hooks/useModalDismiss.js'
import { onConfirmState, confirm, resolveConfirm } from './confirmStore.js'
import { useFocusTrap } from '../../hooks/useFocusTrap.js'

/** `const confirm = useConfirm(); if (await confirm({ title, description })) …` */
export function useConfirm() {
  return confirm
}

/* Cancel takes focus, not the destructive action -- unlike ConfirmModal's
 * permission gate (Enter = Allow), an accidental Enter here should do
 * nothing rather than delete something. Mount this once, near the other
 * overlays in App.jsx. */
export default function ConfirmDialogHost() {
  const [item, setItem] = useState(null)
  const cancelRef = useRef(null)
  const panelRef = useRef(null)

  useEffect(() => onConfirmState(setItem), [])
  useModalDismiss(!!item, () => resolveConfirm(false))
  useFocusTrap(panelRef, !!item)

  useEffect(() => {
    if (item) cancelRef.current?.focus()
  }, [item])

  if (!item) return null

  const {
    title, description, confirmLabel = 'Confirm', cancelLabel = 'Cancel', tone = 'default',
  } = item

  return (
    <div className="modal-overlay" onMouseDown={onOverlayMouseDown(() => resolveConfirm(false))}>
      <div className="modal" ref={panelRef} role="alertdialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          <button type="button" className="icon-btn modal-close" onClick={() => resolveConfirm(false)} aria-label="Cancel">
            <Icon name="x" size={16} />
          </button>
        </div>
        {description && <p style={{ color: 'var(--text-dim)', marginBottom: 18 }}>{description}</p>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button type="button" ref={cancelRef} className="btn btn--ghost" onClick={() => resolveConfirm(false)}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`btn ${tone === 'danger' ? 'btn--danger' : 'btn--primary'}`}
            onClick={() => resolveConfirm(true)}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
