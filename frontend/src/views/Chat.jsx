import { useCallback, useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import Icon from '../components/Icon.jsx'
import ToolCallCard from '../components/ToolCallCard.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'
import CapabilitiesPanel from '../components/CapabilitiesPanel.jsx'
import { useApp } from '../store.jsx'
import { api, fmtDate } from '../api.js'

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
      const calls = Array.isArray(m.tool_calls) ? m.tool_calls : []
      return { id: nextId(), kind: 'assistant', text: m.content ?? '', callsRaw: calls }
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
  const led = role === 'user' ? 'info' : role === 'assistant' ? 'amber' : 'faint'

  if (role === 'note') {
    const cls = item.tone === 'guard' ? 'msg-note--guard' : item.tone === 'error' ? 'msg-note--error' : 'msg-note--warning'
    return (
      <div className={`msg-note ${cls}`}>
        <span className={`led led--${item.tone === 'guard' ? 'amber' : item.tone === 'error' ? 'bad' : 'info'}`} />
        <span>{item.text}</span>
      </div>
    )
  }
  if (role === 'reasoning') {
    return (
      <div className="msg-reasoning">
        <span className="mono" style={{ fontSize: 10, letterSpacing: '0.18em', color: 'var(--text-faint)' }}>reasoning</span>
        <div>{item.text}</div>
      </div>
    )
  }
  if (role === 'tool') {
    return <ToolCallCard call={{ name: item.name, arguments: item.arguments ?? {}, content: item.content, status: item.isError ? 'error' : 'done' }} running={false} />
  }
  if (role === 'assistant') {
    return (
      <div className="msg msg-assistant">
        <div className="msg-role"><span className={`led led--${led}`} /> psok</div>
        {item.text && <div className="msg-body">{item.text}</div>}
        {item.toolCalls?.map((c, i) => (
          <ToolCallCard key={i} call={c} running={false} />
        ))}
      </div>
    )
  }
  return (
    <div className="msg msg-user">
      <div className="msg-role"><span className={`led led--${led}`} /> you</div>
      <div className="msg-body">{item.text}</div>
    </div>
  )
}

