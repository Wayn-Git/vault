import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api, fmtDate } from '../api.js'
import { SkeletonCard } from '../components/Skeleton.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'

/* The day, on one page.
 *
 * Every number here was measured. `/api/today` gathers the signals in Python
 * and hands back `degraded` naming anything it could not read, so a section
 * that says nothing says *why* rather than showing a confident zero — the whole
 * point of a morning page is that you can act on it without checking it.
 *
 * The briefing is prose over those same figures. When no model is configured
 * the figures are still here and the card says so; it never fills the gap. */

const WEEKDAY = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

/* The small hours belong to the evening that has not ended yet. Reading
   "Good morning" at half past one is the page telling you it is not paying
   attention, on the one screen whose whole job is to be right about today. */
function greeting(hour) {
  if (hour < 5) return 'Still up'
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

/** `2026-09-04T09:00:00` → `09:00`. Calendar rows are local naive already. */
function clock(value) {
  if (!value) return ''
  const time = String(value).replace(' ', 'T').slice(11, 16)
  return time || ''
}

function Panel({ title, action, children }) {
  return (
    <section className="card card-pad today-panel" data-enter>
      <div className="today-panel-head">
        <span className="card-title">{title}</span>
        {action}
      </div>
      {children}
    </section>
  )
}

/** Says what is missing and why, instead of letting a zero stand for it. */
function Unavailable({ reason }) {
  return (
    <p className="today-empty today-empty--why">
      <Icon name="info" size={14} /> {reason}
    </p>
  )
}

export default function Today() {
  const rootRef = useRef(null)
  const { toast, setView, health } = useApp()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState('')
  const [answers, setAnswers] = useState({})
  const loadToken = useRef(0)
  useViewEntrance(rootRef, [data === null])

  const load = useCallback(async () => {
    const token = ++loadToken.current
    try {
      const next = await api.today()
      if (loadToken.current !== token) return
      setData(next)
      setError(null)
    } catch (err) {
      if (loadToken.current !== token) return
      // Clearing the data too: a stale day under an error card reads as
      // half-loaded, which is worse than plainly saying it failed.
      setData(null)
      setError(err.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const now = new Date()
  const signals = data?.signals
  const degraded = data?.degraded ?? {}

  const generate = useCallback(async (kind) => {
    setBusy(kind)
    try {
      await api.generateJournal(kind, { force: true })
      await load()
      toast(kind === 'briefing' ? 'Briefing written' : 'Review written', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [load, toast])

  const submitReview = useCallback(async (entryId) => {
    const questions = data?.questions ?? []
    const written = questions
      .map((q, i) => [q, (answers[i] || '').trim()])
      .filter(([, a]) => a)
      .map(([q, a]) => `${q}\n${a}`)
      .join('\n\n')
    if (!written) {
      toast('Answer at least one question first', 'bad')
      return
    }
    setBusy('review')
    try {
      await api.answerJournal(entryId, written)
      await load()
      toast('Saved, and written up', 'ok')
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy('')
    }
  }, [answers, data, load, toast])

  const connectors = useMemo(() => ({
    awaiting: health?.connectors_awaiting_sign_in ?? [],
    broken: Object.keys(health?.connector_errors ?? {}),
    tools: health?.mcp_tools ?? 0,
  }), [health])

  if (error) {
    return (
      <div className="view" ref={rootRef}>
        <div className="view-inner view-inner--wide">
          <header className="vheader" data-enter>
            <div><h1>Today</h1></div>
          </header>
          <ErrorState message={error} onRetry={load} />
        </div>
      </div>
    )
  }

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="vheader" data-enter>
          <div>
            <h1>{greeting(now.getHours())}</h1>
            <div className="vheader-sub">
              {WEEKDAY[(now.getDay() + 6) % 7]}, {fmtDate(now.toISOString())}
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--ghost" onClick={load}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        {!data ? (
          <SkeletonCard title rows={4} />
        ) : (
          <>
            <Briefing
              entry={data.briefing}
              busy={busy === 'briefing'}
              onGenerate={() => generate('briefing')}
            />

            <div className="today-grid">
              <Panel
                title="today's schedule"
                action={
                  <button type="button" className="btn btn--ghost btn--small" onClick={() => setView('chat')}>
                    Add
                  </button>
                }
              >
                {signals.calendar.total === 0 ? (
                  <p className="today-empty">Nothing scheduled.</p>
                ) : (
                  <ul className="today-list">
                    {signals.calendar.items.map((event, i) => (
                      <li className="today-row" key={i}>
                        <span className="today-when mono">{clock(event.starts_at)}</span>
                        <span className="today-what">
                          {event.title}
                          {event.location ? <span className="today-sub">{event.location}</span> : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel
                title="what is owed"
                action={
                  <button type="button" className="btn btn--ghost btn--small" onClick={() => setView('tasks')}>
                    Tasks
                  </button>
                }
              >
                <div className="today-counts">
                  <span><b>{signals.tasks.my_day_count}</b> in My Day</span>
                  <span className={signals.tasks.overdue_count ? 'is-late' : ''}>
                    <b>{signals.tasks.overdue_count}</b> overdue
                  </span>
                  <span><b>{signals.tasks.completed_count}</b> done today</span>
                </div>
                {signals.tasks.overdue.length > 0 ? (
                  <ul className="today-list">
                    {signals.tasks.overdue.slice(0, 6).map((task, i) => (
                      <li className="today-row" key={i}>
                        <span className="today-when mono">{String(task.due_at || '').slice(5, 10)}</span>
                        <span className="today-what">{task.title}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="today-empty">Nothing overdue.</p>
                )}
              </Panel>

              <Panel
                title="inbox"
                action={
                  <button type="button" className="btn btn--ghost btn--small" onClick={() => setView('mail')}>
                    Open
                  </button>
                }
              >
                {degraded.mail ? (
                  <Unavailable reason={degraded.mail} />
                ) : (
                  <div className="today-counts">
                    <span><b>{signals.mail.unread ?? 0}</b> unread</span>
                    <span><b>{signals.mail.threads ?? 0}</b> threads</span>
                  </div>
                )}
              </Panel>

              <Panel
                title="logged today"
                action={
                  <button type="button" className="btn btn--ghost btn--small" onClick={() => setView('library')}>
                    Library
                  </button>
                }
              >
                {signals.library.total === 0 ? (
                  <p className="today-empty">Nothing logged yet today.</p>
                ) : (
                  <ul className="today-list">
                    {signals.library.items.map((item, i) => (
                      /* No time column here: what a library row wants said is
                         what it was, and `article` truncated to fit a clock
                         reads as a typo. */
                      <li className="today-row today-row--flat" key={i}>
                        <span className="today-what">
                          {item.title}
                          <span className="today-sub">
                            {[item.kind, item.author].filter(Boolean).join(' · ')}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
            </div>

            <Review
              entry={data.review}
              questions={data.questions}
              answers={answers}
              setAnswers={setAnswers}
              busy={busy === 'review'}
              generating={busy === 'daily'}
              onGenerate={() => generate('daily')}
              onSubmit={submitReview}
            />

            {/* Connected tools, read from the health the store already polls —
                asking /api/today for them would put a probe of every provider
                on the page most likely to be opened first. */}
            <section className="card card-pad" data-enter>
              <div className="today-panel-head">
                <span className="card-title">connected tools</span>
                <button
                  type="button"
                  className="btn btn--ghost btn--small"
                  onClick={() => setView('capabilities')}
                >
                  Manage
                </button>
              </div>
              {!health ? (
                <p className="today-empty">Checking…</p>
              ) : (
                <div className="today-counts">
                  <span><b>{connectors.tools}</b> connector tools live</span>
                  {connectors.awaiting.length > 0 && (
                    <span className="is-late">{connectors.awaiting.join(', ')} — not signed in</span>
                  )}
                  {connectors.broken.length > 0 && (
                    <span className="is-late">{connectors.broken.join(', ')} — not answering</span>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  )
}

function Briefing({ entry, busy, onGenerate }) {
  if (!entry) {
    return (
      <EmptyState
        icon="sun"
        message="No briefing has been written for today yet. It is filed automatically at the hour set in Settings."
        action={
          <button type="button" className="btn btn--small btn--primary" disabled={busy} onClick={onGenerate}>
            {busy ? 'Writing…' : 'Write it now'}
          </button>
        }
      />
    )
  }
  return (
    <section className="card card-pad brief" data-enter>
      <div className="today-panel-head">
        <span className="card-title">briefing</span>
        <button type="button" className="btn btn--ghost btn--small" disabled={busy} onClick={onGenerate}>
          <Icon name="refresh" size={13} /> {busy ? 'Writing…' : 'Regenerate'}
        </button>
      </div>
      {entry.summary ? (
        <div className="brief-body">
          {entry.summary.split('\n').filter(Boolean).map((line, i) => <p key={i}>{line}</p>)}
        </div>
      ) : (
        /* No prose, and the reason it is missing. The figures above are the
           briefing in that case; inventing a paragraph would make the page
           less true, not more useful. */
        <p className="today-empty today-empty--why">
          <Icon name="info" size={14} /> {entry.model_error || 'This entry has no summary yet.'}
        </p>
      )}
      {entry.model_name ? (
        <div className="brief-by mono">{entry.model_provider} · {entry.model_name}</div>
      ) : null}
    </section>
  )
}

function Review({ entry, questions, answers, setAnswers, busy, generating, onGenerate, onSubmit }) {
  if (!entry) {
    return (
      <EmptyState
        icon="edit"
        message="Tonight's check-in has not been filed yet. It appears at the review hour, or you can open it now."
        action={
          <button type="button" className="btn btn--small" disabled={generating} onClick={onGenerate}>
            {generating ? 'Opening…' : 'Open the check-in'}
          </button>
        }
      />
    )
  }

  if (entry.summary) {
    return (
      <section className="card card-pad review-card" data-enter>
        <div className="today-panel-head">
          <span className="card-title">tonight's review</span>
        </div>
        <div className="brief-body">
          {entry.summary.split('\n').filter(Boolean).map((line, i) => <p key={i}>{line}</p>)}
        </div>
      </section>
    )
  }

  return (
    <section className="card card-pad review-card" data-enter>
      <div className="today-panel-head">
        <span className="card-title">how did today go?</span>
      </div>
      {/* Filed with the day's real figures and no prose, on purpose: a review
          written before you have said anything can only reword the task list. */}
      <p className="set-note" style={{ marginTop: 0 }}>
        Answer what you want to. What you write is saved before anything is
        generated from it.
      </p>
      <div className="review-questions">
        {(questions ?? []).map((question, i) => (
          <label className="review-q" key={i}>
            <span>{question}</span>
            <textarea
              rows={2}
              value={answers[i] || ''}
              placeholder="…"
              onChange={(e) => setAnswers({ ...answers, [i]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <div className="review-actions">
        <button
          type="button"
          className="btn btn--primary btn--small"
          disabled={busy}
          onClick={() => onSubmit(entry.id)}
        >
          {busy ? 'Saving…' : 'Save the day'}
        </button>
        {entry.model_error ? <span className="today-sub">{entry.model_error}</span> : null}
      </div>
    </section>
  )
}
