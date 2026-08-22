import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import ServiceIcon from '../../components/ServiceIcon.jsx'
import { useApp } from '../../store.jsx'
import { api, copyText } from '../../api.js'

/* Connectors: what is added, what is running, and what each one still needs.

   Two facts per server, and they are not the same fact: switched on, and
   actually running. A row that reported only the first is what made connectors
   look enabled while the agent had none of their tools, so every control here
   waits for the real outcome and shows what came back.

   The catalogue used to live in a separate overlay, so adding a connector and
   managing one were two different places that showed the same services -- and
   the overlay's answer to anything beyond "add it" was to send you here. They
   are one surface now: what is configured, and beneath it everything that
   could be, grouped the way the catalogue groups it. */

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

function ConnectorRow({ server, cap, live, busy, onAct, expanded, onExpand, reason }) {
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
        <td>
          <span className={`conn-status conn-status--${live?.error ? 'error' : live?.connected ? 'live' : 'off'}`}>
            {live?.connected
              ? `${live.tools} tool${live.tools === 1 ? '' : 's'} live`
              : reason ?? 'off'}
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
          <td colSpan={3}><SetupPanel server={server} onChanged={onExpand} /></td>
        </tr>
      )}
    </>
  )
}

/* One thing you could connect: an icon and a name.

   The tiles here used to carry a description, a transport, an auth badge and a
   collapsible setup note each -- four lines of explanation per service, for a
   list whose only question is "which one". What a service is is not in doubt;
   what it needs is a question for after you pick it, and the row that manages
   it answers that. */
function CatalogueRow({ entry, busy, onAdd }) {
  return (
    <button
      type="button"
      className="cat-row"
      disabled={busy}
      title={entry.description}
      onClick={onAdd}
    >
      <ServiceIcon name={entry.id} size={26} />
      <span className="cat-row-name">{entry.title}</span>
      {entry.auth !== 'none' && <span className="state">{entry.auth}</span>}
      <Icon name={busy ? 'refresh' : 'plus'} size={15} className="cat-row-add" />
    </button>
  )
}


const FEATURED = 8

