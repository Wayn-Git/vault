import { useEffect, useState } from 'react'
import Icon from './Icon.jsx'

/* The frame the interface draws while it is waiting for its first answer.

   Two different waits, and they deserve different treatment.

   The ordinary one is a request in flight against a backend that is already up:
   under a second, and what belongs there is the *shape* of what is coming, so
   the page does not jump when it arrives. That is `Skeleton` and the helpers
   below it — blocks the size of the rows they stand in for.

   The other is a container that was stopped for want of traffic and is booting.
   That is tens of seconds, and a shimmering rectangle for tens of seconds reads
   as a hang. So `BootScreen` says what is happening and counts, which is the
   difference between "this is broken" and "this is nearly ready".

   Nothing here animates under `prefers-reduced-motion` — a page of pulsing
   blocks is exactly the kind of thing that rule exists for. */

export default function Skeleton({ w = '100%', h = 12, r = 6, style, className = '' }) {
  return (
    <span
      className={`skel ${className}`.trim()}
      aria-hidden="true"
      style={{ width: w, height: h, borderRadius: r, ...style }}
    />
  )
}

/** A paragraph's worth. The last line is short, because real ones are. */
export function SkeletonText({ lines = 3, gap = 8 }) {
  return (
    <div className="skel-stack" style={{ gap }}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} w={i === lines - 1 ? '58%' : `${88 - (i % 3) * 9}%`} h={11} />
      ))}
    </div>
  )
}

/** Standing in for `.server-row` — an icon, two lines of text, some controls. */
export function SkeletonRows({ rows = 4, controls = 2 }) {
  return (
    <div className="skel-rows" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <div className="skel-row" key={i}>
          <Skeleton w={18} h={18} r={6} />
          <div className="skel-row-text">
            <Skeleton w={`${52 + ((i * 13) % 30)}%`} h={12} />
            <Skeleton w={`${28 + ((i * 17) % 26)}%`} h={9} />
          </div>
          {Array.from({ length: controls }, (_, c) => (
            <Skeleton key={c} w={20} h={20} r={7} />
          ))}
        </div>
      ))}
    </div>
  )
}

/** A card with a title and some rows in it, for a view built out of cards. */
export function SkeletonCard({ title = true, rows = 3, controls = 2 }) {
  return (
    <div className="card card-pad" aria-hidden="true">
      {title && <Skeleton w={140} h={11} style={{ marginBottom: 14 }} />}
      <SkeletonRows rows={rows} controls={controls} />
    </div>
  )
}

/** The grid of cards the skills and catalogue pages are made of. */
export function SkeletonGrid({ cards = 6 }) {
  return (
    <div className="skel-grid" aria-hidden="true">
      {Array.from({ length: cards }, (_, i) => (
        <div className="skel-card" key={i}>
          <Skeleton w={22} h={22} r={8} />
          <Skeleton w={`${58 + ((i * 11) % 26)}%`} h={12} />
          <Skeleton w="90%" h={9} />
          <Skeleton w="64%" h={9} />
        </div>
      ))}
    </div>
  )
}

/** A whole view's worth: the header, then its body. */
export function SkeletonView({ rows = 5, aside = false }) {
  return (
    <div className="view">
      <div className={`view-inner${aside ? ' view-inner--wide' : ''}`}>
        <header className="vheader">
          <div className="skel-stack" style={{ gap: 10 }}>
            <Skeleton w={132} h={20} r={7} />
            <Skeleton w={320} h={10} />
          </div>
        </header>
        {aside ? (
          <div className="task-layout">
            <nav className="skel-rail" aria-hidden="true">
              {Array.from({ length: 6 }, (_, i) => <Skeleton key={i} w="100%" h={30} r={9} />)}
            </nav>
            <section><SkeletonCard rows={rows} /></section>
          </div>
        ) : (
          <SkeletonCard rows={rows} />
        )}
      </div>
    </div>
  )
}

/* How long the wait has been going, in whole seconds.

   Shown only once it is long enough to be worth mentioning. A counter that
   starts at zero on a backend that answers in 80ms is a flash of noise; one
   that appears at four seconds is the page telling you it knows it is slow. */
function useElapsed(since) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(tick)
  }, [])
  return Math.max(0, Math.round((now - since) / 1000))
}

export function BootScreen({ server, onRetry }) {
  const seconds = useElapsed(server.since || Date.now())
  const down = server.phase === 'down'
  const slow = seconds >= 4

  return (
    <div className="boot" role="status" aria-live="polite">
      <div className="boot-inner">
        <div className={`boot-mark${down ? ' is-down' : ''}`}>
          <Icon name={down ? 'alert' : 'spark'} size={22} />
        </div>
        <h1 className="boot-title">{down ? 'The backend did not answer' : 'Waking the backend'}</h1>
        <p className="boot-note">
          {down
            ? server.error
            : slow
              ? 'A container that has been idle is starting up. This is the slow path and it'
                + ' only happens on the first request after a quiet spell.'
              : 'One moment.'}
        </p>

        {!down && (
          <>
            <div className="boot-bar"><span /></div>
            {slow && <div className="boot-count">{seconds}s</div>}
          </>
        )}

        {down && (
          <button type="button" className="btn btn--primary btn--small" onClick={onRetry}>
            <Icon name="refresh" size={13} /> Try again
          </button>
        )}

        {/* The page underneath, in outline, so the wait is spent looking at
            where things will be rather than at a spinner in the void. */}
        <div className="boot-ghost" aria-hidden="true">
          <div className="boot-ghost-rail">
            {Array.from({ length: 5 }, (_, i) => <Skeleton key={i} w="100%" h={26} r={8} />)}
          </div>
          <div className="boot-ghost-main">
            <Skeleton w="46%" h={16} r={7} />
            <SkeletonText lines={3} />
            <Skeleton w="100%" h={44} r={12} />
          </div>
        </div>
      </div>
    </div>
  )
}
