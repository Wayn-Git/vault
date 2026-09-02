/* A destructive action asks one question and waits for an answer -- the same
 * shape as `window.confirm`, minus the browser chrome nobody chose. This is a
 * module-level singleton rather than store.jsx state: only one dialog is ever
 * open at a time, and nothing outside the dialog itself needs to react to it,
 * so it doesn't belong in the context every component re-renders from. */

const listeners = new Set()
let state = null

function emit() {
  listeners.forEach((fn) => fn(state))
}

export function onConfirmState(fn) {
  listeners.add(fn)
  fn(state)
  return () => listeners.delete(fn)
}

/**
 * confirm({ title, description, confirmLabel, cancelLabel, tone })
 * Resolves true if confirmed, false if cancelled or dismissed.
 */
export function confirm(options) {
  return new Promise((resolve) => {
    state = { ...options, resolve }
    emit()
  })
}

export function resolveConfirm(value) {
  state?.resolve(value)
  state = null
  emit()
}
