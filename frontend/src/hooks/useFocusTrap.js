import { useEffect } from 'react'

/* Keep Tab inside an open dialog, and give focus back when it closes.
 *
 * Every overlay in this application was `role="dialog" aria-modal="true"` over
 * a page that was still fully tabbable: three presses of Tab from a permission
 * prompt and the focus ring was in the composer behind it, on controls the
 * dialog was supposed to be blocking. `aria-modal` is a promise to a screen
 * reader; this is the part that keeps it.
 *
 * Deliberately not a library. The whole behaviour is one selector, one wrap at
 * each end, and remembering where focus came from. */

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusable(root) {
  return [...root.querySelectorAll(FOCUSABLE)].filter((el) => (
    // `offsetParent` is null for anything `display: none`, which is how a
    // collapsed section's buttons used to end up in the tab order.
    el.offsetParent !== null || el === document.activeElement
  ))
}

export function useFocusTrap(ref, active) {
  useEffect(() => {
    if (!active) return undefined
    const root = ref.current
    if (!root) return undefined
    const returnTo = document.activeElement

    const onKey = (e) => {
      if (e.key !== 'Tab') return
      const stops = focusable(root)
      if (stops.length === 0) { e.preventDefault(); return }
      const first = stops[0]
      const last = stops[stops.length - 1]
      // Focus already outside — a click on the backdrop, say — comes back in
      // rather than continuing into the page the dialog is covering.
      if (!root.contains(document.activeElement)) {
        e.preventDefault()
        ;(e.shiftKey ? last : first).focus()
        return
      }
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }

    root.addEventListener('keydown', onKey)
    document.addEventListener('keydown', onKey)
    return () => {
      root.removeEventListener('keydown', onKey)
      document.removeEventListener('keydown', onKey)
      // Back where it came from, if that element is still on the page. Losing
      // focus to `<body>` is how a keyboard user ends up starting over from
      // the top of the document every time they close something.
      if (returnTo instanceof HTMLElement && returnTo.isConnected) returnTo.focus()
    }
  }, [ref, active])
}
