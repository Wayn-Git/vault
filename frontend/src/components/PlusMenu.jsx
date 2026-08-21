import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'

/* Everything the agent can be given for the next message, one keystroke from
   the composer.

   A connector row reports what is running, not what is switched on. Those are
   different facts: a row can say "on" while the process failed to start, died,
   or was never asked to. Switching one on starts it here and waits for the
   answer, so the row never claims a capability the agent does not have. */

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
          <span style={{ display: 'block', fontSize: 11.5, color: 'var(--text-faint)', marginTop: 1, lineHeight: 1.45 }}>
            {hint}
          </span>
        )}
      </span>
      {tail && <span className="plus-tail">{tail}</span>}
    </button>
  )
}

const Toggle = ({ on }) => <span className={`plus-toggle${on ? ' on' : ''}`} />

export function connectorState(cap, busy) {
  const live = cap.live || {}
  if (busy) return { tone: 'busy', label: 'starting', dot: 'amber' }
  if (live.error) return { tone: 'error', label: 'failed', dot: 'bad', detail: live.error }
  if (live.connected) return { tone: 'live', label: `${live.tools} tools`, dot: 'ok' }
  if (cap.enabled) return { tone: 'idle', label: 'not running', dot: 'faint' }
  return { tone: 'off', label: 'off', dot: 'faint' }
}

export default function PlusMenu({ conversationId, workspace, onWorkspace, onClose, onNavigate, onChanged }) {
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
      onChanged?.(c)
    } catch {
      /* the menu still opens; the rows simply show nothing to toggle */
    }
  }, [scope, onChanged])

  useEffect(() => { load() }, [load])

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
      // Connectors start a real process, so this waits for the outcome rather
      // than flipping the switch and hoping.
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
    connectors: caps.connectors.filter((c) => c.live?.connected).length,
  }), [caps])

  const scopeLabel = scope ? 'this conversation' : 'new conversations'

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
                : 'No connectors configured. Add one from the Connectors view.'}
            </div>
          )}
          {items.map((cap, i) => {
            const working = busy === cap.kind + cap.name
            const state = panel === 'connectors' ? connectorState(cap, working) : null
            return (
              <Row
                key={cap.name}
                index={i}
                label={cap.title || cap.name}
                hint={
                  state
                    ? state.detail
                      ? `${state.detail.slice(0, 64)} — switch on to retry`
                      : state.label
                    : cap.description?.slice(0, 58)
                }
                tail={
                  <>
                    {state && <span className={`led led--${state.dot}${working ? ' led--pulse' : ''}`} />}
                    {working ? <span className="plus-count">…</span> : <Toggle on={cap.enabled} />}
                  </>
                }
                onClick={() => toggleCap(cap)}
                disabled={working}
              />
            )
          })}
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
        <div style={{ padding: '4px 10px 11px', display: 'grid', gap: 9 }}>
          <div className="field">
            <input
              autoFocus
              value={draftWorkspace}
              placeholder="~/notes"
              onChange={(e) => setDraftWorkspace(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { onWorkspace(draftWorkspace.trim()); onClose() } }}
            />
            <span className="hint">
              File and shell tools are confined here. Empty means the directory the API started in.
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

  const failed = caps.connectors.filter((c) => c.enabled && c.live?.error).length

  return (
    <div className="plus-menu" ref={ref}>
      <Row
        index={0}
        icon="book"
        label="Skills"
        hint={`${counts.skills} of ${caps.skills.length} available`}
        tail={<Icon name="chevron" size={13} />}
        onClick={() => setPanel('skills')}
      />
      <Row
        index={1}
        icon="plug"
        label="Connectors"
        hint={
          failed
            ? `${counts.connectors} running · ${failed} failed to start`
            : `${counts.connectors} running of ${caps.connectors.length}`
        }
        tail={
          <>
            {failed > 0 && <span className="led led--bad" />}
            <Icon name="chevron" size={13} />
          </>
        }
        onClick={() => setPanel('connectors')}
      />
      <Row
        index={2}
        icon="spark"
        label="Memory"
        hint={memory ? `${memory.facts.length} fact${memory.facts.length === 1 ? '' : 's'} recalled each turn` : null}
        tail={busy === 'memory' ? '…' : <Toggle on={Boolean(memory?.enabled)} />}
        onClick={toggleMemory}
        disabled={!memory || busy === 'memory'}
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
      <div className="plus-empty" style={{ paddingTop: 0, paddingBottom: 7 }}>
        Applies to {scopeLabel}. Type <span className="mono" style={{ color: 'var(--text-dim)' }}>/name</span> to
        engage a skill directly.
      </div>
    </div>
  )
}
