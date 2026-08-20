import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const AppCtx = createContext(null)

export function AppProvider({ children }) {
  const [view, setView] = useState('dash')
  const [health, setHealth] = useState(null)
  const [healthError, setHealthError] = useState(null)
  const [toasts, setToasts] = useState([])

  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health()
      setHealth(h)
      setHealthError(null)
      return h
    } catch (err) {
      setHealthError(err.message)
      setHealth(null)
      return null
    }
  }, [])

  const toast = useCallback((message, tone = 'info') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((t) => [...t, { id, message, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200)
  }, [])

  useEffect(() => {
    refreshHealth()
  }, [refreshHealth])

  const value = useMemo(
    () => ({ view, setView, health, healthError, refreshHealth, toasts, toast }),
    [view, health, healthError, refreshHealth, toasts, toast],
  )

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp outside AppProvider')
  return ctx
}