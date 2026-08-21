import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import Markdown from '../components/Markdown.jsx'
import ToolCallCard from '../components/ToolCallCard.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'
import PlusMenu, { connectorState } from '../components/PlusMenu.jsx'
import ModelMenu from '../components/ModelMenu.jsx'
import { useApp } from '../store.jsx'
import { api, copyText } from '../api.js'
import { MOD_LABEL } from '../keys.js'

/* The composer is the interface. Everything else — which skills are live, which
   connectors it may reach, what it remembers, where it may work — hangs off the
   + menu beside it or the palette above it, so the surface stays one field and
   a sentence. */

const FALLBACK_PROVIDER = 'nvidia'
const FALLBACK_MODEL = 'nvidia/nemotron-3-ultra-550b-a55b'

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
    if (m.role === 'user') return { id: nextId(), kind: 'user', text: m.content }
    if (m.role === 'assistant') {
      return {
        id: nextId(),
        kind: 'assistant',
        text: m.content ?? '',
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
   lie about what the model committed to. It gets its own collapsed block. */
function Reasoning({ text, live }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className={`reasoning${open ? ' open' : ''}`}>
      <button type="button" className="reasoning-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name="spark" size={12} />
        <span>{live ? 'thinking' : 'thought for a moment'}</span>
        {live && <span className="led led--amber led--pulse" />}
        <Icon name="chevron" size={12} style={{ transform: open ? 'rotate(90deg)' : 'none' }} />
      </button>
      {open && <div className="reasoning-body">{text}</div>}
    </div>
  )
}

function Msg({ item }) {
  const role = item.kind

  if (role === 'note') {
    const cls = item.tone === 'guard'
      ? 'msg-note--guard'
      : item.tone === 'error' ? 'msg-note--error' : 'msg-note--warning'
    return (
      <div className={`msg-note ${cls}`}>
        <span className={`led led--${item.tone === 'guard' ? 'amber' : item.tone === 'error' ? 'bad' : 'info'}`} />
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
  if (role === 'reasoning') return <Reasoning text={item.text} />
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
      <div className="msg msg-assistant">
        <div className="msg-role">
          <span className="led led--faint" /> psok
          <CopyButton text={item.text} label="Copy this answer" />
        </div>
        {item.text && <div className="msg-body"><Markdown text={item.text} /></div>}
        {item.toolCalls?.map((c, i) => <ToolCallCard key={i} call={c} running={false} />)}
      </div>
    )
  }
  return (
    <div className="msg msg-user">
      <div className="msg-role">you<CopyButton text={item.text} label="Copy" /></div>
      <div className="msg-body msg-body--plain">{item.text}</div>
    </div>
  )
}

export default function Chat() {
  const {
    health, refreshHealth, setView, toast, registerChat,
    conversations, refreshConvs, activeId, setActiveId, setRenaming,
    caps, refreshCaps, setCapEnabled, busyCap,
    workspace, setWorkspace,
  } = useApp()

  const [items, setItems] = useState([])
  const [turnState, setTurnState] = useState('idle')
  const [stopping, setStopping] = useState(false)
  const [liveTool, setLiveTool] = useState(null)
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
  const [plan, setPlan] = useState(false)
  const [atBottom, setAtBottom] = useState(true)
  const [lastSent, setLastSent] = useState('')

  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  const fileRef = useRef(null)
  const acTimerRef = useRef(null)
  const liveRef = useRef({ buffer: '', reasoning: '', tool: null })

  const providers = health?.providers ?? []
  const defaults = health?.provider_defaults ?? {}
  const active = conversations.find((c) => c.id === activeId)

  // What to use when nothing has been chosen: the house default if this machine
  // has it configured, otherwise whatever it does have.
  const fallbackProvider = providers.includes(FALLBACK_PROVIDER) ? FALLBACK_PROVIDER : providers[0]
  const draftProvider = draft.provider || fallbackProvider || ''
  const draftModel =
    draft.model || defaults[draftProvider] || (draftProvider === FALLBACK_PROVIDER ? FALLBACK_MODEL : '')

  const setBuffer = useCallback((t) => { liveRef.current.buffer = t; setLiveBuffer(t) }, [])
  const setTool = useCallback((t) => { liveRef.current.tool = t; setLiveTool(t) }, [])
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
  useEffect(() => { loadMessages(activeId) }, [activeId, loadMessages])

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
    const { buffer, reasoning } = liveRef.current
    if (reasoning) {
      setItems((prev) => [...prev, { id: nextId(), kind: 'reasoning', text: reasoning }])
      setReasoning('')
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

  const finish = useCallback(async (cid) => {
    setTurnState('idle')
    setStopping(false)
    setBuffer('')
    setReasoning('')
    setTool(null)
    setPending([])
    setElsewhere([])
    await loadMessages(cid)
    refreshConvs()
    // A turn is when connectors reconcile, so the tool count and any connector
    // failure only become knowable once one has run.
    refreshHealth()
    refreshCaps()
  }, [loadMessages, refreshConvs, refreshHealth, refreshCaps, setBuffer, setReasoning, setTool])

  const onEvent = useCallback((evt) => {
    switch (evt.type) {
      case 'assistant_delta':
        liveRef.current.buffer += evt.text ?? ''
        setBuffer(liveRef.current.buffer)
        break
      case 'reasoning_delta':
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
      case 'done': pushAssistant(); break
      case 'guard': pushNote('guard', evt.reason); break
      case 'error': pushNote('error', evt.message); break
      case 'warning': pushNote('warning', evt.message); break
      default: break
    }
  }, [pushAssistant, pushNote, setBuffer, setReasoning, setTool])

  const openTurn = useCallback(async (cid, message) => {
    setItems((prev) => [...prev, { id: nextId(), kind: 'user', text: message }])
    setTurnState('running')
    setAtBottom(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      await api.turn({
        conversationId: cid,
        message,
        workspace: workspace.trim() || null,
        onEvent,
        signal: controller.signal,
      })
    } catch (err) {
      if (err.name === 'AbortError') pushNote('warning', 'Stopped.')
      else pushNote('error', err.message)
    } finally {
      finish(cid)
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

  const send = useCallback(async () => {
    const typed = input.trim()
    if ((!typed && attachments.length === 0) || turnState !== 'idle') return
    const attached = attachments.length
      ? `\n\nAttached files (read them with view_file):\n${attachments.map((f) => `- ${f.path}`).join('\n')}`
      : ''
    const prefix = plan
      ? 'Plan first: list the steps you intend to take and what each one will'
        + ' touch, then stop and wait. Do not write files or run commands this turn.\n\n'
      : ''
    const message = `${prefix}${typed}${attached}`
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
        const { id } = await api.createConversation(
          draftProvider,
          draftModel || 'default',
          (typed || attachments[0]?.name || 'untitled').slice(0, 56),
        )
        cid = id
        setActiveId(id)
        refreshConvs()
      }
      await openTurn(cid, message)
    } catch (err) {
      toast(err.message, 'bad')
      setTurnState('idle')
    }
  }, [
    input, attachments, plan, turnState, activeId, draftProvider, draftModel,
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

  // What the keyboard layer and the palette drive. Registered as callbacks so
  // neither needs a copy of the turn's state to act on it.
  useEffect(() => {
    registerChat({
      stop,
      startFresh,
      selectConversation,
      focusComposer,
      toggleMemory,
      openPlus: () => setPlusOpen(true),
      attach: () => fileRef.current?.click(),
      beginRename: (cid) => setRenaming(cid),
      turnRunning: turnState === 'running',
    })
  }, [registerChat, stop, startFresh, selectConversation, focusComposer, toggleMemory, turnState, setRenaming])

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
  const streamingAssistant = turnState === 'running' && !liveTool && (liveBuffer || liveReasoning)
  const isEmpty = rendered.length === 0 && !streamingAssistant && turnState === 'idle'
  const connectorErrors = Object.entries(health?.connector_errors ?? {})
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
  }, [rendered.length, turnState, liveTool, liveBuffer, atBottom])

  const composer = (
    <div className={`composer-wrap${isEmpty ? ' composer-wrap--hero' : ''}`}>
      {plusOpen && (
        <PlusMenu
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
            <button
              type="button"
              className={`mode${plan ? '' : ' active'}`}
              onClick={() => setPlan(false)}
              title="Answer and act in one turn"
            >
              Chat
            </button>
            <button
              type="button"
              className={`mode${plan ? ' active' : ''}`}
              onClick={() => setPlan(true)}
              title="Ask for the plan before anything is run"
            >
              Plan
            </button>
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

      {caps.connectors.length > 0 && (
        <div className="armed">
          <span className="armed-label">reach</span>
          {caps.connectors.map((cap) => {
            const state = connectorState(cap, busyCap === `connector:${cap.name}`)
            return (
              <button
                key={cap.name}
                type="button"
                className={`armed-chip${state.tone === 'live' ? ' is-live' : ''}${state.tone === 'error' ? ' is-error' : ''}${state.tone === 'busy' ? ' is-busy' : ''}`}
                onClick={() => setCapEnabled(cap, !cap.enabled)}
                disabled={busyCap === `connector:${cap.name}`}
                title={
                  state.detail
                    ? `${cap.name}: ${state.detail}`
                    : state.tone === 'live'
                      ? `${cap.name} is running with ${cap.live.tools} tools — click to stop it`
                      : `${cap.name} is ${state.label} — click to start it`
                }
              >
                <span className={`led led--${state.dot}${state.tone === 'busy' ? ' led--pulse' : ''}`} />
                {cap.name}
                {state.tone === 'live' && <span className="armed-count">{cap.live.tools}</span>}
                {state.tone === 'error' && <span className="armed-count">failed</span>}
              </button>
            )
          })}
        </div>
      )}

      <div className="composer-hint">
        <span>enter sends</span>
        <span>shift + enter for a new line</span>
        <span>/name engages a skill</span>
        <span><kbd className="kbd">{MOD_LABEL}</kbd><kbd className="kbd">K</kbd> for everything else</span>
      </div>
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

        {connectorErrors.length > 0 && (
          <div className="chat-banner msg-note msg-note--error">
            <Icon name="plug" size={14} />
            <span>
              {connectorErrors.map(([name, err]) => `${name}: ${String(err).slice(0, 90)}`).join(' · ')}
              {' '}— its tools are not reaching the agent.
            </span>
          </div>
        )}

        {isEmpty ? (
          <div className="hero-stack">
            <div className="hero">
              <h1><span className="hero-mark">✳</span> What needs doing?</h1>
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
            <div className="chat-scroll" ref={scrollRef} onScroll={onScroll}>
              <div className="chat-stream">
                {rendered.map((item) => <Msg key={item.id} item={item} />)}
                {streamingAssistant && (
                  <div className="msg msg-assistant">
                    <div className="msg-role"><span className="led led--faint led--pulse" /> psok</div>
                    {liveReasoning && <Reasoning text={liveReasoning} live />}
                    {liveBuffer && (
                      <div className="msg-body">
                        <Markdown text={liveBuffer} />
                        <span className="tele-cursor" />
                      </div>
                    )}
                  </div>
                )}
                {turnState === 'running' && liveTool && <ToolCallCard call={liveTool} running />}
                {turnState === 'running' && !liveTool && !streamingAssistant && (
                  <div className="msg-note msg-note--guard">
                    <span className="led led--amber led--pulse" /> thinking
                  </div>
                )}
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
