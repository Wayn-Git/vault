/* What a connector row should say about itself.
 *
 * "Switched on" and "actually running" are different facts, and a row that
 * reports only the first is what made connectors look enabled while the agent
 * had none of their tools. Lives in its own module because three surfaces read
 * it -- the + menu, the command palette and the connectors page -- and it was
 * previously exported from PlusMenu, which made the menu a dependency of
 * anything that wanted to describe a connector.
 */
export function connectorState(cap, busy) {
  const live = cap.live || {}
  if (busy) return { tone: 'busy', label: 'starting', dot: 'amber' }
  // Tools in the registry outrank a recorded error, and this ordering is the
  // point. `live.error` used to be checked first, so one transient spawn or
  // OAuth failure -- a string nothing cleared -- rendered "failed" beside a
  // connector whose tools the agent was calling. The backend only reports an
  // error once the server has genuinely stopped serving them.
  if (live.ready || live.tools > 0) {
    return { tone: 'live', label: `Ready (${live.tools} tools)`, dot: 'ok' }
  }
  if (live.error) return { tone: 'error', label: 'failed', dot: 'bad', detail: live.error }
  if (live.connected) return { tone: 'live', label: `Ready (${live.tools} tools)`, dot: 'ok' }
  if (cap.enabled) return { tone: 'idle', label: 'not running', dot: 'faint' }
  return { tone: 'off', label: 'off', dot: 'faint' }
}
