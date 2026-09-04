import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api, copyText, fmtTime, prettyJSON } from '../api.js'
import { SkeletonRows } from '../components/Skeleton.jsx'
import EmptyState from '../components/ui/EmptyState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import Table from '../components/ui/Table.jsx'

/* Every tool call, with the decision that allowed it.

   Two presentations of one list, because a phone and a desk want different
   things from an audit trail. Eight columns is the right shape at a desk: the
   value of this page is scanning down `decision` and `risk` and seeing the one
   row that is not like the others. Eight columns on a 390px screen is a
   sideways scroll nobody performs, so below the breakpoint each row becomes a
   block — the same fields, stacked, with the two that carry the judgement
   (risk and decision) promoted to the top line. */

const LIMITS = [50, 100, 200, 500]

/* Which decisions are worth being able to isolate. Taken from what the server
   actually writes rather than invented here: `confirmation_decision` is one of
   these or null, and `error` is a column, not a decision. */
const LENSES = [
  { id: 'all', label: 'Everything' },
  { id: 'asked', label: 'Asked first', match: (l) => l.confirmation_decision === 'approved' },
  { id: 'denied', label: 'Refused', match: (l) => String(l.confirmation_decision || '').startsWith('denied') },
  { id: 'failed', label: 'Failed', match: (l) => Boolean(l.error) },
  { id: 'risky', label: 'Medium and high risk', match: (l) => l.risk_level !== 'low' },
]

const riskTone = (level) => (level === 'high' ? 'bad' : level === 'medium' ? 'amber' : 'info')

function decisionText(value) {
  if (!value) return '—'
  return value
}

/** One call, as a block. The phone form. */
function LogCard({ row, onCopy }) {
  const [open, setOpen] = useState(false)
  const failed = Boolean(row.error)
  return (
    <div className={`log-card${failed ? ' log-card--failed' : ''}`} data-open={open}>
      <button
        type="button"
        className="log-card-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="log-card-tool">{row.tool_name}</span>
        <span className={`badge badge--${riskTone(row.risk_level)}`}>{row.risk_level}</span>
        <Icon name="chevron" size={12} className="log-card-caret" />
      </button>
      <div className="log-card-meta">
        <span>{fmtTime(row.created_at)}</span>
        <span>{row.tool_source}</span>
        <span className={String(row.confirmation_decision || '').startsWith('denied') ? 'log-denied' : undefined}>
          {decisionText(row.confirmation_decision)}
        </span>
        {row.duration_ms != null && <span>{row.duration_ms}ms</span>}
      </div>
      <p className={`log-card-result${failed ? ' log-result--error' : ''}`}>
        {row.error || row.result_summary || 'No result recorded.'}
      </p>
      {open && (
        <div className="log-card-args">
          <span className="tool-block-label">arguments</span>
          <pre className="tool-json">{prettyJSON(row.arguments)}</pre>
          <button type="button" className="btn btn--ghost btn--small" onClick={() => onCopy(row)}>
            <Icon name="copy" size={12} /> Copy this row
          </button>
        </div>
      )}
    </div>
  )
}

