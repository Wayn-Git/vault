import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { api } from '../api.js'
import { pretty } from '../keys.js'
import { connectorState } from './PlusMenu.jsx'

/* One list for everything the interface can do.

   Skills and connectors are commands here, not settings buried in a panel:
   "turn on the thing, then ask" is one gesture rather than a detour. The list
   is built from the same store the + menu reads, so a connector toggled from
   here and one toggled from there run the identical code path. */

const VIEWS = [
  { id: 'chat', label: 'Chat', icon: 'chat', binding: 'mod+1' },
  { id: 'tasks', label: 'Tasks and calendar', icon: 'check', binding: 'mod+2' },
  { id: 'skills', label: 'Skills', icon: 'book', binding: 'mod+3' },
  { id: 'mcp', label: 'Connectors', icon: 'plug', binding: 'mod+4' },
  { id: 'memory', label: 'Memory', icon: 'spark', binding: 'mod+5' },
  { id: 'logs', label: 'Activity', icon: 'logs', binding: 'mod+6' },
  { id: 'dash', label: 'Status', icon: 'dash' },
]

/** Subsequence match: `gwt` finds `go with tools`. Returns a score, or -1. */
function score(haystack, needle) {
  if (!needle) return 0
  const h = haystack.toLowerCase()
  const n = needle.toLowerCase()
  const direct = h.indexOf(n)
  if (direct !== -1) return 1000 - direct - (h.length - n.length) * 0.1
  let i = 0
  let hits = 0
  let last = -1
  let gaps = 0
  for (let c = 0; c < h.length && i < n.length; c++) {
    if (h[c] === n[i]) {
      if (last !== -1) gaps += c - last - 1
      last = c
      i++
      hits++
    }
  }
  if (i < n.length) return -1
  return 400 - gaps * 2 + hits
}

