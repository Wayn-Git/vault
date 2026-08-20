import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../gsapFx.js'
import { api } from '../api.js'

const EMPTY_FORM = { name: '', transport: 'stdio', command: '', args: '', url: '', oauth: false, allow_local: false }

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

function ServerRow({ server, live, onChanged }) {
  const { toast } = useApp()
  const [busy, setBusy] = useState('')
  const [showOauth, setShowOauth] = useState(false)
  const [showHelp, setShowHelp] = useState(false)

  const act = async (action) => {
    setBusy(action)
    try {
      if (action === 'remove') {
        if (!window.confirm(`Remove ${server.name}? Its credentials are forgotten too.`)) return
        await api.mcpRemove(server.name)
        toast(`Removed ${server.name}`, 'ok')
      } else if (action === 'connect') {
        const r = await api.mcpConnect(server.name)
        if (r.error) toast(`${server.name}: ${r.error}`, 'bad')
        else toast(`Connected ${server.name} — ${r.tools} tool${r.tools === 1 ? '' : 's'}`, 'ok')
      } else if (action === 'switch') {
        // The agent reaches a connector only while it is switched on, and the
        // API starts it at the beginning of the next turn.
        await api.toggleCapability('connector', server.name, !live, null)
        toast(`${server.name} switched ${live ? 'off' : 'on'}`, 'ok')
      } else if (action === 'login') {
        const r = await api.mcpLogin(server.name)
        if (r.authorized) toast(`Authorized ${server.name}`, 'ok')
        else toast(r.result, 'info')
      }
      onChanged()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  const authState = server.authorized === true
    ? <span className="badge badge--ok">authorized</span>
    : server.authorized === false
      ? <span className="badge badge--amber">oauth ready</span>
      : server.oauth
        ? <span className="badge badge--info">oauth</span>
        : null

  return (
    <div className="server-row">
      <span className={`led led--${live ? 'ok' : 'faint'}`} />
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="server-name">{server.name}</span>
          {authState}
          <span className="badge">{server.transport}</span>
          {server.source === 'bundled' && <span className="badge">catalogue</span>}
        </div>
        <div className="server-target">{server.target || '—'}</div>
      </div>
      <div className="server-actions">
        <button
          type="button"
          className={`btn btn--small${live ? ' btn--primary' : ' btn--ghost'}`}
          disabled={busy !== ''}
          onClick={() => act('switch')}
          title={live ? 'Switched on — the agent can use its tools' : 'Switched off — its tools are not offered to the agent'}
        >
          {busy === 'switch' ? '…' : live ? 'On' : 'Off'}
        </button>
        <button
          type="button"
          className="btn btn--ghost btn--small"
          disabled={busy !== '' || !live}
          onClick={() => act('connect')}
          title={live ? 'Connect now instead of at the next turn' : 'Switch it on first'}
        >
          {busy === 'connect' ? 'Connecting…' : 'Connect now'}
        </button>
        {server.oauth && (
          <button type="button" className="btn btn--ghost btn--small" disabled={busy !== ''} onClick={() => act('login')}>
            {busy === 'login' ? 'Logging in…' : 'Login'}
          </button>
        )}
        <button type="button" className="btn btn--ghost btn--small" disabled={busy !== ''} onClick={() => setShowOauth((s) => !s)}>
          <Icon name="key" size={13} /> OAuth client
        </button>
        <button type="button" className="btn btn--ghost btn--small" disabled={busy !== ''} onClick={() => setShowHelp((s) => !s)}>
          Help
        </button>
        <button type="button" className="btn btn--danger btn--small" disabled={busy !== ''} onClick={() => act('remove')}>
          <Icon name="trash" size={13} />
        </button>
      </div>
      {showOauth && <div style={{ gridColumn: '1 / -1', width: '100%' }}><OauthClientForm server={server} onDone={() => setShowOauth(false)} /></div>}
      {showHelp && (
        <div className="msg-note msg-note--guard" style={{ gridColumn: '1 / -1' }}>
          <Icon name="key" size={15} />
          <span>
            Register an OAuth app with this provider, then store the client here.
            Most servers support automatic registration and just need <strong>Login</strong>.
            GitHub and similar require manual registration — use <strong>OAuth client</strong> first.
          </span>
        </div>
      )}
    </div>
  )
}

export default function Mcp() {
  const rootRef = useRef(null)
  const { toast } = useApp()
  const [catalogue, setCatalogue] = useState([])
  const [servers, setServers] = useState([])
  const [live, setLive] = useState({})
  const [auths, setAuths] = useState([])
  const [busyAdd, setBusyAdd] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [helpText, setHelpText] = useState('')
  useViewEntrance(rootRef)

  const refresh = useCallback(async () => {
    try {
      const [cat, srv, auth, caps] = await Promise.all([
        api.mcpCatalogue(), api.mcpServers(), api.mcpAuthorizations(), api.capabilities(),
      ])
      setCatalogue(cat)
      setServers(srv)
      setAuths(auth)
      setLive(Object.fromEntries((caps.connectors ?? []).map((c) => [c.name, c.enabled])))
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [toast])

  useEffect(() => { refresh() }, [refresh])

  const addFromCatalogue = async (entry) => {
    setBusyAdd(entry.id)
    try {
      const r = await api.mcpAdd({ catalogue_id: entry.id })
      setHelpText(r.registration_help ? { server: r.name, text: r.registration_help } : '')
      toast(`Added ${r.name}${r.needs_login ? ' — log in to finish' : ''}`, r.needs_login ? 'info' : 'ok')
      await refresh()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusyAdd('')
    }
  }

  const addCustom = async () => {
    if (!form.name.trim()) { toast('A custom server needs a name', 'bad'); return }
    setBusyAdd('custom')
    try {
      const args = form.args.split(',').map((s) => s.trim()).filter(Boolean)
      const r = await api.mcpAdd({
        name: form.name.trim(),
        transport: form.transport,
        command: form.command.trim() || null,
        args,
        url: form.url.trim() || null,
        oauth: form.oauth,
        allow_local: form.allow_local,
      })
      setForm(EMPTY_FORM)
      setShowCustom(false)
      setHelpText(r.registration_help ? { server: r.name, text: r.registration_help } : '')
      toast(`Added ${r.name}`, r.needs_login ? 'info' : 'ok')
      await refresh()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusyAdd('')
    }
  }

  const openAuth = (url) => window.open(url, '_blank', 'noopener')

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <div className="vheader-eyebrow">
              <span className="led led--amber" /> connections
            </div>
            <h1>MCP servers</h1>
            <div className="vheader-sub">
              Connect external apps. Their tools join the same flat namespace as builtins — the agent
              can't tell them apart.
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--ghost" onClick={refresh}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        {auths.length > 0 && (
          <div className="auth-banner" data-enter>
            <span className="led led--amber led--pulse" />
            <span>
              {auths.length} OAuth authorization{auths.length > 1 ? 's' : ''} pending:
            </span>
            {auths.map((a) => (
              <button key={a.server} type="button" className="btn btn--small" onClick={() => openAuth(a.authorization_url)}>
                <Icon name="link" size={13} /> authorize {a.server}
              </button>
            ))}
            <span className="mono" style={{ fontSize: 11, color: 'var(--text-faint)', marginLeft: 'auto' }}>
              the browser may open on the backend machine too
            </span>
          </div>
        )}

        {helpText && (
          <div className="msg-note msg-note--guard" style={{ marginBottom: 16, whiteSpace: 'pre-wrap' }} data-enter>
            <Icon name="key" size={15} />
            <span>{helpText.text}</span>
          </div>
        )}

        <div className="card card-pad" style={{ marginBottom: 26 }} data-enter>
          <div className="card-title"><span className="led led--ok" /> installed · {servers.length}</div>
          {servers.length === 0 && (
            <div className="empty-state" style={{ padding: 20 }}>
              <Icon name="plug" size={20} />
              Nothing installed yet. Add a server from the catalogue below, or a custom one.
            </div>
          )}
          {servers.length > 0 && (
            <p className="mono" style={{ fontSize: 11, color: 'var(--text-faint)', margin: '0 0 10px' }}>
              A connector starts when it is switched on, at the beginning of the next turn. Adding
              one never starts a process on its own.
            </p>
          )}
          {servers.map((s) => (
            <ServerRow key={s.name} server={s} live={Boolean(live[s.name])} onChanged={refresh} />
          ))}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }} data-enter>
          <div className="card-title" style={{ marginBottom: 0 }}><span className="led led--amber" /> catalogue</div>
          <button type="button" className="btn btn--ghost btn--small" onClick={() => setShowCustom((s) => !s)}>
            <Icon name="plus" size={13} /> {showCustom ? 'Hide custom form' : 'Add custom server'}
          </button>
        </div>

        {showCustom && (
          <div className="card card-pad" style={{ marginBottom: 16, display: 'grid', gap: 12 }} data-enter>
            <div className="card-title">custom server</div>
            <div className="field">
              <label>name</label>
              <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="my-server" />
            </div>
            <div className="field">
              <label>transport</label>
              <select value={form.transport} onChange={(e) => setForm((f) => ({ ...f, transport: e.target.value }))}>
                <option value="stdio">stdio</option>
                <option value="streamable-http">streamable-http</option>
                <option value="sse">sse</option>
              </select>
            </div>
            {form.transport === 'stdio' ? (
              <div className="field-row">
                <div className="field">
                  <label>command</label>
                  <input value={form.command} onChange={(e) => setForm((f) => ({ ...f, command: e.target.value }))} placeholder="npx" />
                </div>
                <div className="field">
                  <label>args (comma separated)</label>
                  <input value={form.args} onChange={(e) => setForm((f) => ({ ...f, args: e.target.value }))} placeholder="-y, @playwright/mcp@latest" />
                </div>
              </div>
            ) : (
              <div className="field">
                <label>url</label>
                <input value={form.url} onChange={(e) => setForm((f) => ({ ...f, url: e.target.value }))} placeholder="https://mcp.example.com/mcp" />
              </div>
            )}
            <div className="field-row">
              <label className="field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-dim)' }}>
                <input type="checkbox" checked={form.oauth} onChange={(e) => setForm((f) => ({ ...f, oauth: e.target.checked }))} style={{ accentColor: 'var(--clay)' }} />
                OAuth login
              </label>
              <label className="field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-dim)' }}>
                <input type="checkbox" checked={form.allow_local} onChange={(e) => setForm((f) => ({ ...f, allow_local: e.target.checked }))} style={{ accentColor: 'var(--clay)' }} />
                allow local connections
              </label>
            </div>
            <div>
              <button type="button" className="btn btn--primary" disabled={busyAdd === 'custom'} onClick={addCustom}>
                {busyAdd === 'custom' ? 'Adding…' : 'Add server'}
              </button>
            </div>
          </div>
        )}

        <div className="mcp-tiles">
          {catalogue.map((entry) => (
            <div className="mcp-tile" key={entry.id} data-enter>
              <div className="mcp-tile-head">
                <span className="mcp-tile-title">{entry.title}</span>
                {entry.installed && <span className="badge badge--ok">installed</span>}
              </div>
              <div className="mcp-tile-desc">{entry.description}</div>
              <div className="mcp-tile-meta">
                <span className="badge">{entry.category}</span>
                <span className="badge">{entry.auth}</span>
                <span className="badge">{entry.transport}</span>
                {entry.requires && <span className="badge">{entry.requires}</span>}
              </div>
              <div className="mcp-tile-foot">
                {entry.installed ? (
                  <span className="mono" style={{ fontSize: 11, color: 'var(--text-faint)' }}>in mcp.yaml</span>
                ) : (
                  <button type="button" className="btn btn--small" disabled={busyAdd === entry.id} onClick={() => addFromCatalogue(entry)}>
                    {busyAdd === entry.id ? 'Adding…' : 'Add'}
                  </button>
                )}
                {entry.homepage && (
                  <a className="mcp-tile-home" href={entry.homepage} target="_blank" rel="noreferrer">
                    homepage
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}