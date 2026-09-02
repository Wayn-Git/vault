/* The one list of what pages exist.
 *
 * This used to be four hand-maintained lists (App.jsx's keybindings, the
 * rail, the command palette, Settings' "Pages" links) that had already
 * drifted apart -- different labels for the same place, Settings missing a
 * link to Mail entirely, a beta marker baked into one label string and not
 * the others. One registry, one place to add a view. */

export const NAV = [
  { id: 'chat', path: '/chat', label: 'Chat', icon: 'chat', digit: 1 },
  { id: 'tasks', path: '/tasks', label: 'Tasks', icon: 'check', digit: 2, rail: true, settings: true },
  { id: 'mail', path: '/mail', label: 'Mail', icon: 'mail', digit: 3, rail: true, settings: true },
  { id: 'capabilities', path: '/capabilities', label: 'Skills & connectors', icon: 'grid', digit: 4, rail: true, settings: true },
  { id: 'automations', path: '/automations', label: 'Automations', icon: 'clock', digit: 5, rail: true, settings: true, beta: true },
  { id: 'memory', path: '/memory', label: 'Memory', icon: 'spark', digit: 6, rail: true, settings: true },
  { id: 'logs', path: '/logs', label: 'Activity', icon: 'logs', digit: 7, rail: true, settings: true },
  // No digit, no rail entry, no Settings link: reached only from the
  // degraded/offline banner or the command palette. That's an existing
  // product decision, not an oversight this file is fixing.
  { id: 'dash', path: '/dash', label: 'Status', icon: 'dash' },
]

export const byId = (id) => NAV.find((n) => n.id === id)
export const forRail = () => NAV.filter((n) => n.rail)
export const forSettings = () => NAV.filter((n) => n.settings)
export const forPalette = () => NAV
export const byDigit = (n) => NAV.find((v) => v.digit === n)
export const pathFor = (id) => byId(id)?.path ?? '/chat'
