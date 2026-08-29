import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import { useApp } from '../store.jsx'
import { useViewEntrance } from '../motion.js'
import { api } from '../api.js'
import { SkeletonRows } from '../components/Skeleton.jsx'

/* The task list, in the shape people already keep tasks in.

   Buckets are computed on the server, never stored: "missed" is a query, not a
   flag someone has to set and something has to unset. The counts and the rows
   come from the same predicate, so a rail saying 5 over a list of 4 is not a
   state this can reach.

   My Day is a list. To Do's own My Day is not in its API at all -- verified
   live, not assumed: showInMyDay and isInMyDay both 400 as unknown properties
   on todoTask, and the live beta schema has no field containing "day" -- and a
   "My Day" category, which was the previous answer, is invisible to a task
   added through To Do's own My Day on the phone. An ordinary list called My Day
   is the one thing both ends can see and edit. So the sun *moves* a task into
   that list, and the list is this bucket. */

const BUCKETS = [
  { id: 'my_day', label: 'My Day', icon: 'sun', blurb: 'Your To Do list called My Day.' },
  { id: 'missed', label: 'Missed', icon: 'clock', blurb: 'Past its deadline and still open.' },
  { id: 'important', label: 'Important', icon: 'star', blurb: 'Flagged, whatever the date.' },
  { id: 'general', label: 'General', icon: 'list', blurb: 'No date attached.' },
  { id: 'all', label: 'All open', icon: 'check', blurb: 'Everything still to do.' },
  { id: 'completed', label: 'Completed', icon: 'archive', blurb: 'Done. Cancelled is not done.' },
]

