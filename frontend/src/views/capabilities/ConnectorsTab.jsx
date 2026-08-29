import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../../components/Icon.jsx'
import ServiceIcon from '../../components/ServiceIcon.jsx'
import { useApp } from '../../store.jsx'
import { api, copyText } from '../../api.js'
import Skeleton, { SkeletonRows } from '../../components/Skeleton.jsx'

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

      {(server.shares_account_with || []).length > 0 && (
        <p className="conn-setup-note">
          One account for {server.shares_account_with.length + 1} connectors — signing in here
          signs in {server.shares_account_with.join(', ')} too, and signing out signs them all out.
        </p>
      )}

      <div className="conn-connection-actions">
        {!blocked && !server.signed_in && (
          <button
            type="button"
            className="btn btn--small btn--primary"
            disabled={Boolean(busy) || (needsHint && !hint.trim())}
            onClick={() => onAct('connect')}
          >
            {busy === 'connect' ? 'Opening…' : 'Connect'}
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

  /* Once a secret is stored it is not editable here.
     One OAuth client backs every connector in an account group, so overwriting
     it is not a per-connector edit -- it takes all of them down at once, and
     the only symptom is the provider refusing to exchange a token at the *end*
     of a sign-in, a long way from the field that caused it. The backend refuses
     the write too; this is the half that stops anyone reaching for it. */
  const secretKey = server.client_secret_env
  const locked = Boolean(secretKey && server.env?.[secretKey])
  const sharedWith = server.shares_account_with || []

  if (locked) {
    return (
      <div className="conn-setup-block">
        <div className="conn-setup-title"><Icon name="key" size={13} /> Credentials</div>
        <div className="conn-locked">
          <Icon name="check" size={14} />
          <div>
            <div className="conn-locked-title">Client secret stored</div>
            <div className="conn-setup-note" style={{ margin: 0 }}>
              Held in the OS keychain
              {sharedWith.length > 0
                ? ` and shared with ${sharedWith.length} other connector${sharedWith.length === 1 ? '' : 's'}, so replacing it changes all of them.`
                : '.'}
              {' '}Replacing it is deliberate, from the terminal:
              <span className="mono"> psok mcp env {server.name} {secretKey} &lt;value&gt; --secret --force</span>
            </div>
          </div>
        </div>
      </div>
    )
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

/* The one button a row offers, per the action its state names.

   `null` means the state has no button — either nothing is wrong, or the only
   correct thing to do is wait for the provider. `credentials` deliberately has
   none either: the fields live in the card you open, and a button here would
   only take you there. */
const ROW_ACTIONS = {
  sign_in: { act: 'connect', label: 'Connect' },
  connect: { act: 'connect', label: 'Start' },
  retry: { act: 'connect', label: 'Retry' },
  sync: { act: 'sync', label: 'Sync now' },
  credentials: null,
}

/* The button a row offers, from the state the server computed.

   `sign_in` means two different things depending on whether the connector is
   working: on a connector with no account it is "Connect", and on a working one
   whose grant is about to lapse -- a Google sign-in is good for seven days
   while its OAuth app is in Testing -- it is "Sign in again", which starts a
   fresh flow rather than reconnecting a process that is already up. */
function rowAction(lifecycle) {
  if (!lifecycle) return undefined
  if (lifecycle.ready && lifecycle.action === 'sign_in') {
    return { act: 'login', label: 'Sign in again' }
  }
  return ROW_ACTIONS[lifecycle.action]
}

/* A configured connector in the list: what it is, and how it is doing. */
function ConnectorRow({ server, live, busy, onOpen, onAct, reason }) {
  const blocked = (server.missing_credentials || []).length > 0
  // `reason` is only passed for a connector that is not usable, and it outranks
  // the tool count: a running process whose account is missing was reporting
  // "122 tools live" for tools that would every one of them have failed.
  const state = reason ?? `${live?.tools ?? 0} tool${live?.tools === 1 ? '' : 's'} live`
  // A working connector can still have something to say -- a sign-in a day from
  // lapsing, two accounts in a single-user store -- and it is not "off" for it.
  // Colouring the row by the sentence rather than by the state made a warning
  // read as a failure.
  const tone = server.lifecycle?.ready
    ? 'live'
    : reason
      ? (live?.error ? 'error' : 'off')
      : 'live'
  // The server's own sentence for this state. Shown on hover rather than in the
  // row, which has no width for it — the row says *that* something is needed,
  // and the card you open says what and offers the button.
  const detail = server.lifecycle?.detail

  return (
    <button type="button" className="conn-row" onClick={onOpen} title={detail || undefined}>
      <ServiceIcon name={server.name} size={30} />
      <span className="conn-row-text">
        <span className="conn-row-name">{server.title}</span>
        <span className="conn-row-sub">
          {server.account || server.description || server.target}
        </span>
      </span>
      <span className={`conn-status conn-status--${tone}`}>{state}</span>
      {rowAction(server.lifecycle) !== undefined
        ? rowAction(server.lifecycle) && (
          <span
            role="button"
            tabIndex={0}
            className="btn btn--small btn--primary"
            onClick={(e) => { e.stopPropagation(); onAct(rowAction(server.lifecycle).act) }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.stopPropagation(); onAct(rowAction(server.lifecycle).act) }
            }}
          >
            {busy ? 'Working…' : rowAction(server.lifecycle).label}
          </span>
        )
        : server.auth_kind !== 'none' && !blocked && server.signed_in === false && (
          <span
            role="button"
            tabIndex={0}
            className="btn btn--small btn--primary"
            onClick={(e) => { e.stopPropagation(); onAct('connect') }}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onAct('connect') } }}
          >
            {busy === 'connect' ? 'Opening…' : 'Connect'}
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

/* The short label per lifecycle state. The sentence lives on the server (as
   `lifecycle.detail`) so it stays the same wherever it is read; this is only
   the two or three words that fit in a row. */
const LIFECYCLE_LABELS = {
  off: 'off',
  starting: 'not started yet',
  setup: 'needs credentials',
  authenticating: 'signing in…',
  sign_in: 'needs sign-in',
  syncing: 'first sync pending',
  failed: 'failed to start',
  ready: 'ready',
}

const FEATURED = 8

/* One sign-in, in the state it is actually in.

   Every state is spelled out here because every one of them happened and none
   of them had a screen. A link is only offered while it can still be used: an
   expired one fails at the provider with a message about a state parameter,
   which reads as PSOK being broken when the honest answer is "that took too
   long, go again". */

const AUTH_STATES = {
  waiting: {
    accent: 'waiting',
    title: (name) => `Finish signing in to ${name}`,
    note: 'A browser tab is open at the provider. This page updates itself when you are done.',
  },
  /* A flow that has started but has not asked for the user yet -- discovery,
     token refresh, or a reconnect that needs no browser at all. Without a state
     of its own the card only appeared once a URL existed, so a silent re-auth
     looked like nothing happening. */
  connecting: {
    accent: 'waiting',
    title: (name) => `Connecting to ${name}…`,
    note: 'Checking the account already stored. This only needs you if the provider asks.',
  },
  done: {
    accent: 'done',
    icon: 'check',
    title: (name) => `Connected to ${name}`,
  },
  failed: {
    accent: 'failed',
    icon: 'alert',
    title: (name) => `Could not connect to ${name}`,
    retry: 'Try again',
  },
  expired: {
    accent: 'expired',
    icon: 'clock',
    title: (name) => `The ${name} sign-in link expired`,
    note: 'Sign-in links are short-lived, so the provider will refuse this one. Start a new one.',
    retry: 'Start again',
  },
  cancelled: {
    accent: 'cancelled',
    icon: 'x',
    title: (name) => `${name} sign-in cancelled`,
    note: 'Nothing was changed.',
    retry: 'Try again',
  },
}

/* The short code a device-code sign-in expects to be typed at the provider.
   Shown large and monospaced because it is the one thing on the card the user
   has to reproduce by hand, and copyable because typing it wrong is the most
   likely way this fails. */
function DeviceCode({ code, onCopy }) {
  return (
    <button type="button" className="auth-code" onClick={onCopy} title="Copy the code">
      <span className="auth-code-value">{code}</span>
      <Icon name="copy" size={13} />
    </button>
  )
}

function AuthCard({ auth, title, onRetry, onCancel, onDismiss, onCopy, onCopyCode }) {
  const linkable = auth.status === 'waiting' && Boolean(auth.authorization_url)
  const state = linkable
    ? AUTH_STATES.waiting
    : (auth.status === 'waiting' ? AUTH_STATES.connecting : AUTH_STATES[auth.status]) ??
      AUTH_STATES.failed
  const waiting = auth.status === 'waiting'
  const [busy, setBusy] = useState(false)

  return (
    <div className={`auth-banner auth-banner--${state.accent}`} role="status">
      <span className="auth-banner-icon">
        {waiting ? <span className="auth-spinner" /> : <Icon name={state.icon} size={15} />}
      </span>
      <div className="auth-banner-body">
        <div className="auth-banner-title">{state.title(title)}</div>
        {auth.user_code && (
          <div className="auth-banner-note">
            Enter this code at the provider, then approve:
          </div>
        )}
        {auth.user_code && <DeviceCode code={auth.user_code} onCopy={onCopyCode} />}
        {(auth.message || (!auth.user_code && state.note)) && (
          <div className="auth-banner-note">{auth.message || state.note}</div>
        )}
        {waiting && auth.expires_in > 0 && (
          <div className="auth-banner-note auth-banner-meta">
            Expires in {Math.ceil(auth.expires_in / 60)} min
          </div>
        )}
      </div>
      <div className="auth-banner-actions">
        {linkable && (
          <>
            <button
              type="button"
              className="btn btn--small"
              onClick={() => window.open(auth.authorization_url, '_blank', 'noopener')}
            >
              <Icon name="link" size={13} /> Open
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--small"
              title="Copy the sign-in link"
              aria-label="Copy the sign-in link"
              onClick={onCopy}
            >
              <Icon name="copy" size={13} />
            </button>
          </>
        )}
        {!waiting && state.retry && (
          <button
            type="button"
            className="btn btn--small"
            disabled={busy}
            onClick={async () => { setBusy(true); try { await onRetry() } finally { setBusy(false) } }}
          >
            {busy ? 'Starting…' : state.retry}
          </button>
        )}
        {waiting ? (
          /* Closing the browser tab is how most abandoned sign-ins end, and
             nothing told PSOK. Without this the card sits there, and a whole
             subprocess sits behind it, until the deadline passes. */
          <button
            type="button"
            className="icon-btn"
            onClick={onCancel}
            title="Cancel this sign-in"
            aria-label="Cancel this sign-in"
          >
            <Icon name="x" size={14} />
          </button>
        ) : (
          <button type="button" className="icon-btn" onClick={onDismiss} aria-label="Dismiss">
            <Icon name="x" size={14} />
          </button>
        )}
      </div>
    </div>
  )
}

export default function ConnectorsTab({ query, newOpen, setNewOpen }) {
  const { toast, caps, refreshCaps, setCapEnabled, refreshHealth, health } = useApp()
  const [servers, setServers] = useState([])
  const [catalogue, setCatalogue] = useState([])
  const [live, setLive] = useState({})
  const [auths, setAuths] = useState([])
  const [tools, setTools] = useState([])
  const [busy, setBusy] = useState({})
  const [open, setOpen] = useState(null)
  const [starting, setStarting] = useState(false)
  // The first fetch. Five calls go out together and none of them is instant on
  // a cold backend, so without this the page rendered its "no connector
  // matches that" empty state over a list that was on its way.
  const [loaded, setLoaded] = useState(false)

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
    } finally {
      setLoaded(true)
    }
  }, [refreshCaps, toast])

  useEffect(() => { refresh() }, [refresh])

  /* The cheap half of `refresh`, for the ticker below to call twice a minute
     without re-fetching the catalogue and all 178 tool schemas -- 47KB of JSON
     that changes when a connector is added, not while one is running. These two
     are 116ms and 27ms, and they carry everything that moves: `lifecycle`, the
     tool count, whether the process is up and who is signed in. */
  const refreshServers = useCallback(async () => {
    try {
      const [srv, capabilities] = await Promise.all([api.mcpServers(true), api.capabilities()])
      setServers(srv)
      setLive(Object.fromEntries((capabilities.connectors ?? []).map((c) => [
        c.name, { enabled: c.enabled, ...(c.live || { connected: false, tools: 0, error: null }) },
      ])))
    } catch {
      /* A failed poll is not worth a toast: the next one is three seconds away,
         and a backend that is down already says so in the header. */
    }
  }, [])

  /* `login` returns as soon as the flow starts, because a sign-in takes as long
     as the person takes. This poll is how the outcome arrives: an entry stays
     `waiting` while they are with the provider, then turns `done`, `failed`,
     `cancelled` or `expired`. The card renders whichever it is, so nothing is
     toasted here -- a toast that disappears is the wrong place for a state the
     user has to act on. */
  const settled = useRef(new Set())
  // Servers whose "waiting" we have already pulled a fresh row for. The row's
  // `lifecycle` is computed on the server from the same pending state, so one
  // refetch at the start of a sign-in is what makes the row say
  // "authenticating" for its duration -- refetching every tick would ask every
  // connector who it is signed in as, three seconds apart, for the whole wait.
  const announced = useRef(new Set())
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      // A connector can die, finish starting, or lose its account between
      // renders, and until 2026-08-29 nothing asked -- the page only refetched
      // when a sign-in changed state, so a row could say "ready" over a dead
      // process until someone reloaded. This is what makes the screen current.
      if (!cancelled) refreshServers()
      let rows
      try { rows = await api.mcpAuthorizations() } catch { return }
      if (cancelled) return
      setAuths(rows)
      for (const row of rows) {
        const key = `${row.server}:${row.finished_at}`
        if (row.status === 'waiting') {
          if (!announced.current.has(row.server)) {
            announced.current.add(row.server)
            refresh()
          }
          continue
        }
        announced.current.delete(row.server)
        if (settled.current.has(key)) continue
        settled.current.add(key)
        refresh()
        refreshHealth()
      }
    }
    // Only while the page is actually being looked at. A hidden tab polling an
    // API that can run shell commands, every three seconds, for as long as the
    // browser is open, is a cost with no reader.
    let timer = null
    const start = () => { if (timer === null) timer = setInterval(tick, 3000) }
    const stop = () => { if (timer !== null) { clearInterval(timer); timer = null } }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') stop()
      else { tick(); start() }
    }
    onVisibility()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      stop()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [refresh, refreshHealth, refreshServers])

  /* Start a sign-in again after one failed, expired, or was cancelled. The
     backend supersedes the dead attempt rather than refusing as "already in
     progress", so this is the only thing the user has to do. */
  const retry = useCallback(async (name) => {
    setAuths((rows) => rows.filter((r) => r.server !== name))
    try {
      await api.mcpLogin(name, {})
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [toast])

  const dismissAuth = useCallback((name) => {
    setAuths((rows) => rows.filter((r) => r.server !== name))
  }, [])

  /* Abandon a sign-in still in progress. It releases the callback port and, for
     a server that runs its own flow, the subprocess held open behind it. */
  const cancelAuth = useCallback(async (name) => {
    setAuths((rows) => rows.filter((r) => r.server !== name))
    try {
      await api.mcpCancelLogin(name)
    } catch (err) {
      toast(err.message, 'bad')
    }
    refresh()
  }, [refresh, toast])

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
      } else if (action === 'connect') {
        /* What "connect" means to someone clicking it: switch it on, and take
           me to the provider to choose my account. Those were two separate
           controls in two places, so a connector could be on and unusable, or
           signed in and switched off, and neither said so. */
        const cap = (caps.connectors ?? []).find((c) => c.name === server.name)
        if (!cap?.enabled) {
          await setCapEnabled(cap || { kind: 'connector', name: server.name, enabled: false }, true)
        }
        await api.mcpLogin(server.name, {})
        toast(`Opening ${server.title}'s sign-in — finish in the browser`, 'info')
      } else if (action === 'logout') {
        const result = await api.mcpLogout(server.name)
        toast(
          result.cleared?.length
            ? `Signed out of ${server.title} — the next sign-in will ask which account`
            : `${server.title} had no account to forget`,
          'ok',
        )
      } else if (action === 'login') {
        await api.mcpLogin(server.name, options)
        toast(`Opening ${server.title}'s sign-in — finish in the browser`, 'info')
      } else if (action === 'sync') {
        /* The last step of setting up Microsoft To Do, which used to be
           invisible: signed in, tools live, and the Tasks page still empty
           until some background tick fifteen minutes later happened to run. */
        const result = await api.syncTasks()
        toast(result.summary || `Synced ${server.title}`, 'ok')
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

  /* Connected means usable, not merely running.

     Grouping on the process alone put Google Workspace under "Connected"
     reporting 122 tools live, beside a "Sign in" button, while no Google
     account was attached to it — every one of those tools would have failed.
     A connector that still needs an account or its credentials is waiting on
     you, whatever its process is doing.

     The judgement now comes from the server as `lifecycle` — the same one the
     agent loop uses to decide whether to offer the connector's tools, so the
     screen and the model cannot disagree about whether it works. The old
     derivation stays as the fallback for a payload without it. */
  const usable = (server) =>
    server.lifecycle
      ? server.lifecycle.ready
      : Boolean(live[server.name]?.connected)
        && (server.missing_credentials || []).length === 0
        && server.signed_in !== false

  const [running, waiting] = useMemo(() => {
    const on = []
    const off = []
    for (const server of servers.filter(matches)) {
      (usable(server) ? on : off).push(server)
    }
    return [on, off]
  }, [servers, live, q]) // eslint-disable-line react-hooks/exhaustive-deps

  const titleOf = useCallback(
    (name) => servers.find((srv) => srv.name === name)?.title || name,
    [servers],
  )

  /* Newest first: if two sign-ins are on screen the one just started is the one
     being looked at. A `done` card is kept only briefly by the backend, which
     is what stops this growing into a log. */
  const authCards = useMemo(
    () => [...auths].sort((a, b) => (a.status === 'waiting' ? -1 : 0) - (b.status === 'waiting' ? -1 : 0)),
    [auths],
  )

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
    if (server.lifecycle) return LIFECYCLE_LABELS[server.lifecycle.state] || server.lifecycle.state
    const state = live[server.name] || {}
    if ((server.missing_credentials || []).length > 0) return 'needs credentials'
    if (server.signed_in === false) return 'needs sign-in'
    if (state.error) return 'failed to start'
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
      {authCards.length > 0 && (
        <div className="auth-stack">
          {authCards.map((a) => (
            <AuthCard
              key={a.server}
              auth={a}
              title={titleOf(a.server)}
              onRetry={() => retry(a.server)}
              onCancel={() => cancelAuth(a.server)}
              onDismiss={() => dismissAuth(a.server)}
              onCopyCode={async () => toast(
                await copyText(a.user_code) ? 'Code copied' : 'Could not copy — type it instead',
                'info',
              )}
              onCopy={async () => toast(
                await copyText(a.authorization_url)
                  ? 'Sign-in link copied'
                  : 'Could not copy — open it instead',
                'info',
              )}
            />
          ))}
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
                reason={server.lifecycle?.action ? server.lifecycle.detail : undefined}
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

      {!loaded && (
        <section data-enter>
          <div className="cap-section-head"><Skeleton w={92} h={11} /><Skeleton w={54} h={11} /></div>
          <div className="card conn-list"><SkeletonRows rows={5} controls={2} /></div>
        </section>
      )}

      {loaded && servers.length === 0 && available.length === 0 && !newOpen && (
        <div className="dir-empty" data-enter>No connector matches that.</div>
      )}

      <p className="conn-foot" data-enter>
        Adding a connector never starts anything on its own. Turning one on starts its process
        now and reports what came back, and every server asks for trust once on first use.
      </p>
    </>
  )
}
