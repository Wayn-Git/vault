import { useCallback, useEffect, useRef, useState } from 'react'
import Icon from '../components/Icon.jsx'
import ToolCallCard from '../components/ToolCallCard.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'
import PlusMenu, { connectorState } from '../components/PlusMenu.jsx'
import { useApp } from '../store.jsx'
import { api, fmtDate } from '../api.js'

/* The composer is the interface. Everything else — which skills are live, which
   connectors it may reach, what it remembers, where it may work — hangs off the
   + menu beside it, so the surface stays one field and a sentence. */

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
  if (role === 'reasoning') {
    return (
      <div className="msg-reasoning">
        <span className="mono" style={{ fontSize: 10, letterSpacing: '0.2em', textTransform: 'uppercase' }}>
          thinking
        </span>
        <div>{item.text}</div>
      </div>
    )
  }
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
    return (
      <div className="msg msg-assistant">
        <div className="msg-role"><span className="led led--faint" /> psok</div>
        {item.text && <div className="msg-body">{item.text}</div>}
        {item.toolCalls?.map((c, i) => <ToolCallCard key={i} call={c} running={false} />)}
      </div>
    )
  }
  return (
    <div className="msg msg-user">
      <div className="msg-role">you</div>
      <div className="msg-body">{item.text}</div>
    </div>
  )
}

