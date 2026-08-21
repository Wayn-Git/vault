import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api.js'

/* One store for everything that is not the transcript.

   The transcript stays inside Chat because it changes on every streamed token
   and nothing else needs to watch it. What lives here is what more than one
   surface has to agree on: which view is open, what the machine currently is,
   which conversations exist, and what the agent may reach. The command palette
   and the keyboard layer are built entirely from this, which is why toggling a
   connector from a hotkey and toggling it from the + menu are the same code. */

const AppCtx = createContext(null)

const KEY = 'psok.ui.v1'

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

function savePrefs(patch) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...loadPrefs(), ...patch }))
  } catch {
    /* private mode, or a full quota: preferences are a convenience, not state */
  }
}

const HEALTH_INTERVAL = 20000

export function AppProvider({ children }) {
  const prefs = useRef(loadPrefs()).current

  const [view, setViewRaw] = useState(prefs.view || 'chat')
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState(null)
  const [toasts, setToasts] = useState([])
  const [overlay, setOverlay] = useState(null) // 'palette' | 'shortcuts' | null

  const [conversations, setConversations] = useState([])
  const [activeId, setActiveIdRaw] = useState(prefs.activeId || null)
  const [caps, setCaps] = useState({ skills: [], connectors: [] })
  const [busyCap, setBusyCap] = useState('')
  const [workspace, setWorkspaceRaw] = useState(prefs.workspace || '')
  // Which conversation is being retitled. It lives here because the rail draws
  // the row and the keyboard layer starts the edit.
  const [renaming, setRenaming] = useState(null)
  const [sidebar, setSidebarRaw] = useState(prefs.sidebar !== false)

  // Chat owns the turn, so the palette and the keyboard layer reach it through
  // callbacks it registers rather than through a copy of its state.
  const chatRef = useRef({})

  const setView = useCallback((next) => {
    setViewRaw(next)
    savePrefs({ view: next })
  }, [])

  const setActiveId = useCallback((next) => {
    setActiveIdRaw(next)
    savePrefs({ activeId: next })
  }, [])

  const setWorkspace = useCallback((next) => {
    setWorkspaceRaw(next)
    savePrefs({ workspace: next })
  }, [])

  const setSidebar = useCallback((next) => {
    setSidebarRaw((prev) => {
      const value = typeof next === 'function' ? next(prev) : next
      savePrefs({ sidebar: value })
      return value
    })
  }, [])

  const toast = useCallback((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t.filter((x) => x.message !== message), { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4600)
  }, [])

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health()
      setHealth(h)
      setHealthError(null)
      return h
    } catch (err) {
      setHealthError(err.message)
      return null
    }
  }, [])

  const refreshConvs = useCallback(async () => {
    try {
      const rows = await api.conversations()
      setConversations(rows)
      return rows
    } catch (err) {
      setHealthError(err.message)
      return []
    }
  }, [])

  const renameConversation = useCallback(async (id, title) => {
    setRenaming(null)
    const clean = (title || '').trim()
    if (!clean) return
    try {
      await api.updateConversation(id, { title: clean })
      await refreshConvs()
    } catch (err) {
      toast(err.message, 'bad')
    }
  }, [refreshConvs, toast])

  const refreshCaps = useCallback(async (scope = activeId) => {
    try {
      const next = await api.capabilities(scope || null)
      setCaps(next)
      return next
    } catch {
      return null
    }
  }, [activeId])

  /** Flip a skill or connector and report what actually happened.
   *
   *  A connector starts a real process, so the answer is not "on" but "running
   *  with N tools" or "failed, here is why". Both callers -- the + menu and the
   *  palette -- need that distinction, so it is resolved once, here. */
  const setCapEnabled = useCallback(async (cap, enabled) => {
    const token = `${cap.kind}:${cap.name}`
    setBusyCap(token)
    try {
      const result = await api.toggleCapability(cap.kind, cap.name, enabled, activeId || null)
      const live = result?.live || {}
      if (cap.kind === 'connector') {
        if (live.error) toast(`${cap.name} could not start — ${live.error}`, 'bad')
        else if (live.connected) toast(`${cap.name} ready · ${live.tools} tools`, 'ok')
        else toast(`${cap.name} ${enabled ? 'on' : 'off'}`, 'info')
        refreshHealth()
      } else {
        toast(`${cap.name} ${enabled ? 'engaged' : 'stood down'}`, enabled ? 'ok' : 'info')
      }
      await refreshCaps()
      return result
    } catch (err) {
      toast(err.message, 'bad')
      return null
    } finally {
      setBusyCap('')
    }
  }, [activeId, refreshCaps, refreshHealth, toast])

  useEffect(() => { refreshHealth() }, [refreshHealth])
  useEffect(() => { refreshConvs() }, [refreshConvs])
  useEffect(() => { refreshCaps() }, [refreshCaps])

  // A connector can die between messages and the API only notices at the start
  // of a turn, so the header has to keep asking.
  useEffect(() => {
    const tick = setInterval(refreshHealth, HEALTH_INTERVAL)
    const onFocus = () => refreshHealth()
    window.addEventListener('focus', onFocus)
    return () => {
      clearInterval(tick)
      window.removeEventListener('focus', onFocus)
    }
  }, [refreshHealth])

  const value = useMemo(() => ({
    view, setView,
    health, healthError, refreshHealth,
    toasts, toast,
    overlay, setOverlay,
    conversations, refreshConvs,
    activeId, setActiveId,
    renaming, setRenaming, renameConversation,
    caps, refreshCaps, setCapEnabled, busyCap,
    workspace, setWorkspace,
    sidebar, setSidebar,
    chat: chatRef.current,
    registerChat: (actions) => Object.assign(chatRef.current, actions),
  }), [
    view, setView, health, healthError, refreshHealth, toasts, toast, overlay,
    conversations, refreshConvs, activeId, setActiveId, caps, refreshCaps,
    setCapEnabled, busyCap, workspace, setWorkspace, sidebar, setSidebar,
    renaming, renameConversation,
  ])

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp outside AppProvider')
  return ctx
}