function when(value) {
  if (!value) return null
  const date = new Date(value.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function isOverdue(task) {
  if (!task.due_at || task.status === 'done' || task.status === 'cancelled') return false
  return new Date(task.due_at.replace(' ', 'T')) < new Date(new Date().toDateString())
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
   "tomorrow" means. Every field the API accepts is here: the composer used to
   offer three of them, which made the browser the least capable way to make a
   task. */
function Composer({ lists, presetList, onAdded, onCancel }) {
  const { toast } = useApp()
  const [title, setTitle] = useState('')
  const [due, setDue] = useState('')
  const [remind, setRemind] = useState('')
  const [notes, setNotes] = useState('')
  const [list, setList] = useState(presetList || '')
  const [important, setImportant] = useState(false)
  const [myDay, setMyDay] = useState(false)
  const [busy, setBusy] = useState(false)
  const ready = title.trim().length > 0

  const submit = async (event) => {
    event.preventDefault()
    if (!ready || busy) return
    setBusy(true)
    try {
      const made = await api.createTask({
        title: title.trim(),
        notes: notes.trim() || null,
        due_date_hint: due.trim() || null,
        reminder_hint: remind.trim() || null,
        list: list || null,
        important,
        add_to_my_day: myDay,
      })
      setTitle(''); setDue(''); setRemind(''); setNotes('')
      toast(made.routed_to ? `Task added — ${made.routed_to}` : 'Task added', 'ok')
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
        <select value={list} aria-label="List" onChange={(e) => setList(e.target.value)}>
          <option value="">Default list</option>
          {lists.map((l) => <option key={l.id} value={l.name}>{l.name}</option>)}
        </select>
      </div>
      <div className="task-composer-row">
        <input
          value={notes}
          placeholder="Notes — optional"
          aria-label="Notes"
          onChange={(e) => setNotes(e.target.value)}
        />
        <button
          type="button"
          className={`btn btn--small${important ? ' btn--primary' : ' btn--ghost'}`}
          aria-pressed={important}
          onClick={() => setImportant((v) => !v)}
        >
          <Icon name="star" size={13} /> Important
        </button>
        <button
          type="button"
          className={`btn btn--small${myDay ? ' btn--primary' : ' btn--ghost'}`}
          aria-pressed={myDay}
          onClick={() => setMyDay((v) => !v)}
        >
          <Icon name="sun" size={13} /> My Day
        </button>
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
  const [view, setViewKey] = useState({ bucket: 'my_day', listId: null })
  // Whether the landing view has already been settled for this mount. My Day is
  // the right place to start a day and the wrong place to start a session that
  // has nothing in it -- an empty default view reads as a broken page.
  const landed = useRef(false)
  const [tasks, setTasks] = useState([])
  const [counts, setCounts] = useState({
    buckets: {}, lists: [], connected: false, my_day_list_id: null,
  })
  const [events, setEvents] = useState([])
  const [syncing, setSyncing] = useState(false)
  const [adding, setAdding] = useState(false)
  const [busyTask, setBusyTask] = useState(null)
  // Whether the first response has landed. Without it the empty states render
  // against an empty array — so the page opened on "Nothing picked for today
  // yet", complete with its explanation, and then replaced it with the day's
  // tasks. A page that says the wrong thing first is worse than one that says
  // nothing yet.
  const [loaded, setLoaded] = useState(false)
  useViewEntrance(rootRef)

  const load = useCallback(async () => {
    try {
      const [rows, summary, cal] = await Promise.all([
        api.tasks(view.listId ? { listId: view.listId } : { bucket: view.bucket }),
        api.taskBuckets(),
        api.calendar(21),
      ])
      setTasks(rows)
      setCounts(summary)
      setEvents(cal)
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setLoaded(true)
    }
  }, [view, toast])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    // `counts` starts as an empty shape, and `{}` is truthy -- so guarding on
    // its presence settled the landing view against zeroes before the first
    // response arrived, and then refused to reconsider. Wait for real data.
    if (landed.current || !counts.buckets || Object.keys(counts.buckets).length === 0) return
    const { my_day: myDay = 0, missed = 0, all = 0 } = counts.buckets
    landed.current = true
    if (myDay > 0) return
    // Nothing chosen for today: show the thing that most wants attention rather
    // than an empty room.
    if (missed > 0) setViewKey({ bucket: 'missed', listId: null })
    else if (all > 0) setViewKey({ bucket: 'all', listId: null })
  }, [counts])

  const patch = useCallback(async (task, body, note) => {
    setBusyTask(task.id)
    try {
      await api.updateTask(task.id, body)
      if (note) toast(note, 'ok')
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

  /* Microsoft To Do is pushed and pulled on a fifteen-minute loop while PSOK is
     up. This is the same sync on demand, for the minute after someone signs in
     or ticks something they want on their phone now. */
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

  /* Opening the page is a request for current tasks, so it asks for one --
     quietly, once per mount, behind whatever is already on screen. The timer
     behind this runs every ninety seconds, which is close enough for a list
     left open and too far away for a list you have just walked back to.
     Failures are silent on purpose: the rows already rendered are still true,
     and the "Sync To Do" button is there for anyone who wants to be told. */
  const synced = useRef(false)
  useEffect(() => {
    if (synced.current) return
    synced.current = true
    let cancelled = false
    api.syncTasks().then(() => { if (!cancelled) load() }).catch(() => {})
    return () => { cancelled = true }
  }, [load])

  const newList = useCallback(async () => {
    const name = window.prompt('Name the list')
    if (!name?.trim()) return
    try {
      const made = await api.createTaskList(name.trim())
      toast(made.note ? `List created — ${made.note}` : 'List created', 'ok')
      await load()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [load, toast])

  const active = useMemo(() => {
    if (view.listId) {
      const found = counts.lists.find((l) => l.id === view.listId)
      return { label: found?.name || 'List', blurb: found?.external_id ? null : LOCAL_ONLY }
    }
    return BUCKETS.find((b) => b.id === view.bucket) || BUCKETS[0]
  }, [view, counts])

  return (
    <div className="view" ref={rootRef}>
      <div className="view-inner view-inner--wide">
        <header className="vheader" data-enter>
          <div>
            <h1>Tasks</h1>
            <div className="vheader-sub">
              {counts.connected
                ? 'Tasks, lists, dates and importance sync both ways with Microsoft To Do. My Day is your To Do list called My Day — the sun moves a task into it.'
                : 'Kept in PSOK. Sign in to Microsoft To Do from Connectors and these follow you.'}
            </div>
          </div>
          <div className="vheader-actions">
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
          </div>
        </header>

        <div className="task-layout" data-enter>
          <nav className="task-rail" aria-label="Task views">
            {BUCKETS.map((bucket) => (
              <button
                key={bucket.id}
                type="button"
                className={`task-rail-row${!view.listId && view.bucket === bucket.id ? ' is-on' : ''}`}
                aria-current={!view.listId && view.bucket === bucket.id}
                onClick={() => setViewKey({ bucket: bucket.id, listId: null })}
              >
                <Icon name={bucket.icon} size={15} />
                <span className="task-rail-label">{bucket.label}</span>
                <span className="task-rail-count">{loaded ? (counts.buckets?.[bucket.id] ?? 0) : ''}</span>
              </button>
            ))}

            <div className="task-rail-head">
              <span>Lists</span>
              <button type="button" className="icon-btn" title="New list" onClick={newList}>
                <Icon name="plus" size={13} />
              </button>
            </div>
            {loaded
              && counts.lists.filter((l) => l.id !== counts.my_day_list_id).length === 0 && (
              <div className="task-rail-empty">No other lists yet.</div>
            )}
            {counts.lists.filter((l) => l.id !== counts.my_day_list_id).map((l) => (
              <button
                key={l.id}
                type="button"
                className={`task-rail-row${view.listId === l.id ? ' is-on' : ''}`}
                aria-current={view.listId === l.id}
                onClick={() => setViewKey({ bucket: 'all', listId: l.id })}
              >
                <Icon name={l.external_id ? 'list' : 'alert'} size={15} />
                <span className="task-rail-label">{l.name}</span>
                <span className="task-rail-count">{l.open}</span>
              </button>
            ))}
          </nav>

          <section className="task-pane">
            <div className="card card-pad">
              <div className="card-title">
                {active.label} · {loaded ? tasks.length : '—'}
              </div>
              {active.blurb && <div className="task-pane-blurb">{active.blurb}</div>}
              {view.bucket === 'my_day' && !view.listId && (
                <div className="task-pane-blurb">
                  This is your Microsoft To Do list called <strong>My Day</strong> &mdash; the
                  same one on your phone, under Lists. Press the sun to move a task in or out.
                  It is <em>not</em> To Do&rsquo;s own My Day at the top of its sidebar: that
                  one is not in the API, so nothing added there can be seen from here.
                </div>
              )}

              {adding && (
                <Composer
                  lists={counts.lists}
                  presetList={counts.lists.find((l) => l.id === view.listId)?.name}
                  onAdded={load}
                  onCancel={() => setAdding(false)}
                />
              )}

              {!loaded && <SkeletonRows rows={5} controls={3} />}

              {loaded && tasks.length === 0 && view.bucket === 'my_day' && !view.listId && (
                <div className="empty-state empty-state--do" style={{ padding: 18 }}>
                  <Icon name="sun" size={20} />
                  <div>
                    <div>
                      {counts.my_day_list_id == null
                        ? 'No My Day list yet.'
                        : 'Nothing in My Day yet.'}
                    </div>
                    <div className="empty-note">
                      {counts.my_day_list_id == null
                        ? 'Make a list called My Day — here or in Microsoft To Do — and it '
                          + 'becomes this page. The sun on any task makes it for you.'
                        : 'Put something here with the sun, or add it to the My Day list in '
                          + 'To Do on your phone. Nothing fills it on its own; that is what '
                          + 'makes it a choice.'}
                    </div>
                    <div className="empty-actions">
                      {counts.buckets?.missed > 0 && (
                        <button
                          type="button"
                          className="btn btn--small"
                          onClick={() => setViewKey({ bucket: 'missed', listId: null })}
                        >
                          Start with the {counts.buckets.missed} overdue
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => setViewKey({ bucket: 'all', listId: null })}
                      >
                        Pick from all {counts.buckets?.all ?? 0}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {loaded && tasks.length === 0 && !(view.bucket === 'my_day' && !view.listId) && (
                <div className="empty-state" style={{ padding: 18 }}>
                  <Icon name="check" size={20} />
                  {view.bucket === 'missed'
                    ? 'Nothing overdue.'
                    : 'Nothing here. Add one above, or ask PSOK to.'}
                </div>
              )}

              {tasks.map((task) => {
                const done = task.status === 'done'
                const late = isOverdue(task)
                const listName = counts.lists.find((l) => l.id === task.list_id)?.name
                const inMyDay = counts.my_day_list_id != null
                  && task.list_id === counts.my_day_list_id
                return (
                  <div
                    className={`server-row task-row${done ? ' task-row--done' : ''}${late ? ' task-row--late' : ''}`}
                    key={task.id}
                  >
                    <button
                      type="button"
                      className={`task-check${done ? ' task-check--on' : ''}`}
                      disabled={busyTask === task.id}
                      aria-label={done ? `Mark ${task.title} not done` : `Mark ${task.title} done`}
                      aria-pressed={done}
                      onClick={() => patch(task, { status: done ? 'todo' : 'done' })}
                    >
                      {done && <Icon name="check" size={12} />}
                    </button>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <div className="server-name task-title">{task.title}</div>
                      {/* Only the overdue fact is amber. Colouring the whole
                          line turns a list of five late tasks into a wall of
                          warning, which says less than one marked word does. */}
                      <div className="server-target">
                        {listName && <span>{listName}</span>}
                        {task.due_at && (
                          <span className={late ? 'task-late-flag' : undefined}>
                            {late ? 'was due' : 'due'} {when(task.due_at)}
                          </span>
                        )}
                        {task.scheduled_at && <span>scheduled {when(task.scheduled_at)}</span>}
                        {reminder(task) && <span>{reminder(task)}</span>}
                        {inMyDay && <span>my day</span>}
                      </div>
                      {task.notes && <div className="server-target">{task.notes}</div>}
                    </div>

                    {/* Missed rows carry their answer. Rescheduling by hand is
                        the step people skip, which is how a list of overdue
                        tasks becomes a list nobody opens. */}
                    {late && (
                      <div className="task-actions">
                        <button
                          type="button"
                          className="btn btn--ghost btn--small"
                          disabled={busyTask === task.id}
                          onClick={() => patch(task, { due_date_hint: 'tomorrow' }, 'Due tomorrow')}
                        >
                          Tomorrow
                        </button>
                      </div>
                    )}

                    {/* The sun moves the task between its list and My Day,
                        because that is what My Day is. To Do has no move, so the
                        server recreates the task there and deletes the original
                        -- the toast says "moved", not "tagged", since the task
                        really does leave the list it was in. */}
                    <button
                      type="button"
                      className={`icon-btn task-sun${inMyDay ? ' is-on' : ''}`}
                      disabled={busyTask === task.id}
                      title={inMyDay ? 'Move out of My Day' : 'Move into My Day'}
                      aria-pressed={inMyDay}
                      aria-label={`Move ${task.title} into My Day`}
                      onClick={() => patch(
                        task,
                        { add_to_my_day: !inMyDay },
                        inMyDay ? 'Moved out of My Day' : 'Moved into My Day',
                      )}
                    >
                      <Icon name="sun" size={14} />
                    </button>

                    <button
                      type="button"
                      className={`icon-btn task-star${task.important ? ' is-on' : ''}`}
                      disabled={busyTask === task.id}
                      title={task.important ? 'Not important' : 'Mark important'}
                      aria-pressed={Boolean(task.important)}
                      aria-label={`Mark ${task.title} important`}
                      onClick={() => patch(task, { important: !task.important })}
                    >
                      <Icon name="star" size={14} />
                    </button>
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

            <div className="card card-pad" style={{ marginTop: 18 }}>
              <div className="card-title">next three weeks · {loaded ? events.length : '—'}</div>
              {!loaded && <SkeletonRows rows={3} controls={0} />}
              {loaded && events.length === 0 && (
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

            <div style={{ marginTop: 18 }}>
              <button
                type="button"
                className="btn btn--small"
                onClick={() => { setView('chat'); chat.focusComposer?.() }}
              >
                <Icon name="chat" size={13} /> Ask PSOK to add one
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

const LOCAL_ONLY = 'This list is only on this machine — it has not reached Microsoft To Do yet.'
