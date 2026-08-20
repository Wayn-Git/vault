import { useCallback, useEffect, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import Icon from './Icon.jsx'
import { api } from '../api.js'

function CapRow({ cap, scope, onToggle, onReset, busy }) {
  const isOn = cap.enabled
  const kindLabel = cap.kind === 'connector' ? 'connector' : 'skill'
  return (
    <div className="server-row" style={{ borderBottom: '1px solid var(--line)' }}>
      <span className={`led led--${isOn ? 'ok' : 'faint'}`} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="server-name">{cap.title || cap.name}</span>
          <span className="badge">{kindLabel}</span>
          {cap.source && cap.source !== 'user' && <span className="badge">{cap.source}</span>}
          {scope === 'conv' && <span className="badge badge--amber">this conversation</span>}
        </div>
        {cap.description && <div className="mcp-tile-desc" style={{ marginTop: 2 }}>{cap.description}</div>}
        {cap.detail && <div className="server-target">{JSON.stringify(cap.detail)}</div>}
      </div>
      <div className="server-actions">
        <button
          type="button"
          className={`btn btn--small${isOn ? ' btn--primary' : ' btn--ghost'}`}
          disabled={busy === cap.kind + cap.name}
          onClick={() => onToggle(cap, !isOn)}
        >
          {busy === cap.kind + cap.name ? '…' : isOn ? 'On' : 'Off'}
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          title="Reset to default"
          disabled={busy === cap.kind + cap.name}
          onClick={() => onReset(cap)}
        >
          <Icon name="refresh" size={13} />
        </button>
      </div>
    </div>
  )
}

export default function CapabilitiesPanel({ conversationId, onClose }) {
  const [caps, setCaps] = useState({ skills: [], connectors: [] })
  const [scope, setScope] = useState(conversationId ? 'conv' : 'global')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  useGSAP(
    () => {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
      const modal = document.querySelector('.cap-modal')
      const overlay = document.querySelector('.cap-overlay')
      if (modal) {
        gsap.fromTo(modal, { autoAlpha: 0, y: 14, scale: 0.98 }, { autoAlpha: 1, y: 0, scale: 1, duration: 0.28, ease: 'power2.out' })
      }
      if (overlay) {
        gsap.fromTo(overlay, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.18 })
      }
    },
    { dependencies: [] },
  )

  const load = useCallback(async (sc) => {
    try {
      const data = await api.capabilities(sc === 'conv' ? conversationId : null)
      setCaps(data)
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }, [conversationId])

  useEffect(() => { load(scope) }, [load, scope])

  const toggle = async (cap, enabled) => {
    setBusy(cap.kind + cap.name)
    try {
      await api.toggleCapability(cap.kind, cap.name, enabled, scope === 'conv' ? conversationId : null)
      await load(scope)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const reset = async (cap) => {
    setBusy(cap.kind + cap.name)
    try {
      await api.resetCapability(cap.kind, cap.name, scope === 'conv' ? conversationId : null)
      await load(scope)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const total = caps.skills.length + caps.connectors.length

  return (
    <div className="modal-overlay cap-overlay" onClick={onClose}>
      <div className="modal cap-modal" role="dialog" aria-modal="true" aria-label="Capabilities" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="vheader-eyebrow"><span className="led led--amber" /> capabilities</div>
            <div className="modal-title">Skills &amp; connectors</div>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 14, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="badge" style={{ padding: '5px 10px' }}>
            scope
          </div>
          <button type="button" className={`btn btn--small${scope === 'global' ? ' btn--primary' : ' btn--ghost'}`} onClick={() => setScope('global')}>
            Global default
          </button>
          <button type="button" className={`btn btn--small${scope === 'conv' ? ' btn--primary' : ' btn--ghost'}`} onClick={() => setScope('conv')} disabled={!conversationId}>
            This conversation
          </button>
          {!conversationId && <span className="mono" style={{ fontSize: 11, color: 'var(--text-faint)' }}>— open a conversation to scope to it</span>}
        </div>

        <div className="msg-note msg-note--warning" style={{ marginBottom: 14 }}>
          <Icon name="info" size={14} />
          <span>
            Skills default on, connectors default off. A disabled capability is not advertised to
            the agent on this scope. Reset returns to the default.
          </span>
        </div>

        {error && <div className="msg-note msg-note--error" style={{ marginBottom: 14 }}>{error}</div>}

        {total === 0 && !error && (
          <div className="empty-state" style={{ padding: 26 }}>
            <Icon name="spark" size={20} />
            No capabilities in this scope yet.
          </div>
        )}

        {caps.skills.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div className="card-title"><span className="led led--ok" /> skills · {caps.skills.length}</div>
            <div className="card">
              {caps.skills.map((c) => (
                <CapRow key={c.name} cap={c} scope={scope} onToggle={toggle} onReset={reset} busy={busy} />
              ))}
            </div>
          </div>
        )}

        {caps.connectors.length > 0 && (
          <div>
            <div className="card-title"><span className="led led--amber" /> connectors · {caps.connectors.length}</div>
            <div className="card">
              {caps.connectors.map((c) => (
                <CapRow key={c.name} cap={c} scope={scope} onToggle={toggle} onReset={reset} busy={busy} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}