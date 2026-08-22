import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api } from '../api.js'

/* What the agent put in the diary.

   Tasks and calendar events are created by the scheduling tools during a turn.
   Reading them back through a model call would be absurd, so this view reads
   the same rows the tools wrote. */

function when(value) {
  if (!value) return null
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export default function Tasks() {
  const rootRef = useRef(null)
  const { toast, setView, chat } = useApp()
  const [tasks, setTasks] = useState([])
  const [events, setEvents] = useState([])
  const [includeDone, setIncludeDone] = useState(false)
  useViewEntrance(rootRef)

  const load = useCallback(async () => {
    try {
      const [t, c] = await Promise.all([api.tasks(includeDone), api.calendar(21)])
      setTasks(t)
      setEvents(c)
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [includeDone, toast])

  useEffect(() => { load() }, [load])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner">
        <header className="vheader" data-enter>
          <div>
            <h1>Tasks and calendar</h1>
            <div className="vheader-sub">
              Created by the agent during a turn, resolved against the real clock rather than guessed.
            </div>
          </div>
          <div className="vheader-actions">
            <button
              type="button"
              className={`btn btn--small${includeDone ? ' btn--primary' : ' btn--ghost'}`}
              onClick={() => setIncludeDone((d) => !d)}
            >
              {includeDone ? 'Showing done' : 'Hiding done'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={load}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        <div className="card card-pad" style={{ marginBottom: 22 }} data-enter>
          <div className="card-title">tasks · {tasks.length}</div>
          {tasks.length === 0 && (
            <div className="empty-state" style={{ padding: 18 }}>
              <Icon name="check" size={20} />
              Nothing on the list. Ask PSOK to remember something to do and it lands here.
            </div>
          )}
          {tasks.map((task) => (
            <div className="server-row" key={task.id}>
              <div style={{ minWidth: 0 }}>
                <div className="server-name" style={{ whiteSpace: 'normal' }}>{task.title}</div>
                <div className="server-target">
                  {[
                    task.status,
                    task.priority ? `${task.priority} priority` : null,
                    task.due_at ? `due ${when(task.due_at)}` : null,
                    task.scheduled_at ? `scheduled ${when(task.scheduled_at)}` : null,
                  ].filter(Boolean).join(' · ')}
                </div>
                {task.notes && <div className="server-target">{task.notes}</div>}
              </div>
            </div>
          ))}
        </div>

        <div className="card card-pad" data-enter>
          <div className="card-title">next three weeks · {events.length}</div>
          {events.length === 0 && (
            <div className="empty-state" style={{ padding: 18 }}>
              <Icon name="clock" size={20} />
              No events. Scheduling one asks first, and checks for conflicts before it writes.
            </div>
          )}
          {events.map((event) => (
            <div className="server-row" key={event.id}>
              <div style={{ minWidth: 0 }}>
                <div className="server-name" style={{ whiteSpace: 'normal' }}>{event.title}</div>
                <div className="server-target">
                  {when(event.starts_at)}{event.ends_at ? ` → ${when(event.ends_at)}` : ''}
                  {event.location ? ` · ${event.location}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div style={{ marginTop: 18 }} data-enter>
          <button
            type="button"
            className="btn btn--small"
            onClick={() => { setView('chat'); chat.focusComposer?.() }}
          >
            <Icon name="chat" size={13} /> Ask PSOK to add one
          </button>
        </div>
      </div>
    </div>
  )
}
