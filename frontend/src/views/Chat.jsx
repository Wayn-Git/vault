import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import Markdown from '../components/markdown/Markdown.jsx'
import ToolCallCard from '../components/ToolCallCard.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'
import PlusMenu from '../components/PlusMenu.jsx'
import ModelMenu from '../components/ModelMenu.jsx'
import { useApp } from '../store.jsx'
import { api, copyText } from '../api.js'
import { MOD_LABEL } from '../keys.js'

/* The composer is the interface. Everything else — which skills are live, which
   connectors it may reach, what it remembers, where it may work — hangs off the
   + menu beside it or the palette above it, so the surface stays one field and
   a sentence. */

/* No provider is special. This used to name one, which made every other
   provider a second-class citizen of the composer's own defaulting. */

/* How long a turn may say nothing at all before this interface stops believing
   in it. Generous on purpose: a single tool call can take minutes and emit
   nothing while it does, and a watchdog that fires on slow work would be worse
   than the hang it replaces. It exists for the case the server can no longer
   report -- a loop wedged on a dead socket, which used to need a page reload. */
const SILENCE_LIMIT_MS = 180_000

// Kept identical to `planning.APPROVAL_MESSAGE` on the server, which is where
// the instruction it answers lives.
const PLAN_APPROVAL = 'Approved. Carry out the plan.'

// Step events belong to the plan being carried out, which is always the most
// recent one on screen -- an older card is a plan that was already finished or
// discarded, and moving its ticks would be a lie about what is running.
function markPlan(items, update) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (items[i].kind === 'plan') {
      const next = items.slice()
      next[i] = update(items[i])
      return next
    }
  }
  return items
}

const OPENERS = [
  'What am I meant to be doing tomorrow?',
  'Find where I wrote about the deploy error',
  'Summarise what changed in this folder today',
]

let idSeq = 0
const nextId = () => `item-${++idSeq}`

function buildRendered(items) {
  const out = []
  for (let i = 0; i < items.length; i++) {
    const it = items[i]
    if (it.kind !== 'assistant') { out.push(it); continue }
    const toolCalls = (it.callsRaw || []).map((c) => ({
      name: c.function?.name ?? c.name,
      arguments: c.function?.arguments ?? c.arguments,
      status: 'done',
    }))
    let j = i + 1
    while (j < items.length && items[j].kind === 'tool') {
      const t = items[j]
      const slot = toolCalls.find((c) => c.name === t.name && c.content === undefined)
      if (slot) {
        slot.content = t.content
        slot.status = t.isError ? 'error' : 'done'
      } else {
        toolCalls.push({ name: t.name, arguments: t.arguments, content: t.content, status: t.isError ? 'error' : 'done' })
      }
      j++
    }
    out.push({ ...it, toolCalls })
    i = j - 1
  }
  return out
}

function historyToItems(rows) {
  return rows.map((m) => {
    // `rowId` is the database id, which is what a pin is written against.
    // Streamed items have none until the transcript is read back, which is why
    // pinning is offered on stored messages and not on one still arriving.
    if (m.role === 'user') {
      return { id: nextId(), rowId: m.id, kind: 'user', text: m.content, pinned: Boolean(m.pinned) }
    }
    if (m.role === 'assistant') {
      return {
        id: nextId(),
        rowId: m.id,
        kind: 'assistant',
        text: m.content ?? '',
        pinned: Boolean(m.pinned),
        callsRaw: Array.isArray(m.tool_calls) ? m.tool_calls : [],
      }
    }
    if (m.role === 'tool') {
      return {
        id: nextId(),
        kind: 'tool',
        name: m.tool_name ?? 'tool',
        arguments: {},
        content: m.content ?? '',
        isError: Boolean(m.is_error),
      }
    }
    return null
  }).filter(Boolean)
}

function CopyButton({ text, label = 'Copy' }) {
  const [done, setDone] = useState(false)
  if (!text) return null
  return (
    <button
      type="button"
      className="msg-copy"
      title={label}
      aria-label={label}
      onClick={async () => {
        setDone(await copyText(text) ? 'ok' : 'no')
        setTimeout(() => setDone(false), 1500)
      }}
    >
      <Icon name={done === 'ok' ? 'check' : done === 'no' ? 'x' : 'copy'} size={13} />
    </button>
  )
}

/* The chain of thought is not the answer, and rendering it as one would be a
   lie about what the model committed to.

   It streams in its own panel while it is happening, because watching it arrive
   is the whole value of having it -- a collapsed block that says "thinking" for
   forty seconds tells you nothing about whether the model is on the right track
   -- and it folds itself away the moment the answer starts, where it stays one
   click from being read again. Opening or closing it by hand wins from then on:
   someone reading the thinking does not want it shutting on them. */
function Reasoning({ text, live, ms }) {
  const [manual, setManual] = useState(null)
  const bodyRef = useRef(null)
  const open = manual === null ? Boolean(live) : manual

  useEffect(() => {
    const el = bodyRef.current
    if (live && el) el.scrollTop = el.scrollHeight
  }, [text, live, open])

  if (!text) return null

  const label = live
    ? 'Thinking'
    : ms
      ? `Thought for ${Math.max(1, Math.round(ms / 1000))}s`
      : 'Thought for a moment'

  return (
    <div className={`reasoning${open ? ' open' : ''}${live ? ' live' : ''}`}>
      <button
        type="button"
        className="reasoning-head"
        onClick={() => setManual(!open)}
        aria-expanded={open}
      >
        <Icon name="chevron" size={11} className="reasoning-caret" />
        <span>{label}</span>
      </button>
      {open && (
        <div className={`reasoning-body${live ? ' is-live' : ''}`} ref={bodyRef}>{text}</div>
      )}
    </div>
  )
}

function PinButton({ item, onPin }) {
  if (!item.rowId) return null
  return (
    <button
      type="button"
      className={`msg-pin${item.pinned ? ' is-pinned' : ''}`}
      title={item.pinned ? 'Unpin' : 'Pin this message'}
      aria-label={item.pinned ? `Unpin ${item.kind} message` : `Pin ${item.kind} message`}
      aria-pressed={item.pinned}
      onClick={() => onPin(item, !item.pinned)}
    >
      <Icon name="pin" size={13} weight={item.pinned ? 'fill' : 'regular'} />
    </button>
  )
}

/* What each named state is called on screen. The set is closed on the server
   (`director.STATUSES`), so a label missing here means a state was added
   without deciding what to call it -- which is why the fallback is the raw
   name rather than a shrug. */
