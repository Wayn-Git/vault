import { useCallback, useEffect } from 'react'
import Icon from './components/Icon.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import Shortcuts from './components/Shortcuts.jsx'
import Settings from './components/Settings.jsx'
import Sidebar from './components/Sidebar.jsx'
import { BootScreen } from './components/Skeleton.jsx'
import { useApp } from './store.jsx'
import { chord, isTyping, MOD_LABEL } from './keys.js'
import Dashboard from './views/Dashboard.jsx'
import Chat from './views/Chat.jsx'
import Capabilities from './views/Capabilities.jsx'
import Automations from './views/Automations.jsx'
import Memory from './views/Memory.jsx'
import Logs from './views/Logs.jsx'
import Tasks from './views/Tasks.jsx'

const VIEWS = {
  chat: Chat,
  tasks: Tasks,
  capabilities: Capabilities,
  automations: Automations,
  memory: Memory,
  logs: Logs,
  dash: Dashboard,
}

// What ⌘1…6 reaches, in the order the rail lists them.
const ORDER = ['chat', 'tasks', 'capabilities', 'automations', 'memory', 'logs']

/* Every binding in one listener.

   Scattering `keydown` handlers across components is how two of them end up
   owning Escape and neither works reliably. This is the only global listener;
   local ones exist inside a field or an open menu, where they are about that
   field or that menu, and they stop propagation when they act. */
function useGlobalKeys() {
  const {
    view, setView, overlay, setOverlay, chat, conversations, activeId, setSidebar,
  } = useApp()

  const cycleConversation = useCallback((delta) => {
    if (!conversations.length) return
    const at = conversations.findIndex((c) => c.id === activeId)
    const next = conversations[(at + delta + conversations.length) % conversations.length]
    if (next && next.id !== activeId) {
      setView('chat')
      chat.selectConversation?.(next.id)
    }
  }, [conversations, activeId, chat, setView])

  useEffect(() => {
    const onKey = (e) => {
      const combo = chord(e)
      const typing = isTyping(e.target)

      // Escape is shared: whatever is open closes first, and only when nothing
      // is open does it reach the running turn.
      if (combo === 'escape') {
        if (overlay) { e.preventDefault(); setOverlay(null); return }
        if (chat.turnRunning) { e.preventDefault(); chat.stop?.(); return }
        return
      }

      if (combo === 'mod+k') { e.preventDefault(); setOverlay(overlay === 'palette' ? null : 'palette'); return }
      if (combo === 'mod+shift+o') { e.preventDefault(); setView('chat'); chat.startFresh?.(); return }
      if (combo === 'mod+l') { e.preventDefault(); setView('chat'); chat.focusComposer?.(); return }
      if (combo === 'mod+/') { e.preventDefault(); setView('chat'); chat.openPlus?.(); return }
      if (combo === 'mod+u') { e.preventDefault(); setView('chat'); chat.attach?.(); return }
      if (combo === 'mod+b') { e.preventDefault(); setSidebar((s) => !s); return }
      if (combo === 'mod+,') { e.preventDefault(); setOverlay(overlay === 'settings' ? null : 'settings'); return }
      if (combo === 'mod+arrowup') { e.preventDefault(); cycleConversation(-1); return }
      if (combo === 'mod+arrowdown') { e.preventDefault(); cycleConversation(1); return }
      if (combo === 'mod+m') { e.preventDefault(); chat.toggleMemory?.(); return }
      if (combo === 'mod+p') { e.preventDefault(); setView('chat'); chat.togglePin?.(); return }
      if (combo === 'f2' && activeId) { e.preventDefault(); setView('chat'); chat.beginRename?.(activeId); return }

      const digit = /^mod\+([1-6])$/.exec(combo)
      if (digit) {
        e.preventDefault()
        setView(ORDER[Number(digit[1]) - 1])
        return
      }

      if (!typing && (combo === 'shift+?' || combo === '?')) {
        e.preventDefault()
        setOverlay(overlay === 'shortcuts' ? null : 'shortcuts')
        return
      }
      // Bare `/` from anywhere goes where a skill name is typed.
      if (!typing && combo === '/' && view === 'chat') {
        e.preventDefault()
        chat.focusComposer?.('/')
      }
    }

    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [view, setView, overlay, setOverlay, chat, cycleConversation, setSidebar, activeId])
}

function StageTop() {
  const { setOverlay, health, healthError, view, setView } = useApp()
  const degraded = health?.status === 'degraded'
  return (
    <div className="stage-top">
      {view !== 'chat' && (
        <button type="button" className="stage-back" onClick={() => setView('chat')}>
          <Icon name="chevron" size={13} style={{ transform: 'rotate(180deg)' }} /> Chat
        </button>
      )}
      <div className="stage-top-actions">
        {(healthError || degraded) && (
          <button
            type="button"
            className="stage-warn"
            onClick={() => setView('dash')}
            title={healthError || 'A connector failed to start'}
          >
            {healthError ? 'API offline' : 'degraded'}
          </button>
        )}
        <button
          type="button"
          className="stage-cmd"
          onClick={() => setOverlay('palette')}
          title="Command palette"
        >
          <Icon name="search" size={13} />
          <kbd className="kbd">{MOD_LABEL}</kbd><kbd className="kbd">K</kbd>
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => setOverlay('shortcuts')}
          title="Keyboard shortcuts"
          aria-label="Keyboard shortcuts"
        >
          <Icon name="keyboard" size={15} />
        </button>
        <button
          type="button"
          className="icon-btn"
          onClick={() => setOverlay('settings')}
          title={`Settings — ${MOD_LABEL}+,`}
          aria-label="Settings"
        >
          <Icon name="sliders" size={15} />
        </button>
      </div>
    </div>
  )
}

function Toasts() {
  const { toasts } = useApp()
  return (
    <div className="toast-wrap">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { view, server, retryServer } = useApp()
  useGlobalKeys()

  const Active = VIEWS[view] || Chat

  useEffect(() => {
    document.title = 'PSOK · personal operating system'
  }, [])

  // Nothing is mounted until the backend answers. Every view here opens by
  // fetching, so mounting them against a container that is still booting draws
  // a page of failures and then leaves it there -- a deploy that looks broken
  // for the fifty seconds it takes to start. The frame says what is happening
  // instead, and the views mount into real data.
  if (server.phase !== 'ready') {
    return <BootScreen server={server} onRetry={retryServer} />
  }

  return (
    <div className="app">
      <Sidebar />
      <div className="stage">
        <StageTop />
        {/* Chat stays mounted: unmounting it mid-turn would drop the stream. */}
        <main className={`main${view === 'chat' ? '' : ' main--hidden'}`}>
          <ErrorBoundary><Chat /></ErrorBoundary>
        </main>
        {view !== 'chat' && (
          <main className="main view-swap" key={view}>
            <ErrorBoundary><Active /></ErrorBoundary>
          </main>
        )}
      </div>
      <CommandPalette />
      <Shortcuts />
      <Settings />
      <Toasts />
    </div>
  )
}
