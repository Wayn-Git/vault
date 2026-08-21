import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import ServiceIcon from '../components/ServiceIcon.jsx'
import { connectorState } from '../components/PlusMenu.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api, copyText } from '../api.js'

/* Connectors: what is added, what is running, and what each one still needs.

   Two facts per server, and they are not the same fact: switched on, and
   actually running. A row that reported only the first is what made connectors
   look enabled while the agent had none of their tools, so every control here
   waits for the real outcome and shows what came back. */

const TABS = [
  { id: 'all', label: 'All' },
  { id: 'connected', label: 'Connected' },
  { id: 'idle', label: 'Not connected' },
]

function OauthClientForm({ server, onDone }) {
  const { toast } = useApp()
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (!clientId.trim()) return
    setBusy(true)
    try {
      await api.mcpOauthClient(server.name, { client_id: clientId.trim(), client_secret: clientSecret.trim() || null })
      toast(`OAuth client stored for ${server.name}`, 'ok')
      setClientId('')
      setClientSecret('')
      onDone()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'grid', gap: 8, padding: '8px 14px 14px', borderTop: '1px dashed var(--hairline)' }}>
      <div className="field-row">
        <div className="field">
          <label>client id</label>
          <input value={clientId} onChange={(e) => setClientId(e.target.value)} placeholder="Ov23li…" />
        </div>
        <div className="field">
          <label>client secret</label>
          <input value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} placeholder="stored in OS keychain" type="password" />
        </div>
      </div>
      <button type="button" className="btn btn--small" onClick={save} disabled={busy || !clientId.trim()}>
        {busy ? 'Storing…' : 'Store client'}
      </button>
    </div>
  )
}

/* Some servers take their credentials through the environment rather than an
   OAuth handshake -- Google Workspace wants a client id and secret it obtained
   from Google Cloud. Without this the browser could add that connector and
   then not finish it, which is the same as not supporting it. */