export default function Chat() {
  const { health, refreshHealth, setView, toast } = useApp()
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [items, setItems] = useState([])
  const [turnState, setTurnState] = useState('idle')
  const [stopping, setStopping] = useState(false)
  const [liveTool, setLiveTool] = useState(null)
  const [liveBuffer, setLiveBuffer] = useState('')
  const [liveReasoning, setLiveReasoning] = useState('')
  const [pending, setPending] = useState([])
  const [workspace, setWorkspace] = useState('')
  const [input, setInput] = useState('')
  const [plusOpen, setPlusOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [draft, setDraft] = useState({ provider: '', model: '' })
  const [acItems, setAcItems] = useState([])
  const [acIndex, setAcIndex] = useState(0)
  const [caps, setCaps] = useState({ skills: [], connectors: [] })
  const [arming, setArming] = useState('')

  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
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

  const refreshConvs = useCallback(async () => {
    try { setConversations(await api.conversations()) } catch (err) { toast(err.message, 'bad') }
  }, [toast])

  useEffect(() => { refreshConvs() }, [refreshConvs])

  // What the agent can actually reach. Refreshed when the conversation changes
  // and after every turn, because a connector can die between messages.
  const refreshCaps = useCallback(async () => {
    try { setCaps(await api.capabilities(activeId || null)) } catch { /* strip stays as it was */ }
  }, [activeId])

  useEffect(() => { refreshCaps() }, [refreshCaps])

  const armConnector = useCallback(async (cap) => {
    setArming(cap.name)
    try {
      // Starts or stops the process and waits for the outcome, so the chip
      // never reports a capability the agent does not have.
      const result = await api.toggleCapability('connector', cap.name, !cap.enabled, activeId || null)
      const live = result.live || {}
      if (live.error) toast(`${cap.name} could not start — ${live.error}`, 'bad')
      else if (live.connected) toast(`${cap.name} ready — ${live.tools} tools`, 'ok')
      await refreshCaps()
      refreshHealth()
    } catch (err) {
      toast(err.message, 'bad')
    } finally {
      setArming('')
    }
  }, [activeId, refreshCaps, refreshHealth, toast])

  // Prompts arrive on the stream; this one fetch recovers anything a reload left
  // suspended, since the turn survives the page and the stream does not.
  useEffect(() => { api.confirmations().then(setPending).catch(() => {}) }, [])

  const loadMessages = useCallback(async (cid) => {
    try {
      setItems(historyToItems(await api.messages(cid)))
    } catch (err) {
      toast(err.message, 'bad')
      setItems([])
    }
  }, [toast])

  const selectConversation = useCallback((cid) => {
    if (turnState !== 'idle') return
    setActiveId(cid)
    loadMessages(cid)
  }, [turnState, loadMessages])

  const startFresh = useCallback(() => {
    if (turnState !== 'idle') return
    setActiveId(null)
    setItems([])
    setInput('')
  }, [turnState])

  const pushAssistant = useCallback(() => {
    const { buffer, reasoning } = liveRef.current
    if (buffer || reasoning) {
      setItems((prev) => [...prev, { id: nextId(), kind: 'assistant', text: buffer, callsRaw: [] }])
      setBuffer('')
    }
    if (reasoning) {
      setItems((prev) => [...prev, { id: nextId(), kind: 'reasoning', text: reasoning }])
      setReasoning('')
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
    await loadMessages(cid)
    refreshConvs()
    // A turn is when connectors reconcile, so the tool count and any connector
    // failure only become knowable once one has run.
    refreshHealth()
  }, [loadMessages, refreshConvs, refreshHealth, setBuffer, setReasoning, setTool])

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

  const send = useCallback(async () => {
    const message = input.trim()
    if (!message || turnState !== 'idle') return
    setInput('')
    setAcItems([])
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
    let cid = activeId
    try {
      if (!cid) {
        if (!draftProvider) { toast('No provider is configured in providers.yaml', 'bad'); return }
        const { id } = await api.createConversation(
          draftProvider,
          draftModel || 'default',
          message.slice(0, 56),
        )
        cid = id
        setActiveId(id)
        refreshConvs()
      }
      await openTurn(cid, message)
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [input, turnState, activeId, draftProvider, draftModel, refreshConvs, openTurn, toast])

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
    const m = input.match(/\/[\w-]*$/)
    const start = m ? m.index : input.length
    setInput(input.slice(0, start) + '/' + item.name + ' ')
    setAcItems([])
    textareaRef.current?.focus()
  }, [input])

  const onDecide = useCallback((id) => setPending((p) => p.filter((x) => x.id !== id)), [])

  const rendered = buildRendered(items)
  const streamingAssistant = turnState === 'running' && !liveTool && (liveBuffer || liveReasoning)
  const isEmpty = rendered.length === 0 && !streamingAssistant && turnState === 'idle'
  const connectorErrors = Object.entries(health?.connector_errors ?? {})
  const shownModel = (active?.model ?? draftModel ?? '').split('/').pop() || 'no model'

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: turnState === 'running' ? 'auto' : 'smooth' })
  }, [rendered.length, turnState, liveTool, liveBuffer])

  const composer = (
    <div className={`composer-wrap${isEmpty ? ' composer-wrap--hero' : ''}`}>
      {plusOpen && (
        <PlusMenu
          conversationId={activeId}
          workspace={workspace}
          onWorkspace={setWorkspace}
          onNavigate={setView}
          onChanged={setCaps}
          onClose={() => { setPlusOpen(false); refreshCaps() }}
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

      {modelOpen && (
        <div className="plus-menu" style={{ left: 'auto', right: 26, width: 320 }}>
          <div className="plus-head">model · {activeId ? 'this conversation' : 'for the next one'}</div>
          <div style={{ padding: '4px 11px 12px', display: 'grid', gap: 10 }}>
            <div className="field">
              <label htmlFor="mdl-provider">provider</label>
              <select
                id="mdl-provider"
                value={active?.provider ?? draftProvider}
                onChange={(e) => {
                  const provider = e.target.value
                  applyModel({ provider, ...(defaults[provider] ? { model: defaults[provider] } : {}) })
                }}
              >
                {providers.length === 0 && <option value="">none configured</option>}
                {providers.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="mdl-model">model</label>
              <input
                id="mdl-model"
                key={`${activeId ?? 'draft'}-${active?.model ?? draftModel}`}
                defaultValue={active?.model ?? draftModel}
                onKeyDown={(e) => { if (e.key === 'Enter') e.target.blur() }}
                onBlur={(e) => {
                  const model = e.target.value.trim()
                  if (model && model !== (active?.model ?? draftModel)) applyModel({ model })
                }}
              />
              <span className="hint">Resolved fresh every turn — switching mid-conversation is this write.</span>
            </div>
            <button type="button" className="btn btn--small" onClick={() => setModelOpen(false)}>Done</button>
          </div>
        </div>
      )}

      <div className="composer">
        <div className="composer-core">
          <textarea
            ref={textareaRef}
            rows={1}
            value={input}
            placeholder={turnState === 'running' ? 'Working…' : 'Ask for anything on this machine'}
            disabled={turnState === 'running'}
            onChange={(e) => {
              setInput(e.target.value)
              runAc(e.target.value, activeId)
              e.target.style.height = 'auto'
              e.target.style.height = `${Math.min(e.target.scrollHeight, 220)}px`
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
              if (acItems.length && e.key === 'Escape') { setAcItems([]); return }
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
            }}
          />
          <div className="composer-bar">
            <button
              type="button"
              className={`composer-chip${plusOpen ? ' active' : ''}`}
              onClick={() => { setPlusOpen((o) => !o); setModelOpen(false) }}
              title="Skills, connectors, memory, workspace"
              aria-label="Skills, connectors, memory, workspace"
            >
              <Icon name="plus" size={15} />
            </button>
            <button
              type="button"
              className={`composer-chip${modelOpen ? ' active' : ''}`}
              onClick={() => { setModelOpen((o) => !o); setPlusOpen(false) }}
              title="Provider and model"
            >
              {shownModel}
              <Icon name="chevron" size={11} style={{ transform: 'rotate(-90deg)', opacity: 0.6 }} />
            </button>
            <div className="composer-bar-right">
              {turnState === 'running' ? (
                <button
                  type="button"
                  className="composer-send composer-send--stop"
                  onClick={stop}
                  disabled={stopping}
                  title="Stop this turn on the server"
                  aria-label="Stop"
                >
                  <Icon name="stop" size={13} />
                </button>
              ) : (
                <button
                  type="button"
                  className="composer-send"
                  onClick={send}
                  disabled={!input.trim()}
                  title="Send — Enter"
                  aria-label="Send"
                >
                  <Icon name="send" size={14} />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {caps.connectors.length > 0 && (
        <div className="armed">
          <span className="armed-label">reach</span>
          {caps.connectors.map((cap) => {
            const state = connectorState(cap, arming === cap.name)
            return (
              <button
                key={cap.name}
                type="button"
                className={`armed-chip${state.tone === 'live' ? ' is-live' : ''}${state.tone === 'error' ? ' is-error' : ''}${state.tone === 'busy' ? ' is-busy' : ''}`}
                onClick={() => armConnector(cap)}
                disabled={arming === cap.name}
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
        <span>writes and shell commands ask first</span>
      </div>
    </div>
  )

  return (
    <div className="view view--flush">
      <div className="chat-layout">
        <aside className="chat-side">
          <div className="chat-side-head">
            <button
              type="button"
              className="chat-new"
              onClick={startFresh}
              disabled={turnState !== 'idle'}
            >
              <Icon name="plus" size={14} /> New conversation
            </button>
          </div>
          <div className="chat-convs">
            {conversations.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`chat-conv${c.id === activeId ? ' active' : ''}`}
                onClick={() => selectConversation(c.id)}
                title={`${c.provider} · ${c.model}`}
              >
                <span className="chat-conv-title">{c.title || 'untitled'}</span>
                <span className="chat-conv-meta">{fmtDate(c.updated_at)}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="chat-main">
          {connectorErrors.length > 0 && (
            <div className="msg-note msg-note--error" style={{ margin: '14px 26px 0' }}>
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
                <h1>What needs doing?</h1>
                <p className="hero-sub">
                  Files, shell, tasks, calendar, your notes and whatever you have connected,
                  reachable from one line. Anything that writes or runs asks you first.
                </p>
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
              {composer}
            </div>
          ) : (
            <>
              <div className="chat-scroll" ref={scrollRef}>
                <div className="chat-stream">
                  {rendered.map((item) => <Msg key={item.id} item={item} />)}
                  {streamingAssistant && (
                    <div className="msg msg-assistant">
                      <div className="msg-role"><span className="led led--faint led--pulse" /> psok</div>
                      {liveReasoning && <div className="msg-reasoning">{liveReasoning}</div>}
                      <div className="msg-body">
                        {liveBuffer}
                        <span className="tele-cursor" />
                      </div>
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
              {composer}
            </>
          )}
        </div>
      </div>

      <ConfirmModal pending={pending} onDecide={onDecide} />
    </div>
  )
}
