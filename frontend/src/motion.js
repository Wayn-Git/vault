/* Motion helpers with no animation library behind them.

   CSS animations run off the main thread, so they hold their frame rate while
   the app is parsing a stream, mounting a list, or doing anything else that
   keeps JavaScript busy — which, in a chat client, is most of the time. The
   only thing left for JS to do is decide when an element should start. */

import { useEffect } from 'react'

/** Stagger `[data-enter]` children in once, on mount.
 *
 *  Sets a per-element `--i` and lets CSS handle the rest, so nothing here runs
 *  per frame. Stagger is decorative: it never gates interaction.
 */
export function useViewEntrance(rootRef, deps = []) {
  useEffect(() => {
    const nodes = rootRef.current?.querySelectorAll('[data-enter]')
    if (!nodes?.length) return
    nodes.forEach((node, i) => {
      node.style.setProperty('--i', String(Math.min(i, 8)))
      node.classList.add('enter')
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
