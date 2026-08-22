import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { fmtDate } from '../api.js'
import { MOD_LABEL } from '../keys.js'

/* The rail: what PSOK holds, and every conversation you have had with it.

   Views live here rather than in a top bar because the list of conversations
   has to be permanently visible -- it is the thing you switch between most --
   and a top bar that carries both ends up carrying neither well. */

const PLACES = [
  { id: 'tasks', label: 'Tasks', icon: 'check' },
  // Skills and connectors are one place: they are the same kind of thing, and
  // splitting them meant a third surface existed to browse both.
  { id: 'capabilities', label: 'Skills & connectors', icon: 'grid' },
  { id: 'automations', label: 'Automations', icon: 'clock', beta: true },
  { id: 'memory', label: 'Memory', icon: 'spark' },
  { id: 'logs', label: 'Activity', icon: 'logs' },
]

/* One row, and the two things you can do to it that are not opening it.

   Delete is behind a second click rather than a modal: a modal for every
   discarded conversation is friction on the common case, and an undo this
   interface cannot honour -- the rows are gone -- would be a lie. */
function ConvRow({ conv, active, onOpen, onRename, onDelete }) {
  const [menu, setMenu] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!menu) return undefined
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) setMenu(false) }
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); setMenu(false) } }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key, true)
    }
  }, [menu])

  useEffect(() => { if (!menu) setConfirming(false) }, [menu])

  return (
    <div className={`rail-conv${active ? ' active' : ''}${menu ? ' menu-open' : ''}`} ref={ref}>
      <button
        type="button"
        className="rail-conv-open"
        onClick={onOpen}
        onDoubleClick={onRename}
        title={`${conv.provider} · ${conv.model}`}
      >
        <span className="rail-conv-title">{conv.title || 'untitled'}</span>
      </button>
      <span className="rail-conv-when">{fmtDate(conv.updated_at)}</span>
      <button
        type="button"
        className="rail-conv-more"
        onClick={() => setMenu((m) => !m)}
        title="Rename or delete"
        aria-label={`Actions for ${conv.title || 'conversation'}`}
        aria-expanded={menu}
      >
        <Icon name="dots" size={14} />
      </button>
      {menu && (
        <div className="rail-conv-menu" role="menu">
          <button type="button" onClick={() => { setMenu(false); onRename() }}>
            <Icon name="edit" size={13} /> Rename
            <kbd className="kbd">F2</kbd>
          </button>
          <button
            type="button"
            className="danger"
            onClick={() => {
              if (!confirming) { setConfirming(true); return }
              setMenu(false)
              onDelete()
            }}
          >
            <Icon name="trash" size={13} /> {confirming ? 'Click again to delete' : 'Delete'}
          </button>
        </div>
      )}
    </div>
  )
}

export default function Sidebar() {
  const {
    view, setView, conversations, activeId, chat, health, healthError,
    setOverlay, sidebar, setSidebar, renaming, setRenaming, renameConversation,
    deleteConversation,
  } = useApp()
  const [filter, setFilter] = useState('')
  const [searching, setSearching] = useState(false)

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter((c) => (c.title || 'untitled').toLowerCase().includes(q))
  }, [conversations, filter])

  if (!sidebar) {
    return (
      <button
        type="button"
        className="rail-peek"
        onClick={() => setSidebar(true)}
        title={`Show the rail — ${MOD_LABEL}+B`}
        aria-label="Show the sidebar"
      >
        <Icon name="chevron" size={15} />
      </button>
    )
  }

  return (
    <aside className="rail">
      <div className="rail-top">
        <span className="rail-brand">PSOK</span>
        <div className="rail-top-actions">
          <button
            type="button"
            className="icon-btn"
            onClick={() => setSearching((s) => !s)}
            title="Filter conversations"
            aria-label="Filter conversations"
          >
            <Icon name="search" size={15} />
          </button>
          <button
            type="button"
            className="icon-btn"
            onClick={() => setSidebar(false)}
            title={`Hide the rail — ${MOD_LABEL}+B`}
            aria-label="Hide the sidebar"
          >
            <Icon name="sidebar" size={15} />
          </button>
        </div>
      </div>

      <button
        type="button"
        className="rail-new"
        onClick={() => { setView('chat'); chat.startFresh?.() }}
        title={`New conversation — ${MOD_LABEL}+Shift+O`}
      >
        <Icon name="plus" size={15} /> New
      </button>

      <nav className="rail-places">
        {PLACES.map((place) => (
          <button
            key={place.id}
            type="button"
            className={`rail-place${view === place.id ? ' active' : ''}`}
            onClick={() => setView(place.id)}
          >
            <Icon name={place.icon} size={15} /> {place.label}
            {place.beta && <span className="beta">beta</span>}
          </button>
        ))}
      </nav>

      <div className="rail-section">
        <span>Conversations</span>
        <button
          type="button"
          className="icon-btn"
          onClick={() => setSearching((s) => !s)}
          aria-label="Filter"
        >
          <Icon name="search" size={13} />
        </button>
      </div>

      {searching && (
        <div className="rail-filter">
          <input
            autoFocus
            value={filter}
            placeholder="Filter"
            aria-label="Filter conversations"
            onChange={(e) => setFilter(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setSearching(false); setFilter('') } }}
          />
        </div>
      )}

      <div className="rail-convs">
        {visible.length === 0 && (
          <p className="rail-empty">{conversations.length ? 'Nothing matches.' : 'No conversations yet.'}</p>
        )}
        {visible.map((c) => (
          renaming === c.id ? (
            <input
              key={c.id}
              className="rail-rename"
              autoFocus
              defaultValue={c.title || ''}
              aria-label="Conversation title"
              onBlur={(e) => renameConversation(c.id, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); renameConversation(c.id, e.target.value) }
                if (e.key === 'Escape') { e.stopPropagation(); setRenaming(null) }
              }}
            />
          ) : (
            <ConvRow
              key={c.id}
              conv={c}
              active={c.id === activeId && view === 'chat'}
              onOpen={() => { setView('chat'); chat.selectConversation?.(c.id) }}
              onRename={() => setRenaming(c.id)}
              onDelete={() => deleteConversation(c.id)}
            />
          )
        ))}
      </div>

      <button
        type="button"
        className="rail-foot"
        onClick={() => setOverlay('settings')}
        title="Providers, permissions, working directory"
      >
        <span className="rail-avatar"><Icon name="cpu" size={14} /></span>
        <span className="rail-foot-text">
          <span className="rail-foot-name">Settings</span>
          <span className="rail-foot-sub">
            {healthError ? 'API offline' : health ? `${health.tools} tools · ${health.skills} skills` : 'connecting…'}
          </span>
        </span>
        <Icon name="sliders" size={14} />
      </button>
    </aside>
  )
}
