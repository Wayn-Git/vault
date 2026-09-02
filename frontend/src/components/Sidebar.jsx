import { useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { fmtDate } from '../api.js'
import { MOD_LABEL } from '../keys.js'
import { forRail } from '../nav.js'
import { useConfirm } from './ui/ConfirmDialog.jsx'
import { useDismiss } from '../hooks/useDismiss.js'
import { prefetchView } from '../views/registry.js'

/* The rail: what PSOK holds, and every conversation you have had with it.

   Views live here rather than in a top bar because the list of conversations
   has to be permanently visible -- it is the thing you switch between most --
   and a top bar that carries both ends up carrying neither well. */

const PLACES = forRail()

/* One row, and the two things you can do to it that are not opening it. */
function ConvRow({ conv, active, onOpen, onRename, onDelete }) {
  const [menu, setMenu] = useState(false)
  const ref = useRef(null)
  const confirm = useConfirm()

  useDismiss(ref, menu, { onAway: () => setMenu(false) })

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
            onClick={async () => {
              setMenu(false)
              const ok = await confirm({
                title: `Delete "${conv.title || 'untitled'}"?`,
                description: 'This conversation and its messages are gone for good.',
                confirmLabel: 'Delete',
                tone: 'danger',
              })
              if (ok) onDelete()
            }}
          >
            <Icon name="trash" size={13} /> Delete
          </button>
        </div>
      )}
    </div>
  )
}

export default function Sidebar() {
  const {
    view, setView, conversations, activeId, chat, health, healthError,
    setOverlay, compact, railOpen, toggleRail, closeRail, renaming, setRenaming,
    renameConversation, deleteConversation,
  } = useApp()
  const [filter, setFilter] = useState('')
  const [searching, setSearching] = useState(false)
  const firstRef = useRef(null)

  /* Every way out of the drawer, in one place.
   *
   * The store closes it when the route changes, which covers the places above
   * — but opening a conversation and starting a new one both stay on /chat, so
   * the route never changes and the drawer stayed sitting over the transcript
   * the tap had just asked for. */
  const leave = (act) => () => { act(); closeRail() }

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter((c) => (c.title || 'untitled').toLowerCase().includes(q))
  }, [conversations, filter])

  /* Opening the drawer moves focus into it. A drawer that opens behind the
     keyboard's cursor is a drawer a keyboard user has to hunt for. */
  useEffect(() => {
    if (compact && railOpen) firstRef.current?.focus()
  }, [compact, railOpen])

  // Desktop only: on a phone the header's menu button is the way back in, and
  // a second floating control for the same thing is one more thing over the
  // page. The rail stays mounted either way, so the drawer can animate out.
  if (!compact && !railOpen) {
    return (
      <button
        type="button"
        className="rail-peek"
        onClick={toggleRail}
        title={`Show the rail — ${MOD_LABEL}+B`}
        aria-label="Show the sidebar"
      >
        <Icon name="chevron" size={15} />
      </button>
    )
  }

  return (
    <aside
      id="rail"
      className={`rail${compact ? ' rail--drawer' : ''}${railOpen ? ' is-open' : ''}`}
      aria-label="Places and conversations"
      aria-hidden={compact && !railOpen ? 'true' : undefined}
    >
      <div className="rail-top">
        <span className="rail-brand">PSOK</span>
        <div className="rail-top-actions">
          <button
            type="button"
            className="icon-btn"
            onClick={toggleRail}
            title={compact ? 'Close navigation' : `Hide the rail — ${MOD_LABEL}+B`}
            aria-label={compact ? 'Close navigation' : 'Hide the sidebar'}
          >
            <Icon name={compact ? 'x' : 'sidebar'} size={compact ? 17 : 15} />
          </button>
        </div>
      </div>

      <button
        type="button"
        ref={firstRef}
        className="rail-new"
        onClick={leave(() => { setView('chat'); chat.startFresh?.() })}
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
            aria-current={view === place.id ? 'page' : undefined}
            onClick={() => setView(place.id)}
            // Each view is its own script now, so the hover is where it gets
            // fetched: by the time the click lands it is already parsed.
            onPointerEnter={() => prefetchView(place.id)}
            onFocus={() => prefetchView(place.id)}
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
              onOpen={leave(() => { setView('chat'); chat.selectConversation?.(c.id) })}
              onRename={() => setRenaming(c.id)}
              onDelete={() => deleteConversation(c.id)}
            />
          )
        ))}
      </div>

      <button
        type="button"
        className="rail-foot"
        onClick={leave(() => setOverlay('settings'))}
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