export default function CommandPalette() {
  const app = useApp()
  const {
    overlay, setOverlay, setView, conversations, activeId, caps,
    setCapEnabled, busyCap, chat, toast, refreshHealth, refreshCaps,
  } = app

  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const [memory, setMemory] = useState(null)
  const listRef = useRef(null)
  const open = overlay === 'palette'

  useEffect(() => {
    if (!open) return
    setQuery('')
    setIndex(0)
    api.memory(activeId || null).then(setMemory).catch(() => setMemory(null))
  }, [open, activeId])

  const close = () => setOverlay(null)

  const commands = useMemo(() => {
    const out = []

    out.push({
      id: 'new',
      group: 'Chat',
      icon: 'plus',
      label: 'New conversation',
      binding: 'mod+shift+o',
      run: () => { setView('chat'); chat.startFresh?.() },
    })
    if (chat.turnRunning) {
      out.push({
        id: 'stop',
        group: 'Chat',
        icon: 'stop',
        label: 'Stop this turn',
        hint: 'the loop is asked to stop; the stream closes itself',
        binding: 'escape',
        run: () => chat.stop?.(),
      })
    }
    if (activeId) {
      out.push({
        id: 'rename',
        group: 'Chat',
        icon: 'edit',
        label: 'Rename this conversation',
        binding: 'f2',
        run: () => { setView('chat'); chat.beginRename?.(activeId) },
      })
    }

    for (const view of VIEWS) {
      out.push({
        id: `view:${view.id}`,
        group: 'Go to',
        icon: view.icon,
        label: view.label,
        binding: view.binding,
        run: () => setView(view.id),
      })
    }

    for (const skill of caps.skills || []) {
      out.push({
        id: `skill:${skill.name}`,
        group: 'Skills',
        icon: 'book',
        label: `${skill.enabled ? 'Stand down' : 'Engage'} /${skill.name}`,
        hint: skill.description?.slice(0, 74),
        state: skill.enabled ? 'on' : 'off',
        run: () => setCapEnabled(skill, !skill.enabled),
      })
    }

    for (const connector of caps.connectors || []) {
      const state = connectorState(connector, busyCap === `connector:${connector.name}`)
      out.push({
        id: `connector:${connector.name}`,
        group: 'Connectors',
        icon: 'plug',
        label: `${connector.enabled ? 'Disconnect' : 'Connect'} ${connector.name}`,
        hint: state.detail ? state.detail.slice(0, 74) : state.label,
        state: state.tone === 'live' ? 'on' : state.tone === 'error' ? 'bad' : 'off',
        run: () => setCapEnabled(connector, !connector.enabled),
      })
    }
    out.push({
      id: 'directory:skills',
      group: 'Skills',
      icon: 'plus',
      label: 'Browse and install skills',
      hint: 'paste a link to a SKILL.md',
      run: () => setOverlay('directory:skills'),
    })

    out.push({
      id: 'connector:add',
      group: 'Connectors',
      icon: 'plus',
      label: 'Add a connector',
      hint: 'GitHub, Google Workspace, a browser, or your own server',
      run: () => setOverlay('directory:connectors'),
    })

    if (memory) {
      out.push({
        id: 'memory:toggle',
        group: 'Memory',
        icon: 'spark',
        label: memory.enabled ? 'Stop remembering' : 'Start remembering',
        hint: `${memory.facts.length} fact${memory.facts.length === 1 ? '' : 's'} recalled each turn`,
        state: memory.enabled ? 'on' : 'off',
        binding: 'mod+m',
        run: async () => {
          const next = await api.toggleMemory(!memory.enabled, activeId || null)
          setMemory((m) => ({ ...m, enabled: next.enabled }))
          toast(next.enabled ? 'Memory on' : 'Memory off', next.enabled ? 'ok' : 'info')
        },
      })
    }

    for (const conversation of conversations.slice(0, 40)) {
      if (conversation.id === activeId) continue
      out.push({
        id: `conv:${conversation.id}`,
        group: 'Conversations',
        icon: 'chat',
        label: conversation.title || 'untitled',
        hint: `${conversation.provider} · ${conversation.model}`,
        run: () => { setView('chat'); chat.selectConversation?.(conversation.id) },
      })
    }

    out.push({
      id: 'settings',
      group: 'Help',
      icon: 'sliders',
      label: 'Settings',
      binding: 'mod+,',
      run: () => setOverlay('settings'),
    })
    out.push({
      id: 'attach',
      group: 'Chat',
      icon: 'paperclip',
      label: 'Attach a file',
      binding: 'mod+u',
      run: () => { setView('chat'); chat.attach?.() },
    })
    out.push({
      id: 'shortcuts',
      group: 'Help',
      icon: 'keyboard',
      label: 'Keyboard shortcuts',
      binding: 'shift+?',
      run: () => setOverlay('shortcuts'),
    })
    out.push({
      id: 'reconnect',
      group: 'Help',
      icon: 'refresh',
      label: 'Re-check the backend',
      hint: 'health, tool count and connector errors',
      run: () => { refreshHealth(); refreshCaps() },
    })

    return out
  }, [
    caps, conversations, activeId, memory, chat, setView, setCapEnabled,
    busyCap, setOverlay, toast, refreshHealth, refreshCaps,
  ])

  const results = useMemo(() => {
    if (!query.trim()) return commands
    return commands
      .map((c) => ({ c, s: Math.max(score(c.label, query.trim()), score(`${c.group} ${c.label}`, query.trim()) - 60) }))
      .filter((r) => r.s >= 0)
      .sort((a, b) => b.s - a.s)
      .map((r) => r.c)
  }, [commands, query])

  // Group headers are decided with the list, not while rendering it, so the
  // header a row carries does not depend on the order React happens to render.
  const rows = useMemo(() => {
    let group = null
    return results.map((command) => {
      const header = command.group !== group ? command.group : null
      group = command.group
      return { command, header }
    })
  }, [results])

  useEffect(() => { setIndex(0) }, [query])

  useEffect(() => {
    if (!open) return
    const node = listRef.current?.querySelector('[data-active="true"]')
    node?.scrollIntoView({ block: 'nearest' })
  }, [index, open, results])

  if (!open) return null

  const run = (command) => {
    close()
    // Let the overlay unmount before focus moves, so the composer keeps it.
    setTimeout(() => command.run(), 0)
  }

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown' || (e.key === 'n' && e.ctrlKey)) {
      e.preventDefault()
      setIndex((i) => (results.length ? (i + 1) % results.length : 0))
    } else if (e.key === 'ArrowUp' || (e.key === 'p' && e.ctrlKey)) {
      e.preventDefault()
      setIndex((i) => (results.length ? (i - 1 + results.length) % results.length : 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const command = results[index]
      if (command) run(command)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      close()
    }
  }

  return (
    <div className="modal-overlay palette-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) close() }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div className="palette-input">
          <Icon name="search" size={16} />
          <input
            autoFocus
            value={query}
            placeholder="Run anything — a skill, a connector, a conversation"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            aria-label="Search commands"
          />
          <kbd className="kbd">Esc</kbd>
        </div>
        <div className="palette-list" ref={listRef}>
          {results.length === 0 && <div className="palette-empty">Nothing matches “{query}”.</div>}
          {rows.map(({ command, header }, i) => {
            return (
              <div key={command.id}>
                {header && <div className="palette-group">{header}</div>}
                <button
                  type="button"
                  className={`palette-item${i === index ? ' active' : ''}`}
                  data-active={i === index}
                  onMouseMove={() => setIndex(i)}
                  onClick={() => run(command)}
                >
                  <Icon name={command.icon} size={15} />
                  <span className="palette-label">
                    {command.label}
                    {command.hint && <span className="palette-hint">{command.hint}</span>}
                  </span>
                  {command.state && (
                    <span className={`led led--${command.state === 'on' ? 'ok' : command.state === 'bad' ? 'bad' : 'faint'}`} />
                  )}
                  {command.binding && (
                    <span className="palette-keys">
                      {pretty(command.binding).map((k, n) => <kbd key={n} className="kbd">{k}</kbd>)}
                    </span>
                  )}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