const STATUS_LABELS = {
  retrieving: 'Searching your notes',
  recalling: 'Recalling',
  thinking: 'Thinking',
  planning: 'Planning',
  generating: 'Writing',
  tool: 'Running',
  connector: 'Using',
  retrying: 'Continuing',
  switching: 'Switching provider',
  completed: 'Finishing',
  cancelled: 'Stopping',
  failed: 'Failed',
}

function statusLabel(status) {
  if (!status) return 'Thinking'
  const base = STATUS_LABELS[status.state] || status.state
  if (status.state === 'connector' && status.server) return `${base} ${status.server}`
  if (status.state === 'tool' && status.tool) return `${base} ${status.tool}`
  return base
}

function formatDuration(ms) {
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total}s`
  return `${Math.floor(total / 60)}m ${String(total % 60).padStart(2, '0')}s`
}

/* The plan, as steps you can act on.

   Plan mode used to prepend a sentence to the message and hope. The steps now
   arrive as a `plan` frame from a `submit_plan` tool call, and nothing that
   changes anything was even offered to the model during the turn that produced
   them -- the registry withheld it. So Approve is the first moment any of this
   could touch the machine. */
/* Where the executing turn has got to. `running` is the step the model said it
   was starting; `done` are the ones it said it finished. Both come from
   `begin_step` calls, never from guessing which tool belongs to which step. */
function stepClass(item, index) {
  const n = index + 1
  if (item.doneSteps?.includes(n)) return 'plan-step--done'
  if (item.runningStep === n) return 'plan-step--running'
  return ''
}

/* The three modes, in the order they cost. `reasoning` is the one the fast
   model asks for on your behalf when it escalates; picking it up front is the
   same request without the question. */
const MODES = [
  { id: 'chat', label: 'Chat', hint: 'Answer and act in one turn' },
  { id: 'plan', label: 'Plan', hint: 'Ask for the plan before anything is run' },
  { id: 'reasoning', label: 'Reasoning', hint: 'Start on the stronger, slower model' },
]

function PlanCard({ item, onApprove, onDiscard, onEditStep, disabled }) {
  return (
    <div className="plan-card">
      <div className="plan-head">
        <Icon name="check" size={14} />
        <span>Plan</span>
        <span className="plan-count">{item.steps.length} steps</span>
      </div>
      {item.summary && <p className="plan-summary">{item.summary}</p>}
      <ol className="plan-steps">
        {item.steps.map((step, i) => (
          <li key={`${item.id}-${i}`} className={stepClass(item, i)}>
            {/* Editable in place. The spec asked for approve, edit or discard,
                and an edited plan travels with the approval -- the model's
                original is already in the transcript, so approving without
                sending the edit would approve the wrong thing. */}
            {item.settled ? (
              <span className="plan-step-title">{step.title}</span>
            ) : (
              <input
                className="plan-step-input"
                value={step.title}
                aria-label={`Step ${i + 1}`}
                onChange={(e) => onEditStep?.(item.id, i, e.target.value)}
              />
            )}
            {step.detail && <span className="plan-step-detail">{step.detail}</span>}
            {step.tools?.length > 0 && (
              <span className="plan-step-tools">{step.tools.join(' · ')}</span>
            )}
          </li>
        ))}
      </ol>
      {item.settled ? (
        <p className="plan-settled">{item.settled === 'approved' ? 'Approved.' : 'Discarded.'}</p>
      ) : (
        <div className="plan-actions">
          <button type="button" className="btn btn--primary btn--small" disabled={disabled} onClick={onApprove}>
            Approve and run
          </button>
          <button type="button" className="btn btn--ghost btn--small" disabled={disabled} onClick={onDiscard}>
            Discard
          </button>
          <span className="plan-hint">Nothing has run yet. Edit the request and plan again to change it.</span>
        </div>
      )}
    </div>
  )
}

/* The fast model asking for the slow one.

   Rendered like a plan card because it is the same kind of moment: the turn has
   ended, nothing has run, and the user decides what happens next. The model it
   would move to is named rather than described as "a bigger one" -- the wait is
   the cost being agreed to, and it is measured in minutes on this machine. */
function EscalationCard({ item, onEscalate, onAnyway, disabled }) {
  return (
    <div className="plan-card escalation-card">
      <div className="plan-head">
        <Icon name="spark" size={14} />
        <span>Needs a stronger model</span>
      </div>
      <p className="plan-summary">{item.reason}</p>
      <p className="plan-step-detail">
        {item.from_model} → <strong>{item.to_model}</strong>
      </p>
      {item.settled ? (
        <p className="plan-settled">
          {item.settled === 'escalated' ? 'Escalated.' : 'Answered on the faster model.'}
        </p>
      ) : (
        <div className="plan-actions">
          <button type="button" className="btn btn--primary btn--small" disabled={disabled} onClick={onEscalate}>
            Escalate
          </button>
          <button type="button" className="btn btn--ghost btn--small" disabled={disabled} onClick={onAnyway}>
            Answer anyway
          </button>
          <span className="plan-hint">Nothing has run. The stronger model is slower.</span>
        </div>
      )}
    </div>
  )
}

function Msg({
  item, onPin, onApprovePlan, onDiscardPlan, onEditPlanStep, onEscalate, onAnyway, busy,
}) {
  const role = item.kind

  if (role === 'escalation') {
    return (
      <EscalationCard
        item={item}
        disabled={busy}
        onEscalate={() => onEscalate?.(item.id)}
        onAnyway={() => onAnyway?.(item.id)}
      />
    )
  }
  if (role === 'plan') {
    return (
      <PlanCard
        item={item}
        disabled={busy}
        onApprove={() => onApprovePlan?.(item.id)}
        onDiscard={() => onDiscardPlan?.(item.id)}
        onEditStep={onEditPlanStep}
      />
    )
  }
  if (role === 'cost') {
    return (
      <div className="msg-cost">
        {item.steps} step{item.steps === 1 ? '' : 's'} · {item.tools} tool{item.tools === 1 ? '' : 's'} · {formatDuration(item.durationMs)}
      </div>
    )
  }

  if (role === 'note') {
    const cls = item.tone === 'guard'
      ? 'msg-note--guard'
      : item.tone === 'error' ? 'msg-note--error' : 'msg-note--warning'
    return (
      <div className={`msg-note ${cls}`}>
        <Icon name={item.tone === 'error' ? 'x' : 'info'} size={14} />
        <span>{item.text}</span>
      </div>
    )
  }
  if (role === 'memory') {
    return (
      <div className="msg-note msg-note--warning">
        <Icon name="spark" size={14} />
        <span><strong style={{ fontWeight: 500 }}>remembered</strong> — {item.text}</span>
      </div>
    )
  }
  if (role === 'reasoning') return <Reasoning text={item.text} ms={item.ms} />
  if (role === 'tool') {
    return (
      <ToolCallCard
        call={{
          name: item.name,
          arguments: item.arguments ?? {},
          content: item.content,
          status: item.isError ? 'error' : 'done',
        }}
        running={false}
      />
    )
  }
  if (role === 'assistant') {
    // A turn that only called tools has nothing to say yet, and labelling each
    // of those as a reply from PSOK turns three steps of one answer into three
    // answers.
    if (!item.text && item.toolCalls?.length) {
      return <>{item.toolCalls.map((c, i) => <ToolCallCard key={i} call={c} running={false} />)}</>
    }
    return (
      <div className={`msg msg-assistant${item.pinned ? ' is-pinned' : ''}`}>
        <div className="msg-role">
          psok
          <CopyButton text={item.text} label="Copy this answer" />
          <PinButton item={item} onPin={onPin} />
        </div>
        {item.text && <div className="msg-body"><Markdown text={item.text} /></div>}
        {item.toolCalls?.map((c, i) => <ToolCallCard key={i} call={c} running={false} />)}
      </div>
    )
  }
  return (
    <div className={`msg msg-user${item.pinned ? ' is-pinned' : ''}`}>
      <div className="msg-role">
        you
        <CopyButton text={item.text} label="Copy" />
        <PinButton item={item} onPin={onPin} />
      </div>
      <div className="msg-body msg-body--plain">{item.text}</div>
    </div>
  )
}

export default function Chat() {
  const {
    health, refreshHealth, setView, toast, registerChat,
    conversations, refreshConvs, activeId, setActiveId, setRenaming,
    refreshCaps, setCapabilitiesTab,
    workspace, setWorkspace, notify,
  } = useApp()

  const [items, setItems] = useState([])
  const [turnState, setTurnState] = useState('idle')
  const [stopping, setStopping] = useState(false)
  const [liveTool, setLiveTool] = useState(null)
  const [liveStatus, setLiveStatus] = useState(null)
  const [liveBuffer, setLiveBuffer] = useState('')
  const [liveReasoning, setLiveReasoning] = useState('')
  const [pending, setPending] = useState([])
  const [elsewhere, setElsewhere] = useState([])
  const [input, setInput] = useState('')
  const [plusOpen, setPlusOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [draft, setDraft] = useState({ provider: '', model: '' })
  const [acItems, setAcItems] = useState([])
  const [acIndex, setAcIndex] = useState(0)
  const [attachments, setAttachments] = useState([])
  // Plan mode is a real instruction, not a mode flag: it is prepended to the
  // message so the model outlines the work before touching anything.
  /* Three modes now, so a boolean stopped being enough. `chat` answers and
     acts, `plan` hands back an approvable plan with mutating tools withheld,
     and `reasoning` starts on the heavy tier -- the model the fast one asks for
     when it escalates. */
  const [mode, setMode] = useState('chat')
  const [atBottom, setAtBottom] = useState(true)
  const [lastSent, setLastSent] = useState('')
  const [pinsOpen, setPinsOpen] = useState(true)
  /* Health banners the user has waved away. Keyed by a signature of what the
     banner says, not just "hidden": a connector that starts failing for a new
     reason, or a different connector going down, is a new fact worth showing
     again. Persisted so a reload does not resurrect one the user already
     dismissed for a condition that has not changed. */
  const [dismissedBanners, setDismissedBanners] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem('psok.dismissed.v1') || '[]')) }
    catch { return new Set() }
  })
  const dismissBanner = useCallback((sig) => {
    setDismissedBanners((prev) => {
      const next = new Set(prev)
      next.add(sig)
      try { localStorage.setItem('psok.dismissed.v1', JSON.stringify([...next])) } catch { /* private mode */ }
      return next
    })
  }, [])

  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  const fileRef = useRef(null)
  const acTimerRef = useRef(null)
  const liveRef = useRef({ buffer: '', reasoning: '', reasoningStart: 0, tool: null, status: null })
  // One counter per turn. The stream outlives the answer -- memory extraction
  // runs after `done` -- so a turn that has already been superseded must not be
  // allowed to reset the composer when its stream finally closes.
  const turnTokenRef = useRef(0)
  const runningRef = useRef(null)
  const settledRef = useRef(true)

  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}
  const active = conversations.find((c) => c.id === activeId)

  // What to use when nothing has been chosen: the house default if this machine
  // has it configured, otherwise whatever it does have.
  const fallbackProvider = providers[0]
  const draftProvider = draft.provider || fallbackProvider || ''
  const draftModel =
    draft.model || defaults[draftProvider] || ''

  const setBuffer = useCallback((t) => { liveRef.current.buffer = t; setLiveBuffer(t) }, [])
  const setTool = useCallback((t) => { liveRef.current.tool = t; setLiveTool(t) }, [])
  const setStatus = useCallback((next) => { liveRef.current.status = next; setLiveStatus(next) }, [])
  const setReasoning = useCallback((t) => { liveRef.current.reasoning = t; setLiveReasoning(t) }, [])

  const loadMessages = useCallback(async (cid) => {
    if (!cid) { setItems([]); return }
    try {
      setItems(historyToItems(await api.messages(cid)))
    } catch (err) {
      toast(err.message, 'bad')
      setItems([])
    }
  }, [toast])

  // A reload lands here with a conversation id from the last session, so the
  // transcript has to be fetched before anything is typed.
  //
  // Never underneath a running turn, though. Sending the first message of a new
  // conversation sets the id, which fires this, which used to race the stream
  // and replace the message that had just been typed with whatever the database
  // had a moment ago -- the "sometimes the prompt does nothing" case.
  useEffect(() => {
    if (runningRef.current) return
    loadMessages(activeId)
  }, [activeId, loadMessages])

  const selectConversation = useCallback((cid) => {
    if (turnState !== 'idle') { toast('Finish or stop this turn first', 'amber'); return }
    setActiveId(cid)
  }, [turnState, setActiveId, toast])

  const startFresh = useCallback(() => {
    if (turnState !== 'idle') { toast('Finish or stop this turn first', 'amber'); return }
    setActiveId(null)
    setItems([])
    setInput('')
    setTimeout(() => textareaRef.current?.focus(), 0)
  }, [turnState, setActiveId, toast])

  const pushAssistant = useCallback(() => {
    const { buffer, reasoning, reasoningStart } = liveRef.current
    if (reasoning) {
      const ms = reasoningStart ? Date.now() - reasoningStart : 0
      setItems((prev) => [...prev, { id: nextId(), kind: 'reasoning', text: reasoning, ms }])
      setReasoning('')
      liveRef.current.reasoningStart = 0
    }
    if (buffer) {
      setItems((prev) => [...prev, { id: nextId(), kind: 'assistant', text: buffer, callsRaw: [] }])
      setBuffer('')
    }
  }, [setBuffer, setReasoning])

  const pushNote = useCallback((tone, text) => {
    pushAssistant()
    setItems((prev) => [...prev, { id: nextId(), kind: 'note', tone, text: text ?? '' }])
  }, [pushAssistant])

  /* The stream is closed. Everything it said is already on screen.

     This deliberately does not refetch the transcript. It used to, and the
     refetch is what made every finished turn flicker and then lose its own
     thinking: reasoning, warnings and the memory note are stream-only events
     that were never written to the database, so replacing the local transcript
     with the stored one silently deleted them a second after they appeared. */
  const finish = useCallback(() => {
    settledRef.current = true
    pushAssistant()
    setTurnState('idle')
    setStopping(false)
    setTool(null)
    // `settle` clears this and `done` always goes through `settle` -- but a
    // stream that closes with no terminal frame lands here instead, and used
    // to leave the last status ("Running view_file") behind a finished turn.
    setStatus(null)
    setPending([])
    setElsewhere([])
    refreshConvs()
    // A turn is when connectors reconcile, so the tool count and any connector
    // failure only become knowable once one has run.
    refreshHealth()
    refreshCaps()
  }, [pushAssistant, refreshConvs, refreshHealth, refreshCaps, setTool, setStatus])

  /* `done`, `guard` and `error` end the turn as far as anyone typing is
     concerned, even though the stream stays open behind them: memory extraction
     is a second model call that runs after `done`. Waiting for the stream to
     close before releasing the composer is what put a second "thinking" line
     under a finished answer and left the field disabled for seconds after the
     reply had arrived. */
  const settle = useCallback(() => {
    settledRef.current = true
    pushAssistant()
    setTool(null)
    setStatus(null)
    setTurnState('idle')
    setStopping(false)
    refreshConvs()
  }, [pushAssistant, setTool, setStatus, refreshConvs])

  /* One desktop notification for a finished turn, titled by the conversation it
     belongs to. The store decides whether to actually show it (opted in,
     permission granted, tab in the background) -- here we only say what it says
     and what clicking it does: come back to this conversation. */
  const notifyDone = useCallback((title, body) => {
    const cid = runningRef.current
    const conv = conversations.find((c) => c.id === cid)
    const heading = conv?.title ? `${title} — ${conv.title}` : title
    notify(heading, body || '', () => { if (cid) selectConversation(cid) })
  }, [notify, conversations, selectConversation])

  const onEvent = useCallback((evt) => {
    switch (evt.type) {
      case 'assistant_delta':
        liveRef.current.buffer += evt.text ?? ''
        setBuffer(liveRef.current.buffer)
        break
      case 'reasoning_delta':
        if (!liveRef.current.reasoningStart) liveRef.current.reasoningStart = Date.now()
        liveRef.current.reasoning += evt.text ?? ''
        setReasoning(liveRef.current.reasoning)
        break
      case 'assistant_text':
        setBuffer(evt.text ?? '')
        break
      case 'tool_call':
        pushAssistant()
        setTool({ name: evt.name, arguments: evt.arguments ?? {}, status: 'running' })
        break
      case 'tool_result': {
        const t = liveRef.current.tool
        setItems((prev) => [...prev, {
          id: nextId(),
          kind: 'tool',
          name: t?.name ?? evt.name,
          arguments: t?.arguments ?? {},
          content: evt.content ?? '',
          isError: Boolean(evt.is_error),
        }])
        setTool(null)
        break
      }
      case 'confirmation_required':
        // The turn is suspended until this is answered. The frame carries the
        // request id, which polling cannot supply unambiguously when two calls
        // to the same tool are pending.
        setPending((p) => (p.some((x) => x.id === evt.request_id) ? p : [...p, {
          id: evt.request_id,
          tool_name: evt.tool_name,
          operation_key: evt.operation_key,
          risk: evt.risk,
          reason: evt.reason,
          arguments: evt.arguments ?? {},
        }]))
        break
      case 'memory': {
        const created = evt.created ?? []
        const superseded = evt.superseded ?? []
        const parts = []
        if (created.length) parts.push(created.join(' · '))
        if (superseded.length) parts.push(`${superseded.length} retired`)
        setItems((prev) => [...prev, { id: nextId(), kind: 'memory', text: parts.join(' — ') }])
        break
      }
      // The plan itself, as data. Rendered as steps with Approve and Discard
      // rather than as prose, which is the whole reason it is a tool call.
      case 'plan':
        pushAssistant()
        setItems((prev) => [...prev, {
          id: nextId(),
          kind: 'plan',
          summary: evt.summary ?? '',
          steps: evt.steps ?? [],
          settled: false,
        }])
        break
      // What the turn is doing right now. Every one of these already happened
      // inside the loop and none of it was visible: the composer said
      // "Thinking" from the moment a turn opened until the first token, whether
      // the wait was retrieval, a cold connector or a provider retry.
      // The fast model handing the job over. The message that caused it travels
      // with the card: approving re-sends it in reasoning mode, and declining
      // re-sends it in chat, where the backend withholds the tool because the
      // transcript already records the request.
      case 'escalation':
        pushAssistant()
        setItems((prev) => {
          const asked = [...prev].reverse().find((it) => it.kind === 'user')
          return [...prev, {
            id: nextId(),
            kind: 'escalation',
            reason: evt.reason ?? '',
            from_model: evt.from_model ?? '',
            to_model: evt.to_model ?? '',
            message: asked?.text ?? '',
            settled: false,
          }]
        })
        break
      case 'status':
        setStatus(evt.state ? { state: evt.state, tool: evt.tool, server: evt.server } : null)
        break
      // Progress through an approved plan, as the model reported it. Applied to
      // the last plan card, which is the one that was approved.
      case 'step_started':
        setItems((prev) => markPlan(prev, (plan) => ({ ...plan, runningStep: evt.number })))
        break
      case 'step_done':
        setItems((prev) => markPlan(prev, (plan) => ({
          ...plan,
          runningStep: plan.runningStep === evt.number ? null : plan.runningStep,
          doneSteps: [...(plan.doneSteps ?? []), evt.number],
        })))
        break
      case 'done':
        // `execution_logs.duration_ms` has held this since logging shipped and
        // nothing ever read it. Asked immediately or not at all.
        if (evt.duration_ms != null) {
          setItems((prev) => [...prev, {
            id: nextId(),
            kind: 'cost',
            steps: evt.steps ?? evt.iterations ?? 0,
            tools: evt.tools ?? 0,
            durationMs: evt.duration_ms,
          }])
        }
        notifyDone('Reply ready', evt.text)
        settle()
        break
      case 'guard': pushNote('guard', evt.reason); notifyDone('Turn stopped', evt.reason); settle(); break
      case 'error': pushNote('error', evt.message); notifyDone('Turn failed', evt.message); settle(); break
      // Not terminal: the loop is continuing a turn that came back empty or
      // truncated, and the composer stays disabled while it does.
      case 'warning': pushNote('warning', evt.message); break
      // A keepalive during a long tool call. Nothing to render -- its whole job
      // is done by having arrived: the `beat()` wrapping onEvent has already
      // reset the silence watchdog, and the byte kept the socket alive.
      case 'ping': break
      default:
        /* A frame added on the server used to vanish here without trace, which
           is how you spend an afternoon wondering why the backend's new event
           "does not arrive". It arrives. */
        console.warn('[psok] unhandled turn frame', evt.type, evt) // eslint-disable-line no-console
        break
    }
  }, [pushAssistant, pushNote, settle, setBuffer, setReasoning, setTool, setStatus, notifyDone])

  const openTurn = useCallback(async (cid, message, mode = 'chat') => {
    const token = ++turnTokenRef.current
    runningRef.current = cid
    settledRef.current = false
    setItems((prev) => [...prev, { id: nextId(), kind: 'user', text: message }])
    setTurnState('running')
    setAtBottom(true)
    const controller = new AbortController()
    abortRef.current = controller

    /* A wedged stream used to be unrecoverable without reloading the page.
       `reader.read()` has no timeout, so a server-side loop stuck on a dead
       socket left turnState 'running' forever: the composer disabled,
       conversation switching refused, and Stop disabled too once pressed.

       The watchdog is deliberately generous and reset by *every* frame, not
       just text -- a tool call can legitimately take minutes and say nothing
       while it does. It fires only when the connection has gone quiet
       entirely, which is the one case the server can no longer report. */
    let watchdog = null
    const beat = () => {
      clearTimeout(watchdog)
      watchdog = setTimeout(() => {
        if (turnTokenRef.current !== token || settledRef.current) return
        pushNote('error', `No response from the server for ${SILENCE_LIMIT_MS / 1000}s. The turn may still be running; reload to reconnect.`)
        settledRef.current = true
        setTurnState('idle')
        setStopping(false)
        controller.abort()
      }, SILENCE_LIMIT_MS)
    }
    beat()

    try {
      await api.turn({
        conversationId: cid,
        message,
        workspace: workspace.trim() || null,
        mode,
        onEvent: (evt) => { beat(); onEvent(evt) },
        signal: controller.signal,
      })
    } catch (err) {
      // An abort after the answer landed is this interface letting go of a
      // stream it no longer needs, not a turn someone interrupted.
      if (err.name === 'AbortError') { if (!settledRef.current) pushNote('warning', 'Stopped.') }
      else pushNote('error', err.message)
    } finally {
      clearTimeout(watchdog)
      if (turnTokenRef.current === token) {
        /* A clean close with no terminal frame used to push nothing at all:
           the composer re-enabled, the thinking indicator vanished, and if
           nothing had streamed the turn simply evaporated. Silence is not an
           answer, so say so. */
        if (!settledRef.current) {
          pushNote('error', 'The turn ended without a result. Nothing was returned.')
        }
        runningRef.current = null
        finish()
      }
    }
  }, [workspace, onEvent, finish, pushNote])

  // A browser cannot hand the agent a path, so the file is uploaded and the
  // message carries where it landed -- which the ordinary file tools can read.
  const uploadFiles = useCallback(async (files) => {
    for (const file of files) {
      try {
        const stored = await api.upload(file)
        setAttachments((list) => [...list, stored])
      } catch (err) {
        toast(`${file.name}: ${err.message}`, 'bad')
      }
    }
  }, [toast])

  /* Approve runs the plan as an ordinary chat turn.

     The plan is already in the transcript -- the director persisted it as the
     assistant's own words -- so the executing turn reads it as history rather
     than being handed it again. That is also why approving is a normal turn and
     not a special endpoint: there is nothing special about it except that the
     model has already agreed what it is going to do. */
  const approvePlan = useCallback(async (itemId) => {
    if (turnState !== 'idle' || !activeId) return
    let message = PLAN_APPROVAL
    setItems((prev) => prev.map((it) => {
      if (it.id !== itemId) return it
      if (it.edited) {
        // An edited plan travels with the approval. The model's original is
        // already in the transcript, so approving without sending the edit
        // would approve the plan the user just changed.
        const steps = it.steps.map((st, i) => `${i + 1}. ${st.title}`).join('\n')
        message = `Approved, with this as the plan. Carry it out, and call \`begin_step\` before each step.\n\n${steps}`
      }
      return { ...it, settled: 'approved' }
    }))
    try {
      abortRef.current?.abort()
      await openTurn(activeId, message, 'chat')
    } catch (err) {
      toast(err.message, 'bad')
      setTurnState('idle')
    }
  }, [turnState, activeId, openTurn, toast])

  const editPlanStep = useCallback((itemId, index, title) => {
    setItems((prev) => prev.map((it) => (
      it.id === itemId
        ? { ...it, steps: it.steps.map((st, i) => (i === index ? { ...st, title } : st)), edited: true }
        : it
    )))
  }, [])

  /* Both buttons re-send the same message; only the mode differs. There is no
     resume endpoint and there should not be one -- the turn ended, nothing ran,
     and a second turn is exactly what this is. "Answer anyway" needs no flag:
     the backend withholds the tool when the last assistant message is the
     escalation record, which survives a reload where a flag here would not. */
  const answerEscalation = useCallback(async (itemId, mode) => {
    if (turnState !== 'idle' || !activeId) return
    let message = ''
    setItems((prev) => prev.map((it) => {
      if (it.id !== itemId) return it
      message = it.message
      return { ...it, settled: mode === 'reasoning' ? 'escalated' : 'declined' }
    }))
    if (!message) return
    try {
      abortRef.current?.abort()
      await openTurn(activeId, message, mode)
    } catch (err) {
      toast(err.message, 'bad')
      setTurnState('idle')
    }
  }, [turnState, activeId, openTurn, toast])

  const escalate = useCallback((itemId) => answerEscalation(itemId, 'reasoning'), [answerEscalation])
  const answerAnyway = useCallback((itemId) => answerEscalation(itemId, 'chat'), [answerEscalation])

  const discardPlan = useCallback((itemId) => {
    // Local only. Nothing ran, so there is nothing to undo on the server, and
    // the plan stays in the transcript because the model said it.
    setItems((prev) => prev.map((it) => (it.id === itemId ? { ...it, settled: 'discarded' } : it)))
  }, [])

  const send = useCallback(async () => {
    const typed = input.trim()
    if ((!typed && attachments.length === 0) || turnState !== 'idle') return
    const attached = attachments.length
      ? `\n\nAttached files (read them with view_file):\n${attachments.map((f) => `- ${f.path}`).join('\n')}`
      : ''
    /* No prefix any more. It used to prepend "Plan first: ..." to the user's
       own message, which meant the instruction was persisted into the
       transcript and replayed on every later iteration and every later turn --
       and nothing enforced it, because the backend had no idea plan mode
       existed. It is a field on the request now, and the tool schemas are
       withheld by the registry. */
    const message = `${typed}${attached}`
    if (!message.trim()) return
    setInput('')
    setAttachments([])
    setLastSent(typed)
    setAcItems([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    let cid = activeId
    try {
      if (!cid) {
        if (!draftProvider) { toast('No provider is configured in providers.yaml', 'bad'); return }
        /* Never invent a model name. Sending 'default' as a placeholder for
           "health has not answered yet" put that literal string on the wire:
           NVIDIA replied 404, and every turn in that conversation failed
           forever with no way to correct it from here. The server fills in the
           provider's declared default when the field is empty, and refuses
           when there is none -- which is a rejected send, not a dead
           conversation. */
        const { id } = await api.createConversation(
          draftProvider,
          draftModel || '',
          (typed || attachments[0]?.name || 'untitled').slice(0, 56),
        )
        cid = id
        setActiveId(id)
        refreshConvs()
      }
      // A finished turn's stream can still be open on the memory frame it emits
      // after `done`. Let go of it before opening the next one on the same
      // conversation, so two readers are never live at once.
      abortRef.current?.abort()
      await openTurn(cid, message, mode)
    } catch (err) {
      toast(err.message, 'bad')
      setTurnState('idle')
    }
  }, [
    input, attachments, mode, turnState, activeId, draftProvider, draftModel,
    refreshConvs, openTurn, toast, setActiveId,
  ])

  const stop = useCallback(async () => {
    if (!activeId) { abortRef.current?.abort(); return }
    setStopping(true)
    try {
      // The server stops the loop; the stream then ends with a guard frame of
      // its own accord. Aborting the read here would leave it running.
      await api.stopTurn(activeId)
    } catch (err) {
      toast(err.message, 'bad')
      abortRef.current?.abort()
    }
  }, [activeId, toast])

  const applyModel = useCallback(async (patch) => {
    if (!activeId) { setDraft((d) => ({ ...d, ...patch })); return }
    try {
      await api.updateConversation(activeId, patch)
      await refreshConvs()
    } catch (err) {
      toast(err.message, 'bad')
      refreshConvs()
    }
  }, [activeId, refreshConvs, toast])

  const toggleMemory = useCallback(async () => {
    try {
      const current = await api.memory(activeId || null)
      const next = await api.toggleMemory(!current.enabled, activeId || null)
      toast(next.enabled ? 'Memory on — facts are recalled each turn' : 'Memory off', next.enabled ? 'ok' : 'info')
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [activeId, toast])

  const focusComposer = useCallback((seed) => {
    const el = textareaRef.current
    if (!el) return
    el.focus()
    if (seed) setInput((v) => (v.endsWith(seed) ? v : v + seed))
  }, [])

  /* A pin is a bookmark in a transcript that scrolls. It changes nothing about
     the turn — not what is sent, not what is recalled — which is why it is
     written straight through rather than folded into the turn's state. */
  const onPin = useCallback(async (item, pinned) => {
    if (!activeId || !item.rowId) return
    // Optimistic: the write is one boolean and the row is on screen, so waiting
    // for the round trip only makes the button feel broken.
    setItems((prev) => prev.map((i) => (i.rowId === item.rowId ? { ...i, pinned } : i)))
    try {
      await api.pinMessage(activeId, item.rowId, pinned)
    } catch (err) {
      setItems((prev) => prev.map((i) => (i.rowId === item.rowId ? { ...i, pinned: !pinned } : i)))
      toast(err.message, 'bad')
    }
  }, [activeId, toast])

  const jumpToItem = useCallback((id) => {
    const el = scrollRef.current?.querySelector(`[data-item="${id}"]`)
    if (!el) return
    setAtBottom(false)
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    el.classList.add('is-flash')
    setTimeout(() => el.classList.remove('is-flash'), 1200)
  }, [])

  // `⌘P` acts on the newest answer, which is what "pin that" almost always
  // means the moment after reading one.
  const togglePin = useCallback(() => {
    const last = [...items].reverse().find((i) => i.rowId && (i.kind === 'assistant' || i.kind === 'user'))
    if (!last) { toast('Nothing to pin yet', 'info'); return }
    onPin(last, !last.pinned)
    toast(last.pinned ? 'Unpinned' : 'Pinned', 'info')
  }, [items, onPin, toast])
  // What the keyboard layer and the palette drive. Registered as callbacks so
  // neither needs a copy of the turn's state to act on it.
  useEffect(() => {
    registerChat({
      stop,
      startFresh,
      selectConversation,
      focusComposer,
      toggleMemory,
      togglePin,
      openPlus: () => setPlusOpen(true),
      attach: () => fileRef.current?.click(),
      beginRename: (cid) => setRenaming(cid),
      turnRunning: turnState === 'running',
    })
  }, [registerChat, stop, startFresh, selectConversation, focusComposer, toggleMemory, togglePin, turnState, setRenaming])

  // Prompts arrive on the stream; this fetch recovers anything a reload left
  // suspended, since the turn survives the page and the stream does not.
  //
  // Pending prompts are process-wide, so they are split by conversation. One
  // belonging to a different conversation must not be raised over the
  // transcript being read here -- answering it would approve a tool call the
  // user cannot see the context for, and it blocks the page until they do.
  const refreshPending = useCallback(async () => {
    try {
      const rows = await api.confirmations()
      setPending(rows.filter((r) => !r.conversation_id || r.conversation_id === activeId))
      setElsewhere(rows.filter((r) => r.conversation_id && r.conversation_id !== activeId))
    } catch {
      /* the prompt still arrives on the stream; this is only the recovery path */
    }
  }, [activeId])

  useEffect(() => {
    // Only between turns: mid-turn the stream is the authority, and a fetch
    // would race it.
    if (turnState === 'idle') refreshPending()
  }, [refreshPending, turnState])

  const runAc = useCallback((value, cid) => {
    const m = value.match(/\/[\w-]{1,}$/)
    if (!m) { setAcItems([]); return }
    clearTimeout(acTimerRef.current)
    acTimerRef.current = setTimeout(async () => {
      try {
        setAcItems((await api.skillSearch(m[0].slice(1), cid)).slice(0, 6))
        setAcIndex(0)
      } catch { setAcItems([]) }
    }, 160)
  }, [])

  const acceptAc = useCallback((item) => {
    if (!item) return
    const m = input.match(/\/[\w-]*$/)
    const start = m ? m.index : input.length
    setInput(input.slice(0, start) + '/' + item.name + ' ')
    setAcItems([])
    textareaRef.current?.focus()
  }, [input])

  const onDecide = useCallback((id) => setPending((p) => p.filter((x) => x.id !== id)), [])

  const rendered = useMemo(() => buildRendered(items), [items])
  const pins = useMemo(() => rendered.filter((i) => i.pinned && i.text), [rendered])

  const isEmpty = rendered.length === 0 && turnState === 'idle'
  /* "Nobody has signed in yet" is not a failure, and the server has said so
     since connectors shipped -- `connectors_awaiting_sign_in` exists for
     exactly this. The banner showed both in the same red sentence, which made
     an ordinary un-signed-in Gmail look like a crash and made a real crash
     look ordinary. Split, and each gets the sentence it deserves. */
  const awaitingSignIn = health?.connectors_awaiting_sign_in ?? []
  const connectorErrors = Object.entries(health?.connector_errors ?? {})
    .filter(([name]) => !awaitingSignIn.includes(name))
  // A banner's signature is its content: dismissing "gmail: refused" hides that
  // exact sentence, and a later "gmail: timed out" is a new one that shows.
  const errorSig = `err:${connectorErrors.map(([n, e]) => `${n}=${e}`).join('|')}`
  const signInSig = `signin:${[...awaitingSignIn].sort().join(',')}`
  const shownModel = (active?.model ?? draftModel ?? '').split('/').pop() || 'no model'
  // Follow the stream, but never yank the view away from someone reading back.
  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 90)
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (!el || !atBottom) return
    el.scrollTo({ top: el.scrollHeight, behavior: turnState === 'running' ? 'auto' : 'smooth' })
  }, [rendered.length, turnState, liveTool, liveBuffer, liveReasoning, atBottom])

  const composer = (
    <div className={`composer-wrap${isEmpty ? ' composer-wrap--hero' : ''}`}>
      {plusOpen && (
        <PlusMenu
          placement={isEmpty ? 'down' : 'up'}
          conversationId={activeId}
          workspace={workspace}
          onWorkspace={setWorkspace}
          onNavigate={setView}
          onAttach={(file) => setAttachments((list) => [...list, file])}
          onClose={() => { setPlusOpen(false); refreshCaps() }}
        />
      )}

      {modelOpen && (
        <ModelMenu
          placement={isEmpty ? 'down' : 'up'}
          provider={active?.provider ?? draftProvider}
          model={active?.model ?? draftModel}
          scoped={Boolean(activeId)}
          onChange={applyModel}
          onClose={() => setModelOpen(false)}
        />
      )}

      {acItems.length > 0 && (
        <div className="ac-menu">
          {acItems.map((item, i) => (
            <button
              key={item.name}
              type="button"
              className={`ac-item${i === acIndex ? ' active' : ''}`}
              onMouseEnter={() => setAcIndex(i)}
              onClick={() => acceptAc(item)}
            >
              <span className="ac-name">/{item.name}</span>
              <span className="ac-desc">{item.description}</span>
            </button>
          ))}
        </div>
      )}

      <div className="composer">
        {attachments.length > 0 && (
          <div className="composer-files">
            {attachments.map((file) => (
              <span className="file-chip" key={file.path}>
                <Icon name="paperclip" size={12} />
                {file.name}
                <span className="file-chip-size">{Math.max(1, Math.round(file.bytes / 1024))}kB</span>
                <button
                  type="button"
                  onClick={() => setAttachments((list) => list.filter((f) => f.path !== file.path))}
                  aria-label={`Remove ${file.name}`}
                >
                  <Icon name="x" size={11} />
                </button>
              </span>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          placeholder={turnState === 'running' ? 'Working — Esc stops it' : 'Type / for skills'}
          disabled={turnState === 'running'}
          aria-label="Message"
          onChange={(e) => {
            setInput(e.target.value)
            runAc(e.target.value, activeId)
            e.target.style.height = 'auto'
            e.target.style.height = `${Math.min(e.target.scrollHeight, 260)}px`
          }}
          onPaste={(e) => {
            const files = [...(e.clipboardData?.files || [])]
            if (files.length) { e.preventDefault(); uploadFiles(files) }
          }}
          onKeyDown={(e) => {
            if (acItems.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
              e.preventDefault()
              setAcIndex((i) => (i + (e.key === 'ArrowDown' ? 1 : acItems.length - 1)) % acItems.length)
              return
            }
            if (acItems.length && (e.key === 'Enter' || e.key === 'Tab')) {
              e.preventDefault()
              acceptAc(acItems[acIndex])
              return
            }
            if (acItems.length && e.key === 'Escape') { e.stopPropagation(); setAcItems([]); return }
            if (e.key === 'ArrowUp' && !input && lastSent) {
              e.preventDefault()
              setInput(lastSent)
              return
            }
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
          }}
        />

        <div className="composer-bar">
          <button
            type="button"
            className={`composer-chip${plusOpen ? ' active' : ''}`}
            onClick={() => { setPlusOpen((o) => !o); setModelOpen(false) }}
            title={`Files, skills, connectors, memory — ${MOD_LABEL}+/`}
            aria-label="Files, skills, connectors, memory"
          >
            <Icon name="plus" size={16} />
          </button>

          <div className="composer-modes">
            {MODES.map((entry) => (
              <button
                key={entry.id}
                type="button"
                className={`mode${mode === entry.id ? ' active' : ''}`}
                onClick={() => setMode(entry.id)}
                title={entry.hint}
              >
                {entry.label}
              </button>
            ))}
          </div>

          <div className="composer-bar-right">
            <button
              type="button"
              className={`composer-model${modelOpen ? ' active' : ''}`}
              onClick={() => { setModelOpen((o) => !o); setPlusOpen(false) }}
              title="Provider and model"
            >
              {shownModel}
              <Icon name="chevron" size={11} style={{ transform: 'rotate(90deg)', opacity: 0.6 }} />
            </button>
            {turnState === 'running' ? (
              <button
                type="button"
                className="composer-send composer-send--stop"
                onClick={stop}
                disabled={stopping}
                title="Stop this turn on the server — Esc"
                aria-label="Stop"
              >
                <Icon name="stop" size={13} />
              </button>
            ) : (
              <button
                type="button"
                className="composer-send"
                onClick={send}
                disabled={!input.trim() && attachments.length === 0}
                title="Send — Enter"
                aria-label="Send"
              >
                <Icon name="send" size={15} />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* The connector strip that used to sit here reported the same thing the
          + menu does, in a row of coloured lamps under the field you type in.
          Two readings of one fact, and the louder one was below the composer. */}

      {isEmpty && (
        <div className="composer-hint">
          <span><kbd className="kbd">/</kbd> engages a skill</span>
          <span><kbd className="kbd">{MOD_LABEL}</kbd><kbd className="kbd">K</kbd> for everything else</span>
        </div>
      )}
    </div>
  )

  return (
    <div className="view view--flush">
      <input
        ref={fileRef}
        type="file"
        multiple
        hidden
        onChange={(e) => { uploadFiles([...e.target.files]); e.target.value = '' }}
      />

      <div className="chat-main">
        {elsewhere.length > 0 && (
          <div className="chat-banner msg-note msg-note--guard">
            <Icon name="key" size={14} />
            <span>
              {elsewhere.length === 1
                ? 'A tool call in another conversation is waiting for an answer.'
                : `${elsewhere.length} tool calls in other conversations are waiting for an answer.`}
              {' '}That turn stays suspended until it is answered.
            </span>
            <button
              type="button"
              className="btn btn--small"
              style={{ marginLeft: 'auto' }}
              onClick={() => selectConversation(elsewhere[0].conversation_id)}
            >
              Open it
            </button>
          </div>
        )}

        {connectorErrors.length > 0 && !dismissedBanners.has(errorSig) && (
          <div className="chat-banner msg-note msg-note--error">
            <Icon name="plug" size={14} />
            <span>
              {connectorErrors.map(([name, err]) => `${name}: ${String(err).slice(0, 90)}`).join(' · ')}
              {' '}— its tools are not reaching the agent.
            </span>
            <button
              type="button"
              className="btn btn--small"
              style={{ marginLeft: 'auto' }}
              onClick={() => { setCapabilitiesTab('connectors'); setView('capabilities') }}
            >
              Open connectors
            </button>
            <button
              type="button"
              className="chat-banner-dismiss"
              title="Dismiss until this changes"
              aria-label="Dismiss"
              onClick={() => dismissBanner(errorSig)}
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        )}

        {/* Amber, not coral, and with the one action that fixes it. A connector
            nobody has signed in to is a switch waiting to be flipped. */}
        {awaitingSignIn.length > 0 && !dismissedBanners.has(signInSig) && (
          <div className="chat-banner msg-note msg-note--guard">
            <Icon name="key" size={14} />
            <span>
              {awaitingSignIn.length === 1
                ? `${awaitingSignIn[0]} is switched on but not signed in.`
                : `${awaitingSignIn.join(', ')} are switched on but not signed in.`}
              {' '}Their tools stay out of reach until they are.
            </span>
            <button
              type="button"
              className="btn btn--small"
              style={{ marginLeft: 'auto' }}
              onClick={() => { setCapabilitiesTab('connectors'); setView('capabilities') }}
            >
              Sign in
            </button>
            <button
              type="button"
              className="chat-banner-dismiss"
              title="Dismiss until this changes"
              aria-label="Dismiss"
              onClick={() => dismissBanner(signInSig)}
            >
              <Icon name="x" size={13} />
            </button>
          </div>
        )}

        {isEmpty ? (
          <div className="hero-stack">
            <div className="hero">
              <h1>What needs doing?</h1>
            </div>
            {composer}
            <div className="hero-hints">
              {OPENERS.map((o) => (
                <button
                  key={o}
                  type="button"
                  className="hero-hint"
                  onClick={() => { setInput(o); textareaRef.current?.focus() }}
                >
                  {o}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {pins.length > 0 && (
              <div className={`pin-strip${pinsOpen ? ' open' : ''}`}>
                <button
                  type="button"
                  className="pin-strip-head"
                  onClick={() => setPinsOpen((o) => !o)}
                  aria-expanded={pinsOpen}
                >
                  <Icon name="pin" size={12} weight="fill" />
                  <span>{pins.length} pinned</span>
                  <Icon name="chevron" size={11} className="pin-strip-caret" />
                </button>
                {pinsOpen && (
                  <div className="pin-strip-list">
                    {pins.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        className="pin-chip"
                        onClick={() => jumpToItem(item.id)}
                        title={item.text}
                      >
                        <span className="pin-chip-who">{item.kind === 'user' ? 'you' : 'psok'}</span>
                        <span className="pin-chip-text">{item.text.replace(/\s+/g, ' ').slice(0, 90)}</span>
                        <span
                          role="button"
                          tabIndex={0}
                          className="pin-chip-off"
                          aria-label="Unpin"
                          onClick={(e) => { e.stopPropagation(); onPin(item, false) }}
                          onKeyDown={(e) => { if (e.key === 'Enter') { e.stopPropagation(); onPin(item, false) } }}
                        >
                          <Icon name="x" size={11} />
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
              <div className="chat-stream">
                {rendered.map((item) => (
                  <div key={item.id} data-item={item.id} className="stream-item">
                    <Msg
                      item={item}
                      onPin={onPin}
                      busy={turnState !== 'idle'}
                      onApprovePlan={approvePlan}
                      onEscalate={escalate}
                      onAnyway={answerAnyway}
                      onDiscardPlan={discardPlan}
                      onEditPlanStep={editPlanStep}
                    />
                  </div>
                ))}
                {turnState === 'running' && !liveTool && (
                  <div className="msg msg-assistant">
                    <div className="msg-role">psok</div>
                    {liveReasoning && <Reasoning text={liveReasoning} live={!liveBuffer} />}
                    {liveBuffer ? (
                      <div className="msg-body">
                        <Markdown text={liveBuffer} />
                        <span className="tele-cursor" />
                      </div>
                    ) : !liveReasoning && (
                      /* It said "Thinking" from the moment a turn opened
                         until the first token, whether the wait was the vault
                         search, a cold connector, a provider retry or the model.
                         The loop knew which; it just never said. */
                      <div className="thinking">
                        {statusLabel(liveStatus)}
                        <span className="thinking-dots"><i /><i /><i /></span>
                      </div>
                    )}
                  </div>
                )}
                {turnState === 'running' && liveTool && <ToolCallCard call={liveTool} running />}
              </div>
            </div>
            {!atBottom && (
              <button
                type="button"
                className="jump-latest"
                onClick={() => { setAtBottom(true); const el = scrollRef.current; el?.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }) }}
              >
                <Icon name="down" size={13} /> latest
              </button>
            )}
            {composer}
          </>
        )}
      </div>

      <ConfirmModal pending={pending} onDecide={onDecide} />
    </div>
  )
}
