import { useMemo, useState } from 'react'
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
  { id: 'skills', label: 'Skills', icon: 'book' },
  { id: 'mcp', label: 'Connectors', icon: 'plug' },
  { id: 'memory', label: 'Memory', icon: 'spark' },
  { id: 'logs', label: 'Activity', icon: 'logs' },
]

export default function Sidebar() {
  const {
    view, setView, conversations, activeId, chat, health, healthError,
    setOverlay, sidebar, setSidebar, renaming, setRenaming, renameConversation,
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
          </button>
        ))}
        <button type="button" className="rail-place" onClick={() => setOverlay('settings')}>
          <Icon name="sliders" size={15} /> Customise
        </button>
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
            <div key={c.id} className={`rail-conv${c.id === activeId && view === 'chat' ? ' active' : ''}`}>
              <button
                type="button"
                className="rail-conv-open"
                onClick={() => { setView('chat'); chat.selectConversation?.(c.id) }}
                onDoubleClick={() => setRenaming(c.id)}
                title={`${c.provider} · ${c.model}`}
              >
                <span className="rail-conv-dot" />
                <span className="rail-conv-title">{c.title || 'untitled'}</span>
              </button>
              <button
                type="button"
                className="rail-conv-edit"
                onClick={() => setRenaming(c.id)}
                title="Rename — F2"
                aria-label={`Rename ${c.title || 'conversation'}`}
              >
                <Icon name="edit" size={12} />
              </button>
              <span className="rail-conv-when">{fmtDate(c.updated_at)}</span>
            </div>
          )
        ))}
      </div>

      <button
        type="button"
        className="rail-foot"
        onClick={() => setOverlay('settings')}
        title="Providers, capabilities, permissions"
      >
        <span className="rail-avatar"><Icon name="cpu" size={14} /></span>
        <span className="rail-foot-text">
          <span className="rail-foot-name">this machine</span>
          <span className="rail-foot-sub">
            {healthError ? 'API offline' : health ? `${health.tools} tools · ${health.skills} skills` : 'connecting…'}
          </span>
        </span>
        <span className={`led led--${healthError ? 'bad' : health?.status === 'degraded' ? 'amber' : 'ok'}`} />
      </button>
    </aside>
  )
}
