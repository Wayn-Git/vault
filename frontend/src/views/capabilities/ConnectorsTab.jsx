import { useCallback, useEffect, useMemo, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import ServiceIcon from '../../components/ServiceIcon.jsx'
import { useApp } from '../../store.jsx'
import { api, copyText } from '../../api.js'

/* Connectors: what is added, what is running, and whose account it is using.

   Two facts per server, and they are not the same fact: switched on, and
   actually running. A row that reported only the first is what made connectors
   look enabled while the agent had none of their tools, so every control here
   waits for the real outcome and shows what came back.

   A third fact was missing entirely, and cost more than either: *which account*
   a connector is signed in as. Switching one off never signed it out, so
   switching it back on silently reused whoever signed in first, with no chooser
   and no way to tell which account you had. The list answers "is it running";
   opening one answers "as whom", and gives you the control to change it. */

/* Where sign-in is arranged, and the only place "Reconnect" lives.

   Reconnecting always signs out first. A provider that still holds a session
   otherwise returns the same account without ever showing its chooser, which
   is what made switching account impossible from inside PSOK. */
function ConnectionBlock({ server, busy, onAct }) {
  const [hint, setHint] = useState('')
  const needsHint = server.auth_kind === 'setup' && Boolean(server.account_hint_label)
  const blocked = (server.missing_credentials || []).length > 0

  if (server.auth_kind === 'none') {
    return (
      <div className="conn-detail-row">
        <span>Connection</span>
        <span className="conn-detail-value">No account needed</span>
      </div>
    )
  }

  return (
    <div className="conn-connection">
      <div className="conn-detail-row">
        <span>Connection</span>
        <span className={`conn-detail-value${server.signed_in ? ' is-live' : ''}`}>
          {blocked
            ? 'Needs credentials'
            : server.signed_in
              ? (server.account || 'Signed in')
              : 'Not signed in'}
        </span>
      </div>

      {blocked && (
        <p className="conn-setup-note">
          This connector cannot sign in until it has{' '}
          {server.missing_credentials.map((key, i) => (
            <span key={key}>
              {i > 0 && ' and '}
              <span className="mono">{key}</span>
            </span>
          ))}
          . Add them below.
        </p>
      )}

      {!blocked && needsHint && !server.signed_in && (
        <div className="field" style={{ marginTop: 10 }}>
          <label>{server.account_hint_label}</label>
          <input
            value={hint}
            placeholder="you@gmail.com"
            onChange={(e) => setHint(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && hint.trim()) onAct('login', { accountHint: hint.trim() }) }}
          />
          <p className="conn-setup-note" style={{ margin: '6px 0 0' }}>
            {server.title} has to be told which account to start the flow for. You still
            choose and approve it on Google&apos;s own page.
          </p>
        </div>
      )}

      <div className="conn-connection-actions">
        {!blocked && !server.signed_in && (
          <button
            type="button"
            className="btn btn--small btn--primary"
            disabled={Boolean(busy) || (needsHint && !hint.trim())}
            onClick={() => onAct('login', { accountHint: hint.trim() || null })}
          >
            {busy === 'login' ? 'Opening…' : 'Sign in'}
          </button>
        )}
        {server.signed_in && (
          <>
            <button
              type="button"
              className="btn btn--small"
              disabled={Boolean(busy)}
              onClick={() => onAct('login', { force: true, accountHint: hint.trim() || null })}
            >
              {busy === 'login' ? 'Opening…' : 'Reconnect'}
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              disabled={Boolean(busy)}
              title="Forget this account. The next sign-in asks which one to use."
              onClick={() => onAct('logout')}
            >
              {busy === 'logout' ? 'Signing out…' : 'Sign out'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}

/* The client id and secret a provider issued, put where the thing that reads
   them will actually find it.

   PSOK's OAuth provider is built for remote transports only, so a stdio server
   reads its client from the environment its process is given. The backend
   routes by transport; this form only has to say which it is doing, because a
   form that claimed to store an OAuth client and wrote it somewhere nothing
   read is exactly how a working Google client was replaced with an email
   address and reported as stored. */
function CredentialsForm({ server, onDone }) {
  const { toast } = useApp()
  const [clientId, setClientId] = useState('')
  const [clientSecret, setClientSecret] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    if (!clientId.trim()) return
    setBusy(true)
    try {
      await api.mcpOauthClient(server.name, {
        client_id: clientId.trim(),
        client_secret: clientSecret.trim() || null,
      })
      toast(`Credentials stored for ${server.title}`, 'ok')
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
    <div className="conn-setup-block">
      <div className="conn-setup-title"><Icon name="key" size={13} /> Credentials</div>
      {server.setup_hint && <pre className="conn-setup-steps">{server.setup_hint}</pre>}
      <div className="field-row">
        <div className="field">
          <label>client id</label>
          <input
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            placeholder={server.auth_kind === 'setup' ? '…apps.googleusercontent.com' : 'Ov23li…'}
          />
        </div>
        <div className="field">
          <label>client secret</label>
          <input
            value={clientSecret}
            type="password"
            onChange={(e) => setClientSecret(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') save() }}
            placeholder="stored in the OS keychain"
          />
        </div>
      </div>
      <p className="conn-setup-note">
        The secret goes to the OS keychain; mcp.yaml keeps only a reference.
        {server.client_id_env && (
          <> The id is written to <span className="mono">{server.client_id_env}</span>, which is
          where this server reads it.</>
        )}
      </p>
      <div>
        <button type="button" className="btn btn--small" onClick={save} disabled={busy || !clientId.trim()}>
          {busy ? 'Storing…' : 'Store credentials'}
        </button>
      </div>
    </div>
  )
}

/* Any other variable a stdio server takes through its environment. */
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
    <div className="conn-setup-block">
      <div className="conn-setup-title"><Icon name="key" size={13} /> Environment</div>
      {entries.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
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
          <input value={key} onChange={(e) => setKey(e.target.value.toUpperCase())} placeholder="SOME_TOKEN" />
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
      <label className="conn-check">
        <input type="checkbox" checked={secret} onChange={(e) => setSecret(e.target.checked)} />
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

const RISK_ORDER = { high: 0, medium: 1, low: 2 }

/* Everything this connector can actually do, from the live registry.

   Not a description of what the service is for -- the list of tools the agent
   would really be able to call, with the risk each one carries, which is the
   thing that decides whether it stops to ask. */
function ActionList({ tools }) {
  const [open, setOpen] = useState(false)
  if (tools.length === 0) return null
  const shown = open ? tools : tools.slice(0, 6)

  return (
    <section className="conn-detail-section">
      <h3>Actions <span className="conn-detail-count">{tools.length}</span></h3>
      <ul className="conn-actions-list">
        {shown.map((tool) => (
          <li key={tool.name}>
            <span className="conn-action-name mono">{tool.short}</span>
            <span className="conn-action-desc">{tool.description}</span>
            <span className={`state state--${tool.risk}`}>{tool.risk}</span>
          </li>
        ))}
      </ul>
      {tools.length > 6 && (
        <button type="button" className="cat-more" onClick={() => setOpen((o) => !o)}>
          {open ? 'Show fewer' : `Show all ${tools.length}`}
        </button>
      )}
    </section>
  )
}

/* One connector, opened. Sign-in, credentials, what it can do, and what it is.

   The list used to expand a setup panel inline and nothing else, so the
   questions "whose account is this" and "what can it do" had no answer
   anywhere in the interface. */
function ConnectorDetail({ server, cap, live, busy, tools, onBack, onAct, onChanged }) {
  const information = [
    ['Category', server.category],
    ['Transport', server.transport],
    ['Endpoint', server.target],
    ['Sign-in', { oauth: 'PSOK runs the OAuth flow', setup: 'The server runs its own flow', none: 'None' }[server.auth_kind]],
    ['Requires', server.requires],
    ['Source', server.source],
  ].filter(([, value]) => Boolean(value))

  return (
    <div className="conn-detail" data-enter>
      <button type="button" className="conn-back" onClick={onBack}>
        <Icon name="chevron" size={14} className="conn-back-mark" /> Connectors
      </button>

      <header className="conn-detail-head">
        <ServiceIcon name={server.name} size={52} />
        <div className="conn-detail-title">
          <h2>{server.title}</h2>
          <p>{server.description}</p>
        </div>
        <button
          type="button"
          className={`btn btn--pill${cap?.enabled ? ' btn--ghost' : ' btn--primary'}`}
          disabled={Boolean(busy)}
          onClick={() => onAct('switch')}
        >
          {busy === 'switch' ? 'Working…' : cap?.enabled ? 'Turn off' : 'Turn on'}
        </button>
      </header>

      <div className="conn-detail-status">
        <span className={`conn-status conn-status--${live?.error ? 'error' : live?.connected ? 'live' : 'off'}`}>
          {live?.connected ? `${live.tools} tools live` : live?.error ? 'Failed to start' : 'Not running'}
        </span>
        {live?.error && <span className="conn-error">{String(live.error).slice(0, 200)}</span>}
      </div>

      <section className="conn-detail-section">
        <ConnectionBlock server={server} busy={busy} onAct={onAct} />
      </section>

      {(server.auth_kind !== 'none' || server.transport === 'stdio') && (
        <section className="conn-detail-section">
          <h3>Set-up</h3>
          {server.auth_kind !== 'none' && <CredentialsForm server={server} onDone={onChanged} />}
          {server.transport === 'stdio' && <EnvForm server={server} onChanged={onChanged} />}
        </section>
      )}

      <ActionList tools={tools} />

      <section className="conn-detail-section">
        <h3>Information</h3>
        <dl className="conn-info">
          {information.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd className={label === 'Endpoint' ? 'mono' : undefined}>{value}</dd>
            </div>
          ))}
          {server.homepage && (
            <div>
              <dt>Website</dt>
              <dd>
                <a href={server.homepage} target="_blank" rel="noreferrer noopener">
                  {server.homepage.replace(/^https?:\/\//, '')}
                </a>
              </dd>
            </div>
          )}
        </dl>
      </section>

      <div className="conn-detail-danger">
        <button
          type="button"
          className="btn btn--ghost btn--small"
          disabled={Boolean(busy)}
          onClick={() => onAct('remove')}
        >
          <Icon name="trash" size={13} /> Remove this connector
        </button>
        <span>Forgets its credentials and its signed-in account too.</span>
      </div>
    </div>
  )
}

/* A configured connector in the list: what it is, and how it is doing. */
function ConnectorRow({ server, live, busy, onOpen, onAct, reason }) {
  const blocked = (server.missing_credentials || []).length > 0
  const state = live?.connected
    ? `${live.tools} tool${live.tools === 1 ? '' : 's'} live`
    : reason ?? 'off'

  return (
    <button type="button" className="conn-row" onClick={onOpen}>
      <ServiceIcon name={server.name} size={30} />
      <span className="conn-row-text">
        <span className="conn-row-name">{server.title}</span>
        <span className="conn-row-sub">
          {blocked
            ? `Needs ${server.missing_credentials.join(' and ')}`
            : server.account || server.description || server.target}
        </span>
      </span>
      <span className={`conn-status conn-status--${live?.error ? 'error' : live?.connected ? 'live' : 'off'}`}>
        {state}
      </span>
      {server.auth_kind !== 'none' && !blocked && !server.signed_in && (
        <span
          role="button"
          tabIndex={0}
          className="btn btn--small"
          onClick={(e) => { e.stopPropagation(); onAct('login', {}) }}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAct('login', {}) } }}
        >
          {busy === 'login' ? 'Opening…' : 'Sign in'}
        </span>
      )}
      <Icon name="chevron" size={15} className="conn-row-chevron" />
    </button>
  )
}

/* One thing you could connect: an icon and a name.

   What a service is is not in doubt; what it needs is a question for after you
   pick it, and the row that manages it answers that. */
function CatalogueRow({ entry, busy, onAdd }) {
  return (
    <button type="button" className="cat-row" disabled={busy} title={entry.description} onClick={onAdd}>
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
  const [tools, setTools] = useState([])
  const [busy, setBusy] = useState({})
  const [open, setOpen] = useState(null)
  const [help, setHelp] = useState(null)
  const [starting, setStarting] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [srv, cat, auth, capabilities, allTools] = await Promise.all([
        api.mcpServers(true), api.mcpCatalogue(), api.mcpAuthorizations(),
        api.capabilities(), api.tools().catch(() => []),
      ])
      setServers(srv)
      setCatalogue(cat)
      setAuths(auth)
      setTools(allTools)
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

  const act = useCallback(async (server, action, options = {}) => {
    setBusy((b) => ({ ...b, [server.name]: action }))
    try {
      if (action === 'remove') {
        if (!window.confirm(`Remove ${server.title}? Its stored credentials and signed-in account are forgotten too.`)) return
        await api.mcpRemove(server.name)
        toast(`Removed ${server.title}`, 'ok')
        setOpen(null)
      } else if (action === 'switch') {
        const cap = (caps.connectors ?? []).find((c) => c.name === server.name)
        await setCapEnabled(cap || { kind: 'connector', name: server.name, enabled: false }, !cap?.enabled)
      } else if (action === 'logout') {
        const result = await api.mcpLogout(server.name)
        toast(
          result.cleared?.length
            ? `Signed out of ${server.title} — the next sign-in will ask which account`
            : `${server.title} had no account to forget`,
          'ok',
        )
      } else if (action === 'login') {
        const result = await api.mcpLogin(server.name, options)
        if (result.authorized) {
          toast(`Signed in to ${server.title}${result.account ? ` as ${result.account}` : ''}`, 'ok')
        } else {
          toast(result.result, 'info')
          setHelp({ server: server.name, text: result.result })
        }
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
      toast(`Added ${result.name}`, 'ok')
      await refresh()
      setOpen(result.name)
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy((b) => ({ ...b, [entry.id]: undefined }))
    }
  }, [refresh, toast])

  const q = query.trim().toLowerCase()
  const matches = (server) =>
    !q || server.name.toLowerCase().includes(q) || (server.target || '').toLowerCase().includes(q)

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

  const showAll = newOpen || Boolean(q)
  const featured = showAll ? available : available.slice(0, FEATURED)
  const started = health?.mcp_reconciled !== false

  const why = (server) => {
    const state = live[server.name] || {}
    if (state.error) return 'failed to start'
    if ((server.missing_credentials || []).length > 0) return 'needs credentials'
    if (server.signed_in === false) return 'needs sign-in'
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

  const openServer = servers.find((s) => s.name === open)
  if (openServer) {
    const prefix = `__mcp__${openServer.name.replace(/-/g, '_2d')}`
    const mine = tools
      .filter((t) => t.server === openServer.name)
      .map((t) => ({
        ...t,
        short: t.name.endsWith(prefix) ? t.name.slice(0, -prefix.length) : t.name,
        description: (t.description || '').replace(`[${openServer.name}] `, ''),
      }))
      .sort((a, b) => (RISK_ORDER[a.risk] ?? 3) - (RISK_ORDER[b.risk] ?? 3))

    return (
      <ConnectorDetail
        server={openServer}
        cap={(caps.connectors ?? []).find((c) => c.name === openServer.name)}
        live={live[openServer.name]}
        busy={busy[openServer.name]}
        tools={mine}
        onBack={() => setOpen(null)}
        onAct={(action, options) => act(openServer, action, options)}
        onChanged={refresh}
      />
    )
  }

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
          <div className="card conn-list">
            {running.map((server) => (
              <ConnectorRow
                key={server.name}
                server={server}
                live={live[server.name]}
                busy={busy[server.name]}
                onOpen={() => setOpen(server.name)}
                onAct={(action, options) => act(server, action, options)}
              />
            ))}
          </div>
        </section>
      )}

      {waiting.length > 0 && (
        <section data-enter className="cap-cat">
          <div className="cap-section-head">
            <span>{started ? 'Added, not running' : 'Added, not started yet'}</span>
            {!started && (
              <button type="button" className="btn btn--small btn--primary" disabled={starting} onClick={startAll}>
                {starting ? 'Starting…' : 'Start them'}
              </button>
            )}
            <span>{waiting.length}</span>
          </div>
          <p className="cap-note">
            {started
              ? 'Configured on this machine but contributing nothing to the agent right now. Each'
                + ' says what it is waiting for; open one to sign in or finish its set-up.'
              : 'Connectors start with the first turn of a conversation, and none has run yet in'
                + ' this server. Start them now to see what actually comes up.'}
          </p>
          <div className="card conn-list">
            {waiting.map((server) => (
              <ConnectorRow
                key={server.name}
                server={server}
                live={live[server.name]}
                busy={busy[server.name]}
                onOpen={() => setOpen(server.name)}
                onAct={(action, options) => act(server, action, options)}
                reason={why(server)}
              />
            ))}
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
            <button type="button" className="cat-more" onClick={() => setNewOpen(true)}>See more</button>
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
        Adding a connector never starts anything on its own. Turning one on starts its process
        now and reports what came back, and every server asks for trust once on first use.
      </p>
    </>
  )
}
