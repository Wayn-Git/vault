import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../gsapFx.js'
import { api, fmtTime, prettyJSON } from '../api.js'

export default function Logs() {
  const rootRef = useRef(null)
  const { toast } = useApp()
  const [logs, setLogs] = useState([])
  const [filter, setFilter] = useState('')
  const [limit, setLimit] = useState(100)
  const [busy, setBusy] = useState(false)
  useViewEntrance(rootRef)

  const load = useCallback(async (n = limit) => {
    setBusy(true)
    try {
      setLogs(await api.logs(n))
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }, [limit, toast])

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return logs
    return logs.filter((l) =>
      [l.tool_name, l.tool_source, l.risk_level, l.confirmation_decision, l.result_summary, l.error]
        .some((v) => (v ? String(v).toLowerCase().includes(q) : false)),
    )
  }, [logs, filter])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <div className="vheader-eyebrow">
              <span className="led led--amber" /> sys / audit
            </div>
            <h1>Execution log</h1>
            <div className="vheader-sub">
              Every tool call from every source, with the decision that allowed it.
              Arguments are redacted before they reach this table.
            </div>
          </div>
          <div className="vheader-actions">
            <button type="button" className="btn btn--ghost" onClick={() => load()} disabled={busy}>
              <Icon name="refresh" size={15} /> {busy ? 'Loading…' : 'Reload'}
            </button>
          </div>
        </header>

        <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }} data-enter>
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="filter logs…"
            style={{
              background: 'var(--bg-sunken)', border: '1px solid var(--line)', borderRadius: 6,
              padding: '7px 12px', fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--text)', width: 220,
            }}
          />
          <select
            value={limit}
            onChange={(e) => { setLimit(Number(e.target.value)); load(Number(e.target.value)) }}
            style={{ background: 'var(--bg-sunken)', border: '1px solid var(--line)', borderRadius: 6, padding: '7px 10px', fontFamily: 'var(--font-mono)', fontSize: 12 }}
          >
            <option value={50}>last 50</option>
            <option value={100}>last 100</option>
            <option value={200}>last 200</option>
          </select>
          <span className="mono" style={{ alignSelf: 'center', fontSize: 11, color: 'var(--text-faint)' }}>
            {filtered.length} row{filtered.length === 1 ? '' : 's'}
          </span>
        </div>

        {filtered.length === 0 && (
          <div className="card empty-state" data-enter>
            <Icon name="logs" size={22} />
            No execution rows yet. Ask the agent to do something in Chat — every tool call lands here.
          </div>
        )}

        {filtered.length > 0 && (
          <div className="card" style={{ overflow: 'auto', maxHeight: 'calc(100vh - 260px)' }} data-enter>
            <table className="log-table">
              <thead>
                <tr>
                  <th>time</th>
                  <th>tool</th>
                  <th>source</th>
                  <th>risk</th>
                  <th>decision</th>
                  <th>ms</th>
                  <th>arguments</th>
                  <th>result / error</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((l) => (
                  <tr key={l.id}>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--text-faint)' }}>{fmtTime(l.created_at)}</td>
                    <td>
                      <span style={{ color: 'var(--amber)' }}>{l.tool_name}</span>
                      {l.tool_source === 'mcp' && <span className="badge" style={{ marginLeft: 6 }}>mcp</span>}
                    </td>
                    <td style={{ color: 'var(--text-faint)' }}>{l.tool_source}</td>
                    <td>
                      <span className={`badge badge--${l.risk_level === 'high' ? 'bad' : l.risk_level === 'medium' ? 'amber' : 'info'}`}>
                        {l.risk_level}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text-dim)' }}>
                      {l.confirmation_decision === 'denied' || l.confirmation_decision === 'denied_by_pref'
                        ? <span style={{ color: 'var(--bad)' }}>{l.confirmation_decision}</span>
                        : l.confirmation_decision}
                    </td>
                    <td style={{ color: 'var(--text-faint)' }}>{l.duration_ms ?? '—'}</td>
                    <td className="log-args" title={prettyJSON(l.arguments)}>{prettyJSON(l.arguments)}</td>
                    <td>
                      {l.error ? (
                        <span className="log-result log-result--error" title={l.error}>{l.error}</span>
                      ) : (
                        <span className="log-result" title={l.result_summary}>{l.result_summary ?? '—'}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}