export default function Logs() {
  const rootRef = useRef(null)
  const { toast, compact } = useApp()
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)
  const [filter, setFilter] = useState('')
  const [lens, setLens] = useState('all')
  const [limit, setLimit] = useState(100)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  // The first response, distinct from `busy`: a reload keeps the rows on screen,
  // but the opening render has nothing to keep and must not claim the log is
  // empty before it has looked.
  const [loaded, setLoaded] = useState(false)
  useViewEntrance(rootRef)

  const load = useCallback(async (n = limit) => {
    setBusy(true)
    try {
      setLogs(await api.logs(n))
      setError(null)
    } catch (err) {
      // `loaded` still flips true below, so without this a failed fetch
      // rendered the identical "No execution rows yet" copy a genuinely
      // empty log shows -- there was no way to tell them apart.
      setError(err.message)
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
      setLoaded(true)
    }
  }, [limit, toast])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Watching a turn happen is the reason to have this view open at all, and a
  // trail you have to keep reloading by hand is not a trail you watch.
  useEffect(() => {
    if (!live) return undefined
    const tick = setInterval(() => load(), 4000)
    return () => clearInterval(tick)
  }, [live, load])

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const match = LENSES.find((l) => l.id === lens)?.match
    return logs.filter((l) => {
      if (match && !match(l)) return false
      if (!q) return true
      return [l.tool_name, l.tool_source, l.risk_level, l.confirmation_decision, l.result_summary, l.error]
        .some((v) => (v ? String(v).toLowerCase().includes(q) : false))
    })
  }, [logs, filter, lens])

  /* Counted over everything loaded, not over what the current lens shows —
     a lens whose own tab reported zero while it was selected would be a tab
     nobody could ever find a reason to press. */
  const lensCounts = useMemo(() => {
    const out = {}
    for (const l of LENSES) out[l.id] = l.match ? logs.filter(l.match).length : logs.length
    return out
  }, [logs])

  const copyRow = useCallback(async (row) => {
    const text = [
      `${fmtTime(row.created_at)}  ${row.tool_name}  (${row.tool_source}, ${row.risk_level} risk)`,
      `decision: ${decisionText(row.confirmation_decision)}${row.duration_ms != null ? `  ${row.duration_ms}ms` : ''}`,
      `arguments: ${prettyJSON(row.arguments)}`,
      row.error ? `error: ${row.error}` : `result: ${row.result_summary ?? '—'}`,
    ].join('\n')
    const ok = await copyText(text)
    toast(
      ok ? 'Row copied' : 'Could not copy — this page is not on a secure origin',
      ok ? 'ok' : 'bad',
    )
  }, [toast])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="vheader" data-enter>
          <div>
            <h1>Execution log</h1>
            <div className="vheader-sub">
              Every tool call from every source, with the decision that allowed it.
              Arguments are redacted before they reach this page. What runs
              without asking is listed under Settings → Permissions.
            </div>
          </div>
          <div className="vheader-actions">
            <button
              type="button"
              className={`btn btn--small${live ? ' btn--primary' : ' btn--ghost'}`}
              onClick={() => setLive((l) => !l)}
              aria-pressed={live}
              title="Reload every few seconds while a turn runs"
            >
              {live ? 'Following' : 'Follow'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => load()} disabled={busy}>
              <Icon name="refresh" size={15} /> {busy ? 'Loading…' : 'Reload'}
            </button>
          </div>
        </header>

        {/* Lenses rather than one free-text box doing everything: "show me what
            was refused" is the question this page exists to answer, and typing
            `denied` to get it is a trick you have to already know. */}
        <div className="log-lenses" role="group" aria-label="Filter by decision" data-enter>
          {LENSES.map((l) => (
            <button
              key={l.id}
              type="button"
              className={`chip${lens === l.id ? ' is-on' : ''}`}
              aria-pressed={lens === l.id}
              onClick={() => setLens(l.id)}
            >
              {l.label}
              <span className="chip-count">{loaded ? lensCounts[l.id] : '—'}</span>
            </button>
          ))}
        </div>

        <div className="log-controls" data-enter>
          <div className="inline-search">
            <Icon name="search" size={13} />
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Filter by tool, source or result"
              aria-label="Filter the log"
            />
            {filter && (
              <button type="button" className="icon-btn" onClick={() => setFilter('')} aria-label="Clear filter">
                <Icon name="x" size={13} />
              </button>
            )}
          </div>
          <label className="inline-select">
            <span>Show</span>
            <select
              value={limit}
              aria-label="How many rows to load"
              onChange={(e) => { setLimit(Number(e.target.value)); load(Number(e.target.value)) }}
            >
              {LIMITS.map((n) => <option key={n} value={n}>last {n}</option>)}
            </select>
          </label>
          <span className="log-count mono">
            {loaded ? `${filtered.length} row${filtered.length === 1 ? '' : 's'}` : 'loading…'}
          </span>
        </div>

        {!loaded && <div className="card card-pad" data-enter><SkeletonRows rows={8} controls={1} /></div>}

        {loaded && error && <ErrorState message={error} onRetry={() => load()} />}

        {loaded && !error && filtered.length === 0 && (
          <EmptyState icon="logs">
            {logs.length === 0
              ? 'No execution rows yet. Ask the agent to do something in Chat — every tool call lands here.'
              : 'Nothing in the log matches that. Clear the filter, or widen the lens above.'}
          </EmptyState>
        )}

        {loaded && !error && filtered.length > 0 && (
          compact ? (
            <div className="log-cards" data-enter>
              {filtered.map((l) => <LogCard key={l.id} row={l} onCopy={copyRow} />)}
            </div>
          ) : (
            <div className="card log-table-wrap" data-enter>
              <Table>
                <Table.Head>
                  <th scope="col">time</th>
                  <th scope="col">tool</th>
                  <th scope="col">source</th>
                  <th scope="col">risk</th>
                  <th scope="col">decision</th>
                  <th scope="col">ms</th>
                  <th scope="col">arguments</th>
                  <th scope="col">result / error</th>
                </Table.Head>
                <Table.Body>
                  {filtered.map((l) => (
                    <Table.Row key={l.id}>
                      <Table.Cell className="log-when">{fmtTime(l.created_at)}</Table.Cell>
                      <Table.Cell className="log-tool" title={l.tool_name}>{l.tool_name}</Table.Cell>
                      <Table.Cell className="log-dim">{l.tool_source}</Table.Cell>
                      <Table.Cell>
                        <span className={`badge badge--${riskTone(l.risk_level)}`}>{l.risk_level}</span>
                      </Table.Cell>
                      <Table.Cell className="log-decision">
                        {String(l.confirmation_decision || '').startsWith('denied')
                          ? <span className="log-denied">{l.confirmation_decision}</span>
                          : decisionText(l.confirmation_decision)}
                      </Table.Cell>
                      <Table.Cell className="log-dim">{l.duration_ms ?? '—'}</Table.Cell>
                      <Table.Cell className="log-args" title={prettyJSON(l.arguments)}>{prettyJSON(l.arguments)}</Table.Cell>
                      <Table.Cell>
                        {l.error ? (
                          <span className="log-result log-result--error" title={l.error}>{l.error}</span>
                        ) : (
                          <span className="log-result" title={l.result_summary}>{l.result_summary ?? '—'}</span>
                        )}
                      </Table.Cell>
                    </Table.Row>
                  ))}
                </Table.Body>
              </Table>
            </div>
          )
        )}
      </div>
    </div>
  )
}
