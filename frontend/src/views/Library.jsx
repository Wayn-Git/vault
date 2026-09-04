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
                onDelete={() => act(item, () => api.deleteLibraryItem(item.id), 'Removed')}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ item, busy, onReindex, onDelete }) {
  return (
    <article className="card lib-row" data-enter>
      <div className="lib-row-icon"><Icon name={KIND_ICON[item.kind] || 'link'} size={18} /></div>
      <div className="lib-row-body">
        <div className="lib-row-title">
          {item.url
            ? <a href={item.url} target="_blank" rel="noreferrer">{item.title}</a>
            : item.title}
        </div>
        <div className="lib-row-meta mono">
          {[item.kind, item.author, item.site, fmtDate(item.consumed_on)].filter(Boolean).join(' · ')}
        </div>
        {item.excerpt ? <p className="lib-row-excerpt">{item.excerpt}</p> : null}
        {item.notes && !item.excerpt ? <p className="lib-row-excerpt">{item.notes}</p> : null}
        {/* Says exactly what was and was not captured. An item with no text and
            no explanation is indistinguishable from a bug. */}
        {item.capture_note
          ? <p className="lib-row-note"><Icon name="info" size={13} /> {item.capture_note}</p>
          : null}
      </div>
      <div className="lib-row-actions">
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
