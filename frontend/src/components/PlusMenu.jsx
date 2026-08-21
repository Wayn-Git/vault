import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { api } from '../api.js'
import { useApp } from '../store.jsx'
import { MOD_LABEL } from '../keys.js'

/* Everything the agent can be given for the next message, one keystroke from
   the composer.

   A row that changes what the agent can reach reports what is running, not what
   is switched on. Those are different facts: a row can say "on" while the
   process failed to start, died, or was never asked to. Switching a connector
   on starts it here and waits for the answer, so the row never claims a
   capability the agent does not have. */

export function connectorState(cap, busy) {
  const live = cap.live || {}
  if (busy) return { tone: 'busy', label: 'starting', dot: 'amber' }
  if (live.error) return { tone: 'error', label: 'failed', dot: 'bad', detail: live.error }
  if (live.connected) return { tone: 'live', label: `${live.tools} tools`, dot: 'ok' }
  if (cap.enabled) return { tone: 'idle', label: 'not running', dot: 'faint' }
  return { tone: 'off', label: 'off', dot: 'faint' }
}

function Row({ icon, label, hint, tail, onClick, disabled, danger, submenu, active }) {
  return (
    <button
      type="button"
      className={`menu-row${danger ? ' danger' : ''}${active ? ' active' : ''}`}
      onClick={onClick}
      disabled={disabled}
      aria-haspopup={submenu ? 'menu' : undefined}
      aria-expanded={submenu ? Boolean(active) : undefined}
    >
      {icon ? <Icon name={icon} size={15} /> : <span className="menu-gutter" />}
      <span className="menu-label">
        {label}
        {hint && <span className="menu-hint">{hint}</span>}
      </span>
      {tail}
      {submenu && <Icon name="chevron" size={13} className="menu-caret" />}
    </button>
  )
}

const Toggle = ({ on }) => <span className={`switch${on ? ' on' : ''}`}><span /></span>

