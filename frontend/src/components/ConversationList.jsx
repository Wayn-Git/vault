import { useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { fmtDate } from '../api.js'
import { MOD_LABEL } from '../keys.js'
import { useConfirm } from './ui/ConfirmDialog.jsx'
import { useDismiss } from '../hooks/useDismiss.js'

/* The second column of the workbench: everything you have said to PSOK.

   It was folded into the rail before, underneath the places, which meant the
   two competed for the same height and hiding the navigation hid the history
   as well. Split out, it can stay open while the rail is a strip of marks, and
   it stays open across pages -- reading the log or a connector's detail does
   not make the conversation you were in disappear.

   Grouped by day, because a flat list of forty rows called "untitled" is a
   list nobody reads the bottom half of. */

function bucketOf(iso) {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return 'Earlier'
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const days = Math.floor((startOfToday - new Date(then.getFullYear(), then.getMonth(), then.getDate())) / 86400000)
  if (days <= 0) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return 'Earlier this week'
  if (days < 30) return 'This month'
  return 'Earlier'
}

/* One row, and the two things you can do to it that are not opening it. */
function ConvRow({ conv, active, onOpen, onRename, onDelete }) {
  const [menu, setMenu] = useState(false)
  const ref = useRef(null)
  const confirm = useConfirm()

  useDismiss(ref, menu, { onAway: () => setMenu(false) })

  return (
    <div className={`wb-conv${active ? ' active' : ''}${menu ? ' menu-open' : ''}`} ref={ref}>
      <button
        type="button"
        className="wb-conv-open"
        onClick={onOpen}
        onDoubleClick={onRename}
        title={`${conv.provider} · ${conv.model}`}
      >
        <span className="wb-conv-title">{conv.title || 'untitled'}</span>
        <span className="wb-conv-when">{fmtDate(conv.updated_at)}</span>
      </button>
      <button
        type="button"
        className="wb-conv-more"
        onClick={() => setMenu((m) => !m)}
        title="Rename or delete"
        aria-label={`Actions for ${conv.title || 'conversation'}`}
        aria-expanded={menu}
      >
        <Icon name="dots" size={14} />
      </button>
      {menu && (
        <div className="wb-conv-menu" role="menu">
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

export default function ConversationList() {
  const {
    view, setView, conversations, activeId, chat, compact, railOpen, closeRail,
    renaming, setRenaming, renameConversation, deleteConversation, toggleRail,
    setOverlay, health, healthError,
  } = useApp()
  const [filter, setFilter] = useState('')

  const leave = (act) => () => { act(); closeRail() }

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const rows = q
      ? conversations.filter((c) => (c.title || 'untitled').toLowerCase().includes(q))
      : conversations
    const out = []
    for (const c of rows) {
      const label = bucketOf(c.updated_at)
      const last = out[out.length - 1]
      if (last && last.label === label) last.rows.push(c)
      else out.push({ label, rows: [c] })
    }
    return out
  }, [conversations, filter])

  const empty = groups.length === 0

  return (
    <aside
      className="wb-list"
      aria-label="Conversations"
      aria-hidden={compact && !railOpen ? 'true' : undefined}
    >
      <div className="wb-list-top">
        <span className="wb-brand">PSOK</span>
        <button
          type="button"
          className="icon-btn"
          onClick={toggleRail}
          title={compact ? 'Close navigation' : `Hide the sidebar — ${MOD_LABEL}+B`}
          aria-label={compact ? 'Close navigation' : 'Hide the sidebar'}
        >
          <Icon name={compact ? 'x' : 'sidebar'} size={compact ? 18 : 15} />
        </button>
      </div>

      <button
        type="button"
        className="wb-new"
        onClick={leave(() => { setView('chat'); chat.startFresh?.() })}
        title={`New conversation — ${MOD_LABEL}+Shift+O`}
      >
        <Icon name="plus" size={15} />
        New conversation
      </button>

      <div className="wb-list-search">
        <Icon name="search" size={14} />
        <input
          value={filter}
          placeholder="Search conversations"
          aria-label="Filter conversations"
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); setFilter('') } }}
        />
        {filter && (
          <button type="button" className="icon-btn" onClick={() => setFilter('')} aria-label="Clear">
            <Icon name="x" size={13} />
          </button>
        )}
      </div>

      <div className="wb-convs">
        {empty && (
          <p className="wb-list-empty">
            {conversations.length ? 'Nothing matches that.' : 'No conversations yet. Ask PSOK something.'}
          </p>
        )}
        {groups.map((g) => (
          <section key={g.label} className="wb-group">
            <h2 className="wb-group-head">{g.label}</h2>
            {g.rows.map((c) => (
              renaming === c.id ? (
                <input
                  key={c.id}
                  className="wb-rename"
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
          </section>
        ))}
      </div>

      {/* What the machine currently is, and the way into changing it.

          The marks column can only say this in a tooltip, and a number nobody
          can see without hovering is a number that may as well not be
          reported. It sits at the foot of the column that has room for it. */}
      <button
        type="button"
        className="wb-foot"
        onClick={leave(() => setOverlay('settings'))}
        title="Providers, permissions, working directory"
      >
        <span className="wb-foot-mark"><Icon name="cpu" size={14} /></span>
        <span className="wb-foot-text">
          <span className="wb-foot-name">Settings</span>
          <span className="wb-foot-sub">
            {healthError ? 'API offline' : health ? `${health.tools} tools · ${health.skills} skills` : 'connecting…'}
          </span>
        </span>
        <Icon name="sliders" size={14} />
      </button>
    </aside>
  )
}
