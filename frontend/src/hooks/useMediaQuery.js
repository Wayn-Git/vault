import { useSyncExternalStore } from 'react'

/* One subscription per query, shared by every component that asks for it.
 *
 * `useSyncExternalStore` rather than `useState` + an effect: the first render
 * already knows the answer, so a phone does not paint the desktop shell for a
 * frame and then swap it. That flash is the whole reason a layout that reads
 * the viewport in an effect looks broken on a slow device. */

const stores = new Map()

function storeFor(query) {
  let store = stores.get(query)
  if (store) return store
  const list = window.matchMedia(query)
  const watchers = new Set()
  const relay = () => watchers.forEach((fn) => fn())
  store = {
    subscribe(fn) {
      watchers.add(fn)
      if (watchers.size === 1) list.addEventListener('change', relay)
      return () => {
        watchers.delete(fn)
        if (watchers.size === 0) list.removeEventListener('change', relay)
      }
    },
    get: () => list.matches,
  }
  stores.set(query, store)
  return store
}

const noMatch = () => false
const noSubscribe = () => () => {}

export function useMediaQuery(query) {
  const canMatch = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const store = canMatch ? storeFor(query) : null
  return useSyncExternalStore(
    store ? store.subscribe : noSubscribe,
    store ? store.get : noMatch,
    noMatch,
  )
}

/* The one breakpoint that changes the shape of the application rather than the
   size of its parts: below it the rail is a drawer over the page instead of a
   column beside it. Written once here so the JavaScript that decides how the
   rail behaves and the CSS that draws it cannot drift apart. */
export const COMPACT_QUERY = '(max-width: 859.98px)'

export const useCompact = () => useMediaQuery(COMPACT_QUERY)