export default function PlusMenu({ conversationId, workspace, onWorkspace, onClose, onNavigate, onAttach, placement = 'up' }) {
  const { caps, refreshCaps, setCapEnabled, busyCap, setOverlay, toast } = useApp()
  const [panel, setPanel] = useState(null)      // which submenu is open
  const [tools_open, setToolsOpen] = useState(false)
  const [memory, setMemory] = useState(null)
  const [tools, setTools] = useState([])
  const [draftWorkspace, setDraftWorkspace] = useState(workspace || '')
  const [busy, setBusy] = useState('')
  const ref = useRef(null)
  const fileRef = useRef(null)

  const scope = conversationId || null

  useEffect(() => {
    refreshCaps(scope)
    api.memory(scope).then(setMemory).catch(() => setMemory(null))
    api.tools().then(setTools).catch(() => setTools([]))
  }, [scope, refreshCaps])

  useEffect(() => {
    const away = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose() }
    const key = (e) => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      if (tools_open) setToolsOpen(false)
      else if (panel) setPanel(null)
      else onClose()
    }
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', key, true)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', key, true)
    }
  }, [onClose, panel, tools_open])

  const toggleMemory = useCallback(async () => {
    setBusy('memory')
    try {
      const next = await api.toggleMemory(!memory?.enabled, scope)
      setMemory((m) => ({ ...m, enabled: next.enabled }))
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [memory, scope, toast])

  const pickFiles = useCallback(async (files) => {
    for (const file of files) {
      try {
        onAttach?.(await api.upload(file))
      } catch (err) {
        toast(`${file.name}: ${err.message}`, 'bad')
      }
    }
    onClose()
  }, [onAttach, onClose, toast])

  const skills = caps.skills ?? []
  const connectors = caps.connectors ?? []
  const live = connectors.filter((c) => c.live?.connected).length
  const engaged = skills.filter((s) => s.enabled).length
  const byServer = useMemo(() => {
    const groups = new Map()
    for (const tool of tools) {
      const key = tool.server || 'builtin'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(tool)
    }
    return [...groups.entries()]
  }, [tools])

  const submenu = (title, body, width = 250) => (
    <div className="menu-flyout" style={{ width }}>
      <div className="menu-flyout-head">{title}</div>
      {body}
    </div>
  )

  return (
    <div className={`menu${placement === "down" ? " menu--down" : ""}`} ref={ref} role="menu">
      <input
        ref={fileRef}
        type="file"
        multiple
        hidden
        onChange={(e) => pickFiles([...e.target.files])}
      />

      <Row
        icon="paperclip"
        label="Add files or photos"
        tail={<span className="menu-keys"><kbd className="kbd">{MOD_LABEL}</kbd><kbd className="kbd">U</kbd></span>}
        onClick={() => fileRef.current?.click()}
      />
      <Row
        icon="folder"
        label="Working directory"
        hint={workspace || 'where the API was started'}
        submenu
        active={panel === 'workspace'}
        onClick={() => setPanel(panel === 'workspace' ? null : 'workspace')}
      />
      {panel === 'workspace' && submenu('file and shell tools are confined here', (
        <div className="menu-pad">
          <input
            autoFocus
            className="menu-input"
            value={draftWorkspace}
            placeholder="~/notes"
            onChange={(e) => setDraftWorkspace(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { onWorkspace(draftWorkspace.trim()); onClose() }
            }}
          />
          <button
            type="button"
            className="btn btn--primary btn--small"
            style={{ marginTop: 8 }}
            onClick={() => { onWorkspace(draftWorkspace.trim()); onClose() }}
          >
            Use this directory
          </button>
        </div>
      ), 280)}

      <div className="menu-sep" />

      <Row
        icon="book"
        label="Skills"
        hint={`${engaged} of ${skills.length} engaged`}
        submenu
        active={panel === 'skills'}
        onClick={() => setPanel(panel === 'skills' ? null : 'skills')}
      />
      {panel === 'skills' && submenu('engaged for this conversation', (
        <>
          <div className="menu-scroll">
            {skills.length === 0 && <div className="menu-empty">Nothing installed yet.</div>}
            {skills.map((skill) => (
              <Row
                key={skill.name}
                icon="book"
                label={skill.name}
                tail={busyCap === `skill:${skill.name}`
                  ? <span className="menu-hint">…</span>
                  : <Toggle on={skill.enabled} />}
                onClick={() => setCapEnabled(skill, !skill.enabled)}
              />
            ))}
          </div>
          <div className="menu-sep" />
          <Row icon="sliders" label="Manage skills" onClick={() => { onNavigate('skills'); onClose() }} />
          <Row icon="plus" label="Browse skills" onClick={() => { setOverlay('directory:skills'); onClose() }} />
        </>
      ))}

      <Row
        icon="plug"
        label="Connectors"
        hint={`${live} running of ${connectors.length}`}
        submenu
        active={panel === 'connectors'}
        onClick={() => setPanel(panel === 'connectors' ? null : 'connectors')}
      />
      {panel === 'connectors' && submenu('switching one on starts it now', (
        <>
          <Row icon="plus" label="Add connector" onClick={() => { setOverlay('directory:connectors'); onClose() }} />
          <Row icon="sliders" label="Manage connectors" onClick={() => { onNavigate('mcp'); onClose() }} />
          <div className="menu-sep" />
          <div className="menu-scroll">
            {connectors.length === 0 && <div className="menu-empty">None configured.</div>}
            {connectors.map((cap) => {
              const state = connectorState(cap, busyCap === `connector:${cap.name}`)
              return (
                <Row
                  key={cap.name}
                  icon={null}
                  label={cap.name}
                  hint={state.detail ? state.detail.slice(0, 40) : state.label}
                  tail={<Toggle on={cap.enabled} />}
                  onClick={() => setCapEnabled(cap, !cap.enabled)}
                />
              )
            })}
          </div>
          <div className="menu-sep" />
          <Row
            icon="grid"
            label="Tool access"
            hint={`${tools.length} tools reachable`}
            submenu
            active={tools_open}
            onClick={() => setToolsOpen((o) => !o)}
          />
          {tools_open && (
            <div className="menu-flyout menu-flyout--nested" style={{ width: 300 }}>
              <div className="menu-flyout-head">what the model can call right now</div>
              <div className="menu-scroll menu-scroll--tall">
                {byServer.map(([server, group]) => (
                  <div key={server}>
                    <div className="menu-group">{server === 'builtin' ? 'builtin' : server}</div>
                    {group.map((tool) => (
                      <div key={tool.name} className="menu-tool" title={tool.description}>
                        <span className={`led led--${tool.risk === 'high' ? 'bad' : tool.risk === 'medium' ? 'amber' : 'ok'}`} />
                        <span className="mono">{tool.name}</span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ), 288)}

      <div className="menu-sep" />

      <Row
        icon="spark"
        label="Memory"
        hint={memory ? `${memory.facts.length} facts recalled each turn` : null}
        tail={busy === 'memory' ? <span className="menu-hint">…</span> : <Toggle on={Boolean(memory?.enabled)} />}
        onClick={toggleMemory}
        disabled={!memory}
      />
      <Row icon="logs" label="What it just did" onClick={() => { onNavigate('logs'); onClose() }} />
    </div>
  )
}
