import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'

/* Everything the agent can be given for the next message, one keystroke from the
   composer: which skills it may read, which connectors it may reach, whether it
   remembers, and where on disk it is allowed to work.

   Scope follows the conversation when there is one, because "not this one, not
   here" is the useful unit — and falls back to the global default before the
   first message exists. */

function Row({ index, icon, label, hint, tail, onClick, disabled }) {
  return (
    <button
      type="button"
      className="plus-item"
      style={{ '--i': index }}
      onClick={onClick}
      disabled={disabled}
    >
      {icon && <Icon name={icon} size={15} />}
      <span style={{ minWidth: 0 }}>
        {label}
        {hint && (
          <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-faint)', marginTop: 1 }}>
            {hint}
          </span>
        )}
      </span>
      {tail && <span className="plus-tail">{tail}</span>}
    </button>
  )
}

function Toggle({ on }) {
  return <span className={`plus-toggle${on ? ' on' : ''}`} />
}

export default function PlusMenu({ conversationId, workspace, onWorkspace, onClose, onNavigate }) {
  const [panel, setPanel] = useState('root')
  const [caps, setCaps] = useState({ skills: [], connectors: [] })
  const [memory, setMemory] = useState(null)
  const [busy, setBusy] = useState('')
  const [draftWorkspace, setDraftWorkspace] = useState(workspace || '')
  const ref = useRef(null)

  const scope = conversationId || null

  const load = useCallback(async () => {
    try {
      const [c, m] = await Promise.all([api.capabilities(scope), api.memory(scope)])
      setCaps(c)
      setMemory(m)
    } catch {
      /* the menu still opens; the rows simply show nothing to toggle */
    }
  }, [scope])

  useEffect(() => { load() }, [load])

  // Click-away and Escape, because a popover that traps the user is a modal
  // wearing a disguise.
  useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const key = (e) => { if (e.key === 'Escape') (panel === 'root' ? onClose() : setPanel('root')) }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key)
    }
  }, [onClose, panel])

  const toggleCap = async (cap) => {
    setBusy(cap.kind + cap.name)
    try {
      await api.toggleCapability(cap.kind, cap.name, !cap.enabled, scope)
      await load()
    } finally {
      setBusy('')
    }
  }

  const toggleMemory = async () => {
    setBusy('memory')
    try {
      await api.toggleMemory(!memory.enabled, scope)
      await load()
    } finally {
      setBusy('')
    }
  }

  const counts = useMemo(() => ({
    skills: caps.skills.filter((s) => s.enabled).length,
    connectors: caps.connectors.filter((c) => c.enabled).length,
  }), [caps])

  const scopeLabel = scope ? 'this conversation' : 'default for new chats'

  if (panel === 'skills' || panel === 'connectors') {
    const items = panel === 'skills' ? caps.skills : caps.connectors
    return (
      <div className="plus-menu" ref={ref}>
        <div className="plus-head">
          <button type="button" className="plus-back" onClick={() => setPanel('root')} aria-label="Back">
            <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} />
          </button>
          {panel} · {scopeLabel}
        </div>
        <div className="plus-scroll">
          {items.length === 0 && (
            <div className="plus-empty">
              {panel === 'skills'
                ? 'No skills installed. Drop a SKILL.md into ~/.psok/skills/<name>/.'
                : 'No connectors configured yet.'}
            </div>
          )}
          {items.map((cap, i) => (
            <Row
              key={cap.name}
              index={i}
              label={cap.title || cap.name}
              hint={cap.description?.slice(0, 60)}
              tail={busy === cap.kind + cap.name ? '…' : <Toggle on={cap.enabled} />}
              onClick={() => toggleCap(cap)}
            />
          ))}
        </div>
        {panel === 'connectors' && (
          <>
            <div className="plus-sep" />
            <Row
              index={items.length}
              icon="plus"
              label="Add a connector"
              onClick={() => { onNavigate('mcp'); onClose() }}
            />
          </>
        )}
      </div>
    )
  }

  if (panel === 'workspace') {
    return (
      <div className="plus-menu" ref={ref} style={{ width: 320 }}>
        <div className="plus-head">
          <button type="button" className="plus-back" onClick={() => setPanel('root')} aria-label="Back">
            <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} />
          </button>
          workspace root
        </div>
        <div style={{ padding: '4px 11px 12px', display: 'grid', gap: 9 }}>
          <div className="field">
            <input
              autoFocus
              value={draftWorkspace}
              placeholder="~/notes"
              onChange={(e) => setDraftWorkspace(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { onWorkspace(draftWorkspace.trim()); onClose() }
              }}
            />
            <span className="hint">
              File and shell tools are scoped here. Empty means the directory the API was started in.
            </span>
          </div>
          <button
            type="button"
            className="btn btn--primary btn--small"
            onClick={() => { onWorkspace(draftWorkspace.trim()); onClose() }}
          >
            Use this directory
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="plus-menu" ref={ref}>
      <Row
        index={0}
        icon="book"
        label="Skills"
        tail={<><span className="plus-count">{counts.skills}/{caps.skills.length}</span><Icon name="chevron" size={13} /></>}
        onClick={() => setPanel('skills')}
      />
      <Row
        index={1}
        icon="plug"
        label="Connectors"
        tail={<><span className="plus-count">{counts.connectors}/{caps.connectors.length}</span><Icon name="chevron" size={13} /></>}
        onClick={() => setPanel('connectors')}
      />
      <Row
        index={2}
        icon="spark"
        label="Memory"
        hint={memory ? `${memory.facts.length} fact${memory.facts.length === 1 ? '' : 's'} recalled each turn` : null}
        tail={busy === 'memory' ? '…' : <Toggle on={Boolean(memory?.enabled)} />}
        onClick={toggleMemory}
        disabled={!memory}
      />
      <div className="plus-sep" />
      <Row
        index={3}
        icon="term"
        label="Workspace"
        hint={workspace || 'the API working directory'}
        tail={<Icon name="chevron" size={13} />}
        onClick={() => setPanel('workspace')}
      />
      <Row
        index={4}
        icon="logs"
        label="What it just did"
        hint="every tool call, and what allowed it"
        onClick={() => { onNavigate('logs'); onClose() }}
      />
      <div className="plus-sep" />
      <div className="plus-empty" style={{ paddingTop: 2, paddingBottom: 8 }}>
        Changes apply to {scopeLabel}. Type <span className="mono" style={{ color: 'var(--clay)' }}>/name</span> to
        engage a skill directly.
      </div>
    </div>
  )
}
