import { useEffect } from 'react'

/* Away-click + Escape-close for an open menu or flyout, hand-rolled
 * identically in three places before this. Escape is a callback rather than
 * always "close" because one of those three (the + menu) closes one nested
 * level at a time instead of the whole thing -- the content each menu holds
 * is too different to also share a `<Menu>` component, but this listener
 * pair was pure duplication. */
export function useDismiss(ref, active, { onAway, onEscape = onAway } = {}) {
  useEffect(() => {
    if (!active) return undefined
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onAway?.() }
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onEscape?.() } }
    /* `pointerdown`, not `mousedown`: a touch only produces a synthesised
       mouse event after the tap has finished, and browsers suppress it
       entirely in some cases -- so an open menu could survive a tap outside
       it and need a second one. */
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', key, true)
    }
  }, [ref, active, onAway, onEscape])
}
