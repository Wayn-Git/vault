/* The keyboard layer's vocabulary.

   One normalising function turns a KeyboardEvent into a string like `mod+k`,
   and every binding is written in that form. `mod` is Command on a Mac and
   Control everywhere else, which is the only platform difference the interface
   has to carry. */

export const IS_MAC = typeof navigator !== 'undefined'
  && /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || navigator.userAgent)

export const MOD_LABEL = IS_MAC ? '⌘' : 'Ctrl'
export const ALT_LABEL = IS_MAC ? '⌥' : 'Alt'

/** True when the event came from somewhere the user is writing prose. */
export function isTyping(target) {
  if (!target) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

/** KeyboardEvent -> `mod+shift+k`. Modifier order is fixed so bindings compare as strings. */
export function chord(e) {
  const parts = []
  if (IS_MAC ? e.metaKey : e.ctrlKey) parts.push('mod')
  // The other modifier still matters: ctrl+k on a Mac is not the same chord.
  if (IS_MAC ? e.ctrlKey : e.metaKey) parts.push('ctrl')
  if (e.altKey) parts.push('alt')
  if (e.shiftKey) parts.push('shift')
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase()
  parts.push(key)
  return parts.join('+')
}

/** `mod+shift+o` -> `⌘ ⇧ O`, for display only. */
export function pretty(binding) {
  return binding.split('+').map((part) => {
    if (part === 'mod') return MOD_LABEL
    if (part === 'ctrl') return 'Ctrl'
    if (part === 'alt') return ALT_LABEL
    if (part === 'shift') return IS_MAC ? '⇧' : 'Shift'
    if (part === 'escape') return 'Esc'
    if (part === 'enter') return IS_MAC ? '↩' : 'Enter'
    if (part === 'arrowup') return '↑'
    if (part === 'arrowdown') return '↓'
    if (part === ' ') return 'Space'
    return part.length === 1 ? part.toUpperCase() : part
  })
}

export const SHORTCUTS = [
  { group: 'Anywhere', binding: 'mod+k', label: 'Command palette — everything, searchable' },
  { group: 'Anywhere', binding: 'mod+shift+o', label: 'New conversation' },
  { group: 'Anywhere', binding: 'mod+l', label: 'Focus the composer' },
  { group: 'Anywhere', binding: 'mod+/', label: 'Files, skills, connectors' },
  { group: 'Anywhere', binding: 'mod+u', label: 'Attach a file' },
  { group: 'Anywhere', binding: 'mod+,', label: 'Settings' },
  { group: 'Anywhere', binding: 'mod+m', label: 'Memory on or off' },
  { group: 'Anywhere', binding: 'mod+b', label: 'Show or hide the rail' },
  { group: 'Anywhere', binding: 'mod+1…9', label: 'Jump to a view' },
  { group: 'Anywhere', binding: 'shift+?', label: 'This list' },
  { group: 'Anywhere', binding: 'escape', label: 'Close what is open, or stop the turn' },

  { group: 'Composer', binding: 'enter', label: 'Send' },
  { group: 'Composer', binding: 'shift+enter', label: 'New line' },
  { group: 'Composer', binding: '/', label: 'Engage a skill by name' },
  { group: 'Composer', binding: 'arrowup', label: 'Edit the last thing you sent (empty composer)' },

  { group: 'Conversations', binding: 'mod+arrowup', label: 'Previous conversation' },
  { group: 'Conversations', binding: 'mod+arrowdown', label: 'Next conversation' },
  { group: 'Conversations', binding: 'f2', label: 'Rename the open conversation' },
  { group: 'Conversations', binding: 'mod+p', label: 'Pin or unpin the last answer' },

  { group: 'Permission prompt', binding: 'enter', label: 'Allow' },
  { group: 'Permission prompt', binding: 'escape', label: 'Deny' },
  { group: 'Permission prompt', binding: 'r', label: 'Remember this decision' },
]
