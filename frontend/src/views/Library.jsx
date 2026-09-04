import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api, fmtDate, copyText } from '../api.js'
import { SkeletonRows } from '../components/Skeleton.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'

/* Everything you have read, watched and listened to.
 *
 * Capture writes the page's text to a real file under ~/.psok/library and hands
 * it to the same indexer that reads the vault, so an article saved here is
 * found by `search_documents` in a chat as well as by the search box below.
 *
 * `?url=` prefills the field — that is what the bookmarklet uses. It navigates
 * rather than posting, because a page on another origin cannot POST to this API
 * and should not be able to. */

const KINDS = ['article', 'book', 'video', 'podcast', 'newsletter', 'paper', 'note', 'other']

const KIND_ICON = {
  article: 'book', book: 'book', video: 'image', podcast: 'spark',
  newsletter: 'mail', paper: 'book', note: 'edit', other: 'link',
}

function bookmarklet(origin) {
  return `javascript:void(window.open('${origin}/library?url='+encodeURIComponent(location.href),'_blank'))`
}

export default function Library() {
  const rootRef = useRef(null)
  const { toast } = useApp()
  const [params, setParams] = useSearchParams()
  const [items, setItems] = useState([])
  const [counts, setCounts] = useState({})
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [draft, setDraft] = useState({ url: '', title: '', kind: '', author: '', notes: '' })
  const loadToken = useRef(0)
  useViewEntrance(rootRef, [loaded])

  // The bookmarklet lands here. Taken out of the URL once read, so a refresh
  // does not re-offer a link that has already been saved.
  useEffect(() => {
    const incoming = params.get('url')
    if (!incoming) return
    setDraft((d) => ({ ...d, url: incoming }))
    params.delete('url')
    setParams(params, { replace: true })
  }, [params, setParams])

  const load = useCallback(async () => {
    const token = ++loadToken.current
    try {
      const data = await api.library({ q: query, kind })
      if (loadToken.current !== token) return
      setItems(data.items)
      setCounts(data.counts)
      setError(null)
    } catch (err) {
      if (loadToken.current !== token) return
      setItems([])
      setError(err.message)
    } finally {
      if (loadToken.current === token) setLoaded(true)
    }
  }, [query, kind])

  // Debounced, so typing a query is one request rather than one per keystroke.
  useEffect(() => {
    const timer = setTimeout(load, query ? 300 : 0)
    return () => clearTimeout(timer)
  }, [load, query])

  const save = useCallback(async () => {
    const body = {
      url: draft.url.trim() || null,
      title: draft.title.trim() || null,
      kind: draft.kind || null,
      author: draft.author.trim() || null,
      notes: draft.notes.trim() || null,
    }
    if (!body.url && !body.title) {
      toast('Give a link, or a title', 'bad')
      return
    }
    setSaving(true)
    try {
      const saved = await api.addLibraryItem(body)
      toast(saved.already_logged ? `Already logged: ${saved.title}` : `Logged: ${saved.title}`, 'ok')
      setDraft({ url: '', title: '', kind: '', author: '', notes: '' })
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setSaving(false)
    }
  }, [draft, load, toast])

  const act = useCallback(async (item, run, note) => {
    setBusyId(item.id)
    try {
      await run()
      if (note) toast(note, 'ok')
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusyId(null)
    }
  }, [load, toast])

  const total = useMemo(() => Object.values(counts).reduce((sum, n) => sum + n, 0), [counts])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="vheader" data-enter>
          <div>
            <h1>Library</h1>
            <div className="vheader-sub">
              What you have read, watched and listened to. Captured text is indexed,
              so the agent can answer from it too.
            </div>
          </div>
          <div className="vheader-actions">
            <button
              type="button"
              className="btn btn--ghost"
              aria-expanded={showShare}
              onClick={() => setShowShare(!showShare)}
            >
              <Icon name="link" size={15} /> Save from anywhere
            </button>
          </div>
        </header>

        {showShare && <SharePanel toast={toast} />}
        {showShare && <InstagramPanel toast={toast} />}

        <section className="card card-pad lib-capture" data-enter>
          <div className="card-title">log something</div>
          <div className="lib-capture-row">
            <input
              className="lib-input"
              placeholder="Paste a link…"
              value={draft.url}
              onChange={(e) => setDraft({ ...draft, url: e.target.value })}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) save() }}
            />
            <select
              className="lib-select"
              value={draft.kind}
              onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
              aria-label="Kind"
            >
              <option value="">auto</option>
              {KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button type="button" className="btn btn--primary" disabled={saving} onClick={save}>
              {saving ? 'Saving…' : 'Log it'}
            </button>
          </div>
          <details className="lib-manual">
            <summary>No link — a book, a talk, a conversation</summary>
            <div className="lib-manual-grid">
              <input
                className="lib-input"
                placeholder="Title"
                value={draft.title}
                onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              />
              <input
                className="lib-input"
                placeholder="Author"
                value={draft.author}
                onChange={(e) => setDraft({ ...draft, author: e.target.value })}
              />
            </div>
            <textarea
              className="lib-input"
              rows={3}
              placeholder="What it said, what you thought — this is what search reads."
              value={draft.notes}
              onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
            />
          </details>
        </section>

        <div className="lib-toolbar" data-enter>
          <div className="lib-search">
            <Icon name="search" size={15} />
            <input
              className="lib-input"
              placeholder="Search what you have read…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <select
            className="lib-select"
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            aria-label="Filter by kind"
          >
            <option value="">all kinds</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>{k}{counts[k] ? ` (${counts[k]})` : ''}</option>
            ))}
          </select>
          <span className="lib-total mono">{total} logged</span>
        </div>

        {!loaded ? (
          <SkeletonRows rows={5} controls={2} />
        ) : error ? (
          <ErrorState message={error} onRetry={load} />
        ) : items.length === 0 ? (
          <EmptyState
            icon="book"
            message={
              query
                ? `Nothing matched “${query}”. Items logged without captured text are findable by title and notes.`
                : 'Nothing logged yet. Paste a link above, or ask in chat to log something you have read.'
            }
          />
        ) : (
          <div className="lib-rows">
            {items.map((item) => (
              <Row
                key={item.id}
                item={item}
                busy={busyId === item.id}
                onReindex={() => act(item, () => api.reindexLibraryItem(item.id), 'Indexed again')}
                onEnrich={() => act(item, () => api.enrichLibraryItem(item.id), 'Read and summarised')}
                onDelete={() => act(item, () => api.deleteLibraryItem(item.id), 'Removed')}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ item, busy, onReindex, onEnrich, onDelete }) {
  return (
    <article className="card lib-row" data-enter>
      <div className="lib-row-icon">
        {item.thumbnail_path ? (
          <img className="lib-thumb" src={api.thumbnailUrl(item.id)} alt="" loading="lazy" />
        ) : (
          <Icon name={KIND_ICON[item.kind] || 'link'} size={18} />
        )}
      </div>
      <div className="lib-row-body">
        <div className="lib-row-title">
          {item.url
            ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
            : item.title}
        </div>
        <div className="lib-row-meta mono">
          {[item.kind, item.author, item.site, fmtDate(item.consumed_on)].filter(Boolean).join(' · ')}
        </div>
        {/* What it is about, before what matched. A summary is the thing worth
            reading in a list; the excerpt is only interesting while searching. */}
        {item.summary ? <p className="lib-row-excerpt">{item.summary}</p> : null}
        {item.excerpt && !item.summary ? <p className="lib-row-excerpt">{item.excerpt}</p> : null}
        {item.notes && !item.excerpt && !item.summary
          ? <p className="lib-row-excerpt">{item.notes}</p>
          : null}
        {item.tags?.length ? (
          <div className="lib-tags">
            {item.tags.map((tag) => <span className="lib-tag" key={tag}>{tag}</span>)}
          </div>
        ) : null}
        {item.resources?.length ? (
          <ul className="lib-resources">
            {item.resources.map((r, i) => (
              <li key={i}>
                <span className="lib-resource-kind">{r.type}</span>
                {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.name}</a> : r.name}
                {r.detail ? <span className="lib-resource-detail"> — {r.detail}</span> : null}
              </li>
            ))}
          </ul>
        ) : null}
        {/* Says exactly what was and was not captured. An item with no text and
            no explanation is indistinguishable from a bug. */}
        {item.capture_note
          ? <p className="lib-row-note"><Icon name="info" size={13} /> {item.capture_note}</p>
          : null}
      </div>
      <div className="lib-row-actions">
        {item.indexed && !item.summary ? (
          <button
            type="button"
            className="btn btn--ghost btn--small"
            disabled={busy}
            title="Work out what this is about, from the text it has"
            aria-label={`Summarise ${item.title}`}
            onClick={onEnrich}
          >
            <Icon name="spark" size={13} />
          </button>
        ) : null}
        {item.indexed ? (
          <button
            type="button"
            className="btn btn--ghost btn--small"
            disabled={busy}
            title="Index this text again — use after starting an embedding server"
            aria-label={`Re-index ${item.title}`}
            onClick={onReindex}
          >
            <Icon name="refresh" size={13} />
          </button>
        ) : null}
        <button
          type="button"
          className="btn btn--ghost btn--small"
          disabled={busy}
          aria-label={`Remove ${item.title}`}
          onClick={onDelete}
        >
          <Icon name="trash" size={13} />
        </button>
      </div>
    </article>
  )
}

/* Two ways in from outside this machine, and they are not the same thing.
 *
 * The bookmarklet is a navigation: it opens this page with the link prefilled.
 * It needs nothing switched on, because no cross-origin request happens.
 *
 * The token is for a phone posting to a deployed instance, and it is a real
 * credential — so it is off until asked for, shown once, and the panel says
 * plainly that it does not make the rest of this API safe to expose. */
function SharePanel({ toast }) {
  const [status, setStatus] = useState(null)
  const [token, setToken] = useState('')
  const origin = typeof window === 'undefined' ? '' : window.location.origin

  useEffect(() => {
    api.shareStatus().then(setStatus).catch(() => setStatus({ enabled: false }))
  }, [])

  const rotate = async () => {
    try {
      const next = await api.rotateShareToken()
      setToken(next.token)
      setStatus({ enabled: true })
      toast('Token created — copy it now, it is not shown again', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }

  const revoke = async () => {
    try {
      await api.revokeShareToken()
      setToken('')
      setStatus({ enabled: false })
      toast('Sharing switched off', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }

  return (
    <section className="card card-pad lib-share" data-enter>
      <div className="card-title">save from anywhere</div>
      <div className="set-rows">
        <div className="set-row">
          <span>
            Bookmarklet
            <span className="set-sub">
              Drag this to the bookmarks bar. On any page, it opens PSOK with the link filled in.
            </span>
          </span>
          <span className="set-row-tail">
            <a
              className="btn btn--small"
              href={bookmarklet(origin)}
              onClick={(e) => e.preventDefault()}
            >
              Save to PSOK
            </a>
          </span>
        </div>
        <div className="set-row">
          <span>
            Share token
            <span className="set-sub">
              For a phone shortcut posting to <code>POST /api/share/capture</code>. Capture only —
              it cannot read, list or run anything.
            </span>
          </span>
          <span className="set-row-tail">
            {status?.enabled ? (
              <>
                <button type="button" className="btn btn--ghost btn--small" onClick={rotate}>Rotate</button>
                <button type="button" className="btn btn--ghost btn--small" onClick={revoke}>Revoke</button>
              </>
            ) : (
              <button type="button" className="btn btn--small" onClick={rotate}>Create</button>
            )}
          </span>
        </div>
      </div>
      {token ? (
        <div className="lib-token">
          <code>{token}</code>
          <button type="button" className="btn btn--small" onClick={() => copyText(token)}>
            <Icon name="copy" size={13} /> Copy
          </button>
        </div>
      ) : null}
      <p className="set-note">
        A token does not make this instance safe to publish. Every other endpoint here is
        unauthenticated by design — if PSOK is reachable from the internet, put a proxy in front
        that exposes <code>/api/share/capture</code> and nothing else. See docs/deployment.md.
      </p>
    </section>
  )
}

/* Instagram capture: send a reel to the account, and it lands here.
 *
 * The panel is mostly about telling the truth about two things. The three
 * credentials are written and never read back — the server reports only whether
 * each is present. And the two routes are not equally good: a comment mention
 * carries the caption and the link, a direct message carries neither, so the
 * copy says which is which rather than letting somebody find out from a thin
 * item three weeks later. */
function InstagramPanel({ toast }) {
  const [state, setState] = useState(null)
  const [busy, setBusy] = useState('')
  const [form, setForm] = useState({ app_secret: '', verify_token: '', access_token: '', owner: '' })
  const origin = typeof window === 'undefined' ? '' : window.location.origin

  const load = useCallback(async () => {
    try { setState(await api.instagram()) } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { load() }, [load])

  const run = async (key, work, note) => {
    setBusy(key)
    try {
      setState(await work())
      if (note) toast(note, 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }

  if (!state) return null
  const { settings, credentials, configured } = state
  const missing = Object.entries(credentials).filter(([, ok]) => !ok).map(([k]) => k)

  return (
    <section className="card card-pad lib-share" data-enter>
      <div className="card-title">save from instagram</div>
      <p className="set-note">
        Comment <code>@your.account</code> on a reel and it is saved with its link and its
        full caption — that is the route worth using. Sending the reel as a direct message
        also works, but Instagram passes on the video and a title and <em>no</em> caption
        and <em>no</em> link, so those are only searchable once the audio has been
        transcribed.
      </p>

      {!configured ? (
        <>
          <p className="set-note">
            From your Meta app: the app secret, a verify token you invent, and a long-lived
            Instagram access token. They go straight to the OS keychain — nothing reads them
            back out. Still missing: <b>{missing.join(', ')}</b>.
          </p>
          <div className="lib-manual-grid">
            <input className="lib-input" placeholder="App secret" type="password"
              value={form.app_secret} onChange={(e) => setForm({ ...form, app_secret: e.target.value })} />
            <input className="lib-input" placeholder="Verify token (you choose this)"
              value={form.verify_token} onChange={(e) => setForm({ ...form, verify_token: e.target.value })} />
            <input className="lib-input" placeholder="Access token" type="password"
              value={form.access_token} onChange={(e) => setForm({ ...form, access_token: e.target.value })} />
            <input className="lib-input" placeholder="Your Instagram account id"
              value={form.owner} onChange={(e) => setForm({ ...form, owner: e.target.value })} />
          </div>
          <div className="set-inline" style={{ marginTop: 12 }}>
            <button type="button" className="btn btn--primary btn--small" disabled={busy === 'save'}
              onClick={() => run('save', async () => {
                const saved = await api.saveInstagramCredentials({
                  app_secret: form.app_secret || null,
                  verify_token: form.verify_token || null,
                  access_token: form.access_token || null,
                  expires_in_days: form.access_token ? 60 : null,
                })
                if (form.owner) await api.updateInstagram({ owner_ig_id: form.owner })
                setForm({ app_secret: '', verify_token: '', access_token: '', owner: '' })
                return saved
              }, 'Stored')}>
              {busy === 'save' ? 'Saving…' : 'Save credentials'}
            </button>
          </div>
        </>
      ) : (
        <div className="set-rows">
          <div className="set-row">
            <span>
              Accepting deliveries
              <span className="set-sub">
                Webhook URL: <code>{origin}{state.webhook_path}</code>
              </span>
            </span>
            <span className="set-row-tail">
              <button type="button" className={`btn btn--small${settings.enabled ? ' btn--primary' : ''}`}
                aria-pressed={settings.enabled} disabled={busy === 'toggle'}
                onClick={() => run('toggle',
                  () => api.updateInstagram({ enabled: !settings.enabled }),
                  settings.enabled ? 'Capture off' : 'Capture on')}>
                {settings.enabled ? 'On' : 'Off'}
              </button>
            </span>
          </div>

          <div className="set-row">
            <span>
              Who may save things
              <span className="set-sub">
                {settings.allow_senders.length
                  ? `Allowed: ${settings.allow_senders.join(', ')}`
                  : 'Nobody yet — anyone can message a public account, so nothing is saved until you say who.'}
              </span>
            </span>
          </div>

          {state.unknown_senders.map((sender) => (
            <div className="set-row" key={sender.sender_id}>
              <span>
                {sender.sender_id} sent you something
                <span className="set-sub">turned away {sender.attempts}× — not on the allowlist</span>
              </span>
              <span className="set-row-tail">
                <button type="button" className="btn btn--small" disabled={busy === sender.sender_id}
                  onClick={() => run(sender.sender_id,
                    () => api.allowInstagramSender(sender.sender_id), 'Allowed')}>
                  Allow
                </button>
              </span>
            </div>
          ))}

          <div className="set-row">
            <span>
              Reply “Saved” on Instagram
              <span className="set-sub">A write to your account, so it is off unless you ask</span>
            </span>
            <span className="set-row-tail">
              <button type="button" className={`btn btn--small${settings.reply_on_save ? ' btn--primary' : ''}`}
                aria-pressed={settings.reply_on_save} disabled={busy === 'reply'}
                onClick={() => run('reply', () => api.updateInstagram({ reply_on_save: !settings.reply_on_save }))}>
                {settings.reply_on_save ? 'On' : 'Off'}
              </button>
            </span>
          </div>

          <div className="set-row">
            <span>
              Transcription
              <span className="set-sub">
                {state.transcription
                  ? `${state.transcription.provider} · ${state.transcription.model}`
                  : 'None configured — a reel sent as a message will have no text at all'}
                {state.ffmpeg ? '' : ' · ffmpeg is not installed'}
              </span>
            </span>
          </div>
        </div>
      )}

      {state.token_expires_in_days !== null && state.token_expires_in_days < 14 ? (
        <p className="lib-token">
          <code>
            The Instagram token expires in {state.token_expires_in_days} days. Once it lapses it
            cannot be refreshed — only replaced.
          </code>
        </p>
      ) : null}

      <p className="set-note">
        This webhook is reachable from the internet by design, and its only authentication is
        Meta’s signature on each delivery. Every other endpoint here is unauthenticated — put a
        proxy in front that publishes <code>{state.webhook_path}</code> and nothing else. See
        docs/deployment.md.
      </p>
    </section>
  )
}
