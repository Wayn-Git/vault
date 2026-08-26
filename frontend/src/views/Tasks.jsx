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

/* What the reminder loop will do with this row, in the row's own words.
   `reminder_at` when set, otherwise the deadline, and nothing at all when there
   is neither -- which is the honest answer, not a silent default. */
function reminder(task) {
  const at = task.reminder_at || task.due_at
  if (!at) return null
  if (task.reminded_at) return `reminded ${when(task.reminded_at)}`
  return `reminder ${when(at)}`
}

/* Adding a task without a model call.
   The date is typed the way it is spoken -- "tomorrow", "friday 5pm" -- and
   resolved on the server by the same scheduling engine the agent's tools use,
   so a task typed here and one created in a turn cannot disagree about what
   "tomorrow" means. */
function Composer({ onAdded, onCancel }) {
  const { toast } = useApp()
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  const [remind, setRemind] = useState('')
  const [busy, setBusy] = useState(false)
  const ready = title.trim().length > 0

  const submit = async (event) => {
    event.preventDefault()
    if (!ready || busy) return
    setBusy(true)
    try {
      await api.createTask({
        title: title.trim(),
        due_date_hint: due.trim() || null,
        reminder_hint: remind.trim() || null,
      })
      setTitle(''); setDue(''); setRemind('')
      toast('Task added', 'ok')
      onAdded()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="task-composer" onSubmit={submit} data-enter>
      <input
        autoFocus
        value={title}
        placeholder="What needs doing?"
        aria-label="Task"
        onChange={(e) => setTitle(e.target.value)}
      />
      <div className="task-composer-row">
        <input
          value={due}
          placeholder="Due — tomorrow, friday 5pm"
          aria-label="Due date"
          onChange={(e) => setDue(e.target.value)}
        />
        <input
          value={remind}
          placeholder="Remind me — optional"
          aria-label="Reminder"
          onChange={(e) => setRemind(e.target.value)}
        />
        <button type="submit" className="btn btn--primary btn--small" disabled={!ready || busy}>
          {busy ? 'Adding…' : 'Add'}
        </button>
        <button type="button" className="btn btn--ghost btn--small" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <span className="field-note">
        Dates are resolved against the real clock. Leave the reminder blank to be told at the
        deadline; leave both blank and nothing is announced.
      </span>
    </form>
  )
}

export default function Tasks() {
  const rootRef = useRef(null)
  const { toast, setView, chat } = useApp()
  const [tasks, setTasks] = useState([])
  const [events, setEvents] = useState([])
  const [includeDone, setIncludeDone] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [busyTask, setBusyTask] = useState(null)
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

  const setStatus = useCallback(async (task, status) => {
    setBusyTask(task.id)
    try {
      await api.updateTask(task.id, { status })
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusyTask(null)
    }
  }, [load, toast])

  const drop = useCallback(async (task) => {
    setBusyTask(task.id)
    try {
      await api.deleteTask(task.id)
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setBusyTask(null)
    }
  }, [load, toast])

  /* Microsoft To Do is pulled on a fifteen-minute loop while PSOK is up. This
     is the same pull on demand, for the minute after someone signs in. */
  const sync = useCallback(async () => {
    setSyncing(true)
    try {
      const report = await api.syncTasks()
      toast(report.summary, 'ok')
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setSyncing(false)
    }
  }, [load, toast])

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
            <button
              type="button"
              className="btn btn--primary btn--small"
              onClick={() => setAdding((a) => !a)}
            >
              <Icon name="plus" size={15} /> New task
            </button>
            <button type="button" className="btn btn--ghost" disabled={syncing} onClick={sync}>
              <Icon name="refresh" size={15} /> {syncing ? 'Syncing…' : 'Sync To Do'}
            </button>
            <button type="button" className="btn btn--ghost" onClick={load}>
              <Icon name="refresh" size={15} /> Refresh
            </button>
          </div>
        </header>

        <div className="card card-pad" style={{ marginBottom: 22 }} data-enter>
          <div className="card-title">tasks · {tasks.length}</div>
          {adding && <Composer onAdded={load} onCancel={() => setAdding(false)} />}
          {tasks.length === 0 && (
            <div className="empty-state" style={{ padding: 18 }}>
              <Icon name="check" size={20} />
              Nothing on the list. Add one above, or ask PSOK to remember something to do.
            </div>
          )}
          {tasks.map((task) => {
            const done = task.status === 'done'
            return (
              <div className={`server-row task-row${done ? ' task-row--done' : ''}`} key={task.id}>
                {/* The checkbox is the whole point of a task list, and there was
                    no way to tick one: marking something done meant asking the
                    model to, which is a model call to change one column. */}
                <button
                  type="button"
                  className={`task-check${done ? ' task-check--on' : ''}`}
                  disabled={busyTask === task.id}
                  aria-label={done ? `Mark ${task.title} not done` : `Mark ${task.title} done`}
                  aria-pressed={done}
                  onClick={() => setStatus(task, done ? 'todo' : 'done')}
                >
                  {done && <Icon name="check" size={12} />}
                </button>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="server-name task-title">{task.title}</div>
                  <div className="server-target">
                    {[
                      task.status,
                      task.priority ? `${task.priority} priority` : null,
                      task.due_at ? `due ${when(task.due_at)}` : null,
                      task.scheduled_at ? `scheduled ${when(task.scheduled_at)}` : null,
                      reminder(task),
                      task.external_source ? `from ${task.external_source}` : null,
                    ].filter(Boolean).join(' · ')}
                  </div>
                  {task.notes && <div className="server-target">{task.notes}</div>}
                </div>
                <button
                  type="button"
                  className="icon-btn task-drop"
                  disabled={busyTask === task.id}
                  title="Cancel this task"
                  aria-label={`Cancel ${task.title}`}
                  onClick={() => drop(task)}
                >
                  <Icon name="x" size={14} />
                </button>
              </div>
            )
          })}
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