function EnvForm({ server, onChanged }) {
  const { toast } = useApp()
  const [key, setKey] = useState('')
  const [value, setValue] = useState('')
  const [secret, setSecret] = useState(true)
  const [busy, setBusy] = useState('')
  const entries = Object.entries(server.env || {})

  const save = async () => {
    const name = key.trim()
    if (!name || !value) return
    setBusy('set')
    try {
      await api.mcpSetEnv(server.name, { key: name, value, secret })
      toast(`${name} stored in ${secret ? 'the OS keychain' : 'mcp.yaml'}`, 'ok')
      setKey('')
      setValue('')
      onChanged()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  const drop = async (name) => {
    setBusy(name)
    try {
      await api.mcpUnsetEnv(server.name, name)
      toast(`Forgot ${name}`, 'ok')
      onChanged()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  return (
    <div style={{ display: 'grid', gap: 10, padding: '10px 14px 14px', borderTop: '1px dashed var(--hairline)' }}>
      {entries.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {entries.map(([name, inKeychain]) => (
            <span key={name} className="badge" style={{ gap: 6 }}>
              <span className="mono">{name}</span>
              <span style={{ color: 'var(--text-faint)' }}>{inKeychain ? 'keychain' : 'mcp.yaml'}</span>
              <button
                type="button"
                onClick={() => drop(name)}
                disabled={busy === name}
                title={`Forget ${name}`}
                aria-label={`Forget ${name}`}
                style={{ color: 'var(--text-faint)', lineHeight: 0 }}
              >
                <Icon name="x" size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="field-row">
        <div className="field">
          <label>variable</label>
          <input value={key} onChange={(e) => setKey(e.target.value.toUpperCase())} placeholder="GOOGLE_OAUTH_CLIENT_ID" />
        </div>
        <div className="field">
          <label>value</label>
          <input
            value={value}
            type={secret ? 'password' : 'text'}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save() }}
            placeholder={secret ? 'stored in the OS keychain' : 'written to mcp.yaml'}
          />
        </div>
      </div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-dim)' }}>
        <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} style={{ accentColor: 'var(--clay)' }} />
        Keep this in the OS keychain — mcp.yaml holds only a reference
      </label>
      <div>
        <button type="button" className="btn btn--small" onClick={save} disabled={busy === 'set' || !key.trim() || !value}>
          {busy === 'set' ? 'Storing…' : 'Set variable'}
        </button>
      </div>
    </div>
  )
}


function SetupPanel({ server, onChanged }) {
  return (
    <div className="conn-setup">
      {server.oauth && (
        <div className="conn-setup-block">
          <div className="conn-setup-title">
            <Icon name="key" size={13} /> OAuth client
          </div>
          <p className="conn-setup-note">
            Only needed where the provider has no dynamic registration — GitHub is the
            example. Register an app with the callback
            <span className="mono"> http://127.0.0.1:33418/oauth/callback</span>, then store it here.
          </p>
          <OauthClientForm server={server} onDone={onChanged} />
        </div>
      )}
      {server.transport === 'stdio' && (
        <div className="conn-setup-block">
          <div className="conn-setup-title">
            <Icon name="key" size={13} /> Environment
          </div>
          <p className="conn-setup-note">
            Credentials this server reads from its environment. Secrets go to the OS keychain;
            mcp.yaml keeps only a reference.
          </p>
          <EnvForm server={server} onChanged={onChanged} />
        </div>
      )}
    </div>
  )
}

function ConnectorRow({ server, cap, live, busy, onAct, expanded, onExpand }) {
  const state = cap ? connectorState(cap, busy === 'switch') : null
  const needsLogin = server.oauth && server.authorized === false

  return (
    <>
      <tr className={expanded ? 'is-open' : ''}>
        <td>
          <div className="conn-name">
            <ServiceIcon name={server.name} size={26} />
            <span>
              {server.name}
              <span className="conn-target mono">{server.target}</span>
            </span>
          </div>
        </td>
        <td className="mono conn-type">{server.transport}</td>
        <td>
          <span className="conn-status">
            <span className={`led led--${state?.dot ?? 'faint'}${busy === 'switch' ? ' led--pulse' : ''}`} />
            {live?.error
              ? 'failed to start'
              : live?.connected
                ? `${live.tools} tool${live.tools === 1 ? '' : 's'} live`
                : needsLogin
                  ? 'needs sign-in'
                  : cap?.enabled ? 'on, not running' : 'off'}
          </span>
          {live?.error && <span className="conn-error">{String(live.error).slice(0, 120)}</span>}
        </td>
        <td className="conn-actions">
          <div className="conn-actions-inner">
          {needsLogin && (
            <button type="button" className="btn btn--small" disabled={Boolean(busy)} onClick={() => onAct('login')}>
              {busy === 'login' ? 'Opening…' : 'Sign in'}
            </button>
          )}
          <button
            type="button"
            className={`btn btn--small${cap?.enabled ? ' btn--ghost' : ' btn--primary'}`}
            disabled={Boolean(busy)}
            onClick={() => onAct('switch')}
          >
            {busy === 'switch' ? 'Working…' : cap?.enabled ? 'Disconnect' : 'Connect'}
          </button>
          <button
            type="button"
            className="icon-btn"
            title="Set-up and credentials"
            aria-label={`Set up ${server.name}`}
            onClick={onExpand}
          >
            <Icon name="sliders" size={15} />
          </button>
          <button
            type="button"
            className="icon-btn"
            title="Remove and forget its credentials"
            aria-label={`Remove ${server.name}`}
            disabled={Boolean(busy)}
            onClick={() => onAct('remove')}
          >
            <Icon name="trash" size={14} />
          </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="conn-setup-row">
          <td colSpan={4}><SetupPanel server={server} onChanged={onExpand} /></td>
        </tr>
      )}
    </>
  )
}

export default function Mcp() {
  const rootRef = useRef(null)
  const { toast, setOverlay, caps, refreshCaps, setCapEnabled, refreshHealth } = useApp()
  const [servers, setServers] = useState([])
  const [catalogue, setCatalogue] = useState([])
  const [live, setLive] = useState({})
  const [auths, setAuths] = useState([])
  const [tab, setTab] = useState('all')
  const [busy, setBusy] = useState({})
  const [expanded, setExpanded] = useState(null)
  const [help, setHelp] = useState(null)
  useViewEntrance(rootRef)

  const refresh = useCallback(async () => {
    try {
      const [srv, cat, auth, capabilities] = await Promise.all([
        api.mcpServers(), api.mcpCatalogue(), api.mcpAuthorizations(), api.capabilities(),
      ])
      setServers(srv)
      setCatalogue(cat)
      setAuths(auth)
      setLive(Object.fromEntries((capabilities.connectors ?? []).map((c) => [
        c.name, { enabled: c.enabled, ...(c.live || { connected: false, tools: 0, error: null }) },
      ])))
      refreshCaps()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [refreshCaps, toast])

  useEffect(() => { refresh() }, [refresh])

  // `login` blocks until the provider redirects back, so the URL it produced is
  // only visible to a second request. Keep asking while this view is open.
  useEffect(() => {
    const tick = setInterval(() => { api.mcpAuthorizations().then(setAuths).catch(() => {}) }, 3000)
    return () => clearInterval(tick)
  }, [])

  const act = useCallback(async (server, action) => {
    setBusy((b) => ({ ...b, [server.name]: action }))
    try {
      if (action === 'remove') {
        if (!window.confirm(`Remove ${server.name}? Its stored credentials are forgotten too.`)) return
        await api.mcpRemove(server.name)
        toast(`Removed ${server.name}`, 'ok')
      } else if (action === 'switch') {
        const cap = (caps.connectors ?? []).find((c) => c.name === server.name)
        await setCapEnabled(cap || { kind: 'connector', name: server.name, enabled: false }, !cap?.enabled)
      } else if (action === 'login') {
        const result = await api.mcpLogin(server.name)
        if (result.authorized) toast(`Signed in to ${server.name}`, 'ok')
        else { toast(result.result, 'info'); setHelp({ server: server.name, text: result.result }) }
      }
      await refresh()
      refreshHealth()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy((b) => ({ ...b, [server.name]: undefined }))
    }
  }, [caps, refresh, refreshHealth, setCapEnabled, toast])

  const addFromCatalogue = useCallback(async (entry) => {
    setBusy((b) => ({ ...b, [entry.id]: 'add' }))
    try {
      const result = await api.mcpAdd({ catalogue_id: entry.id })
      if (result.registration_help) setHelp({ server: result.name, text: result.registration_help })
      toast(`Added ${result.name}${result.needs_login ? ' — sign in to finish' : ''}`, 'ok')
      await refresh()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy((b) => ({ ...b, [entry.id]: undefined }))
    }
  }, [refresh, toast])

  const configured = useMemo(() => new Set(servers.map((s) => s.name)), [servers])
  const popular = useMemo(
    () => catalogue.filter((entry) => !configured.has(entry.id)).slice(0, 3),
    [catalogue, configured],
  )

  const rows = useMemo(() => servers.filter((server) => {
    const state = live[server.name] || {}
    if (tab === 'connected') return Boolean(state.connected)
    if (tab === 'idle') return !state.connected
    return true
  }), [servers, live, tab])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="vheader" data-enter>
          <div>
            <h1>Connectors</h1>
            <div className="vheader-sub">
              External apps over MCP. Their tools join the same flat namespace as the builtins, so
              the agent cannot tell them apart — but you can.
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--primary btn--small" onClick={() => setOverlay('directory:connectors')}>
              <Icon name="plus" size={14} /> Add
            </button>
            <button type="button" className="btn btn--ghost btn--small" onClick={refresh}>
              <Icon name="refresh" size={14} /> Refresh
            </button>
          </div>
        </header>

        {auths.length > 0 && (
          <div className="auth-banner" data-enter>
            <span className="led led--amber led--pulse" />
            <span>{auths.length} sign-in{auths.length > 1 ? 's' : ''} waiting:</span>
            {auths.map((a) => (
              <span key={a.server} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <button type="button" className="btn btn--small" onClick={() => window.open(a.authorization_url, '_blank', 'noopener')}>
                  <Icon name="link" size={13} /> open {a.server}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--small"
                  title="Copy the sign-in link"
                  onClick={async () => toast(
                    await copyText(a.authorization_url) ? 'Sign-in link copied' : 'Could not copy — open it instead',
                    'info',
                  )}
                >
                  <Icon name="copy" size={13} />
                </button>
              </span>
            ))}
          </div>
        )}

        {help && (
          <div className="msg-note msg-note--guard" style={{ marginBottom: 16, whiteSpace: 'pre-wrap' }} data-enter>
            <Icon name="key" size={15} />
            <span>{help.text}</span>
            <button type="button" className="icon-btn" style={{ marginLeft: 'auto' }} onClick={() => setHelp(null)} aria-label="Dismiss">
              <Icon name="x" size={14} />
            </button>
          </div>
        )}

        {popular.length > 0 && (
          <section className="conn-popular" data-enter>
            <div className="conn-section-title">Popular</div>
            <div className="conn-popular-grid">
              {popular.map((entry) => (
                <div className="conn-pop" key={entry.id}>
                  <ServiceIcon name={entry.id} size={30} />
                  <span className="conn-pop-name">{entry.title}</span>
                  <button
                    type="button"
                    className="btn btn--small"
                    disabled={busy[entry.id] === 'add'}
                    onClick={() => addFromCatalogue(entry)}
                  >
                    {busy[entry.id] === 'add' ? 'Adding…' : 'Add'}
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        <div className="conn-tabs" data-enter>
          {TABS.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`conn-tab${tab === item.id ? ' active' : ''}`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
          <span className="conn-count">{rows.length} of {servers.length}</span>
        </div>

        <div className="card" data-enter>
          <table className="conn-table">
            <thead>
              <tr><th>Connector</th><th>Type</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={4} className="conn-empty">
                  {servers.length ? 'Nothing in this tab.' : 'Nothing configured yet — Add one above.'}
                </td></tr>
              )}
              {rows.map((server) => (
                <ConnectorRow
                  key={server.name}
                  server={server}
                  cap={(caps.connectors ?? []).find((c) => c.name === server.name)}
                  live={live[server.name]}
                  busy={busy[server.name]}
                  expanded={expanded === server.name}
                  onExpand={() => setExpanded(expanded === server.name ? null : server.name)}
                  onAct={(action) => act(server, action)}
                />
              ))}
            </tbody>
          </table>
        </div>

        <p className="conn-foot" data-enter>
          Adding a connector never starts anything on its own. Connecting one starts its process
          now and reports what came back, and every server asks for trust once on first use.
        </p>
      </div>
    </div>
  )
}