export default function Chat() {
  const { health, toast } = useApp()
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [items, setItems] = useState([])
  const [turnState, setTurnState] = useState('idle')
  const [liveTool, setLiveTool] = useState(null)
  const [liveBuffer, setLiveBuffer] = useState('')
  const [liveReasoning, setLiveReasoning] = useState('')
  const [pending, setPending] = useState([])
  const [showNew, setShowNew] = useState(false)
  const [draft, setDraft] = useState({ provider: '', model: 'default' })
  const [workspace, setWorkspace] = useState('')
  const [input, setInput] = useState('')
  const [capsOpen, setCapsOpen] = useState(false)
  const [acItems, setAcItems] = useState([])
  const [acIndex, setAcIndex] = useState(0)

  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const textareaRef = useRef(null)
  const acTimerRef = useRef(null)
  const liveRef = useRef({ buffer: '', reasoning: '', tool: null })

  const setBuffer = useCallback((t) => {
    liveRef.current.buffer = t
    setLiveBuffer(t)
  }, [])
  const setTool = useCallback((t) => {
    liveRef.current.tool = t
    setLiveTool(t)
  }, [])
  const setReasoning = useCallback((t) => {
    liveRef.current.reasoning = t
    setLiveReasoning(t)
  }, [])

  const refreshConvs = useCallback(async () => {
    try {
      setConversations(await api.conversations())
    } catch (err) {
      toast(`Conversations: ${err.message}`, 'bad')
    }
  }, [toast])

  useEffect(() => {
    refreshConvs()
  }, [refreshConvs])

  const loadMessages = useCallback(async (cid) => {
    try {
      const rows = await api.messages(cid)
      setItems(historyToItems(rows))
    } catch (err) {
      toast(`Messages: ${err.message}`, 'bad')
      setItems([])
    }
  }, [toast])

  const selectConversation = useCallback((cid) => {
    if (turnState !== 'idle') return
    setActiveId(cid)
    loadMessages(cid)
  }, [turnState, loadMessages])

  const pushAssistant = useCallback(() => {
    const { buffer, reasoning } = liveRef.current
    if (buffer || reasoning) {
      setItems((prev) => [
        ...prev,
        { id: nextId(), kind: 'assistant', text: buffer, callsRaw: [] },
      ])
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
    setBuffer('')
    setReasoning('')
    setTool(null)
    setPending([])
    await loadMessages(cid)
    refreshConvs()
  }, [loadMessages, refreshConvs, setBuffer, setReasoning, setTool])

  const onEvent = useCallback((evt) => {
    switch (evt.type) {
      case 'assistant_delta': {
        liveRef.current.buffer += evt.text ?? ''
        setBuffer(liveRef.current.buffer)
        break
      }
      case 'reasoning_delta': {
        liveRef.current.reasoning += evt.text ?? ''
        setReasoning(liveRef.current.reasoning)
        break
      }
      case 'assistant_text': {
        setBuffer(evt.text ?? '')
        break
      }
      case 'tool_call': {
        pushAssistant()
        setTool({ name: evt.name, arguments: evt.arguments ?? {}, status: 'running' })
        break
      }
      case 'tool_result': {
        const t = liveRef.current.tool
        if (t) {
          setItems((prev) => [...prev, { id: nextId(), kind: 'tool', name: t.name, arguments: t.arguments, content: evt.content ?? '', isError: Boolean(evt.is_error) }])
          setTool(null)
        } else {
          setItems((prev) => [...prev, { id: nextId(), kind: 'tool', name: evt.name, arguments: {}, content: evt.content ?? '', isError: Boolean(evt.is_error) }])
        }
        break
      }
      case 'done':
        pushAssistant()
        break
      case 'guard':
        pushNote('guard', evt.reason)
        break
      case 'error':
        pushNote('error', evt.message)
        break
      case 'warning':
        pushNote('warning', evt.message)
        break
      default:
        break
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
      if (err.name === 'AbortError') {
        pushNote('warning', 'Turn stopped by the user.')
      } else {
        pushNote('error', err.message)
      }
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
        const provider = draft.provider || health?.providers?.[0] || 'ollama'
        const { id } = await api.createConversation(provider, draft.model || 'default', message.slice(0, 56))
        cid = id
        setActiveId(id)
        refreshConvs()
        setShowNew(false)
      }
      await openTurn(cid, message)
    } catch (err) {
      toast(`Could not start turn: ${err.message}`, 'bad')
    }
  }, [input, turnState, activeId, draft, health, refreshConvs, openTurn, toast])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const runAc = useCallback((value, cid) => {
    const m = value.match(/\/[\w-]{1,}$/)
    if (!m) { setAcItems([]); return }
    clearTimeout(acTimerRef.current)
    acTimerRef.current = setTimeout(async () => {
      try {
        const items = await api.skillSearch(m[0].slice(1), cid)
        setAcItems(items.slice(0, 8))
        setAcIndex(0)
      } catch { setAcItems([]) }
    }, 160)
  }, [])

  const acceptAc = useCallback((item) => {
    const m = input.match(/\/[\w-]*$/)
    const start = m ? m.index : input.length
    const prefix = input.slice(0, start)
    const newVal = prefix + '/' + item.name + ' '
    setInput(newVal)
    setAcItems([])
    if (textareaRef.current) textareaRef.current.focus()
  }, [input])

  useEffect(() => {
    if (turnState !== 'running') return undefined
    const poll = setInterval(async () => {
      try {
        const list = await api.confirmations()
        setPending(list)
      } catch { /* transient */ }
    }, 1200)
    return () => clearInterval(poll)
  }, [turnState])

  const onDecide = useCallback((id) => {
    setPending((p) => p.filter((x) => x.id !== id))
  }, [])

  const rendered = buildRendered(items)
  const streamingAssistant = turnState === 'running' && !liveTool && (liveBuffer || liveReasoning)

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (turnState === 'running') {
      el.scrollTop = el.scrollHeight
    } else {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
    }
  }, [rendered.length, turnState, liveTool, items])

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const last = el.querySelector('.chat-stream > :last-child')
    if (!last) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const tween = gsap.from(last, { autoAlpha: 0, y: 10, duration: 0.3, ease: 'power2.out' })
    return () => { tween.kill() }
  }, [rendered.length])

  const active = conversations.find((c) => c.id === activeId)
  const providers = health?.providers ?? []

  return (
    <div className="view view--flush">
      <div className="chat-layout">
        <aside className="chat-side">
          <div className="chat-side-head">
            <button type="button" className="chat-new" onClick={() => setShowNew((s) => !s)}>
              <Icon name="plus" size={15} /> New conversation
            </button>
            {showNew && (
              <div className="card card-pad" style={{ padding: 14, display: 'grid', gap: 10 }}>
                <div className="field">
                  <label htmlFor="nc-provider">provider</label>
                  <select
                    id="nc-provider"
                    value={draft.provider || providers[0] || ''}
                    onChange={(e) => setDraft((d) => ({ ...d, provider: e.target.value }))}
                  >
                    {providers.length === 0 && <option value="">no providers found</option>}
                    {providers.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="nc-model">model</label>
                  <input
                    id="nc-model"
                    value={draft.model}
                    onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))}
                    placeholder="default"
                  />
                </div>
                <button type="button" className="btn btn--primary" onClick={send} disabled={turnState !== 'idle' || !input.trim()}>
                  Create & send
                </button>
              </div>
            )}
          </div>
          <div className="chat-convs">
            {conversations.length === 0 && (
              <div className="empty-state" style={{ padding: 30 }}>
                <Icon name="chat" size={20} />
                No conversations yet.
              </div>
            )}
            {conversations.map((c) => (
              <button key={c.id} type="button" className={`chat-conv${c.id === activeId ? ' active' : ''}`} onClick={() => selectConversation(c.id)}>
                <span className="chat-conv-title">{c.title || 'new conversation'}</span>
                <span className="chat-conv-meta">
                  <span>{c.provider}</span>·<span>{c.model}</span>
                  <span style={{ marginLeft: 'auto' }}>{fmtDate(c.updated_at)}</span>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <div className="chat-main">
          <div className="chat-scroll" ref={scrollRef}>
            <div className="chat-stream">
              {rendered.length === 0 && !streamingAssistant && (
                <div className="empty-state" style={{ paddingTop: 70 }}>
                  <span className={`led led--amber led--pulse`} />
                  <div>
                    <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, color: 'var(--text)' }}>Agent ready</div>
                    <div style={{ maxWidth: 340 }}>
                      Ask for anything — create tasks, check your calendar, read and edit files,
                      search notes, run shell commands. Sensitive operations will ask you first.
                    </div>
                  </div>
                </div>
              )}
              {rendered.map((item) => (
                <Msg key={item.id} item={item} />
              ))}
              {streamingAssistant && (
                <div className="msg msg-assistant">
                  <div className="msg-role"><span className="led led--amber led--pulse" /> psok</div>
                  {liveReasoning && (
                    <div className="msg-reasoning">{liveReasoning}</div>
                  )}
                  <div className="msg-body" style={{ color: 'var(--text-dim)' }}>
                    {liveBuffer}
                    <span className="tele-cursor" />
                  </div>
                </div>
              )}
              {turnState === 'running' && liveTool && (
                <ToolCallCard call={liveTool} running />
              )}
              {turnState === 'running' && !liveTool && !streamingAssistant && (
                <div className="msg-note msg-note--guard">
                  <span className="led led--amber led--pulse" /> thinking…
                </div>
              )}
            </div>
          </div>

          <div className="model-strip">
            {active ? (
              <>
                <span className="badge badge--amber">{active.provider} · {active.model}</span>
                <span className="mono">{conversations.findIndex((c) => c.id === activeId) + 1} of {conversations.length}</span>
              </>
            ) : (
              <span className="badge">no conversation — sending will create one</span>
            )}
            <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="mono">workspace</span>
              <input
                value={workspace}
                onChange={(e) => setWorkspace(e.target.value)}
                placeholder="~ (backend cwd)"
                style={{
                  background: 'var(--bg-sunken)', border: '1px solid var(--line)', borderRadius: 4,
                  padding: '3px 8px', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', width: 200,
                }}
              />
            </span>
          </div>

          <div className="composer-wrap">
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
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => setCapsOpen(true)}
                title="Skills & connectors"
                aria-label="Skills and connectors"
              >
                <Icon name="plus" size={17} />
              </button>
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                placeholder={turnState === 'running' ? 'Turn in progress…' : 'Message PSOK — type / to invoke a skill'}
                onChange={(e) => {
                  setInput(e.target.value)
                  runAc(e.target.value, activeId)
                  const el = e.target
                  el.style.height = 'auto'
                  el.style.height = `${Math.min(el.scrollHeight, 180)}px`
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
                  if (acItems.length && e.key === 'Escape') {
                    setAcItems([])
                    return
                  }
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    send()
                  }
                }}
                disabled={turnState === 'running'}
              />
              {turnState === 'running' ? (
                <button type="button" className="btn btn--danger" onClick={stop} title="Stop the turn">
                  <Icon name="stop" size={16} />
                </button>
              ) : (
                <button type="button" className="btn btn--primary" onClick={send} disabled={!input.trim()} title="Send (Enter)">
                  <Icon name="send" size={16} />
                </button>
              )}
            </div>
            <div className="composer-hint">
              <span>enter = send</span>
              <span>shift+enter = newline</span>
              <span>/name = invoke a skill</span>
              <span>+ = skills &amp; connectors</span>
              <span>medium/high-risk tools pause for your approval</span>
            </div>
          </div>
        </div>
      </div>

      <ConfirmModal pending={pending} onDecide={onDecide} />
      {capsOpen && <CapabilitiesPanel conversationId={activeId} onClose={() => setCapsOpen(false)} />}
    </div>
  )
}