export default function ConnectorsTab({ query, newOpen, setNewOpen }) {
  const { toast, caps, refreshCaps, setCapEnabled, refreshHealth, health } = useApp()
  const [servers, setServers] = useState([])
  const [catalogue, setCatalogue] = useState([])
  const [live, setLive] = useState({})
  const [auths, setAuths] = useState([])
  const [busy, setBusy] = useState({})
  const [expanded, setExpanded] = useState(null)
  const [help, setHelp] = useState(null)
  const [starting, setStarting] = useState(false)

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

  const q = query.trim().toLowerCase()
  const matches = (server) =>
    !q || server.name.toLowerCase().includes(q) || (server.target || '').toLowerCase().includes(q)

  /* Running, and everything else.

     One table of everything "added" put a connector that has never once worked
     next to four that are serving tools right now, under a heading that said
     they were the same thing. They are not: the first list is what the agent
     can reach this second, and the second is a list of things waiting on you.
     A permanently-failing connector sitting among the working ones is worse
     than an absent one, because it makes the working ones look uncertain. */
  const [running, waiting] = useMemo(() => {
    const on = []
    const off = []
    for (const server of servers.filter(matches)) {
      (live[server.name]?.connected ? on : off).push(server)
    }
    return [on, off]
  }, [servers, live, q]) // eslint-disable-line react-hooks/exhaustive-deps

  const configured = useMemo(() => new Set(servers.map((s) => s.name)), [servers])
  const available = useMemo(() => catalogue.filter((entry) => {
    if (configured.has(entry.id)) return false
    return !q
      || entry.title.toLowerCase().includes(q)
      || entry.description.toLowerCase().includes(q)
      || entry.category.toLowerCase().includes(q)
  }), [catalogue, configured, q])

  // A search is itself a request to look through everything there is.
  const showAll = newOpen || Boolean(q)
  const featured = showAll ? available : available.slice(0, FEATURED)

  // Connectors reconcile at the start of a turn, so before one has happened
  // every switched-on connector is truthfully idle. Saying "not running" there
  // reads as six failures when the real answer is that nothing has asked yet.
  const started = health?.mcp_reconciled !== false

  const why = (server) => {
    const state = live[server.name] || {}
    if (state.error) return 'failed to start'
    if (server.oauth && server.authorized === false) return 'needs sign-in'
    if (!state.enabled) return 'off'
    return started ? 'not running' : 'not started yet'
  }

  const startAll = useCallback(async () => {
    setStarting(true)
    try {
      const result = await api.mcpReconcile()
      const failed = Object.keys(result.errors || {}).length
      toast(
        `${result.connected} connected · ${result.tools} tools`
          + (failed ? ` · ${failed} could not start` : ''),
        failed ? 'amber' : 'ok',
      )
      await refresh()
      refreshHealth()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setStarting(false)
    }
  }, [refresh, refreshHealth, toast])

  return (
    <>
      {auths.length > 0 && (
        <div className="auth-banner" data-enter>
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

      {running.length > 0 && (
        <section data-enter>
          <div className="cap-section-head">
            <span>Connected</span>
            <span>{running.reduce((n, s) => n + (live[s.name]?.tools ?? 0), 0)} tools</span>
          </div>
          <div className="card">
            <table className="conn-table">
              <tbody>
                {running.map((server) => (
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
        </section>
      )}

      {waiting.length > 0 && (
        <section data-enter className="cap-cat">
          <div className="cap-section-head">
            <span>{started ? 'Added, not running' : 'Added, not started yet'}</span>
            {!started && (
              <button
                type="button"
                className="btn btn--small btn--primary"
                disabled={starting}
                onClick={startAll}
              >
                {starting ? 'Starting…' : 'Start them'}
              </button>
            )}
            <span>{waiting.length}</span>
          </div>
          <p className="cap-note">
            {started
              ? 'Configured on this machine but contributing nothing to the agent right now. Each'
                + ' says what it is waiting for; removing one forgets its credentials too.'
              : 'Connectors start with the first turn of a conversation, and none has run yet in'
                + ' this server. Start them now to see what actually comes up.'}
          </p>
          <div className="card">
            <table className="conn-table">
              <tbody>
                {waiting.map((server) => (
                  <ConnectorRow
                    key={server.name}
                    server={server}
                    cap={(caps.connectors ?? []).find((c) => c.name === server.name)}
                    live={live[server.name]}
                    busy={busy[server.name]}
                    expanded={expanded === server.name}
                    onExpand={() => setExpanded(expanded === server.name ? null : server.name)}
                    onAct={(action) => act(server, action)}
                    reason={why(server)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {available.length > 0 && (
        <section data-enter className="cap-cat">
          <div className="cap-section-head">
            <span>{showAll ? 'Everything available' : 'Featured'}</span>
            <span>{available.length}</span>
          </div>
          <div className="cat-grid">
            {featured.map((entry) => (
              <CatalogueRow
                key={entry.id}
                entry={entry}
                busy={busy[entry.id] === 'add'}
                onAdd={() => addFromCatalogue(entry)}
              />
            ))}
          </div>
          {!showAll && available.length > FEATURED && (
            <button type="button" className="cat-more" onClick={() => setNewOpen(true)}>
              See more
            </button>
          )}
        </section>
      )}

      {available.length === 0 && newOpen && (
        <section data-enter className="cap-cat">
          <div className="cap-section-head"><span>Everything available</span><span>0</span></div>
          <p className="cap-note">
            {q
              ? 'No connector in the catalogue matches that.'
              : 'Every connector in the bundled catalogue is already added. Anything else is a'
                + ' server of your own: add it to ~/.psok/config/mcp.yaml and it appears here.'}
          </p>
        </section>
      )}

      {servers.length === 0 && available.length === 0 && !newOpen && (
        <div className="dir-empty" data-enter>No connector matches that.</div>
      )}

      <p className="conn-foot" data-enter>
        Adding a connector never starts anything on its own. Connecting one starts its process
        now and reports what came back, and every server asks for trust once on first use.
      </p>
    </>
  )
}
