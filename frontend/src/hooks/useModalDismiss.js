import { useEffect } from 'react'

/* Escape-to-close for an open overlay. Extracted from what Settings already
 * did inline -- capture phase, so it wins over whatever is focused inside. */
export function useModalDismiss(open, onClose) {
  useEffect(() => {
    if (!open) return undefined
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose() } }
    document.addEventListener('keydown', key, true)
    return () => document.removeEventListener('keydown', key, true)
  }, [open, onClose])
}

/** Backdrop click closes, a click inside the panel does not. */
export function onOverlayMouseDown(onClose) {
  return (e) => { if (e.target === e.currentTarget) onClose() }
}
