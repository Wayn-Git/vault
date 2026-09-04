import { Suspense, useCallback, useEffect, useRef } from 'react'
import { Routes, Route } from 'react-router-dom'
import Icon from './components/Icon.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import CommandPalette from './components/CommandPalette.jsx'
import Shortcuts from './components/Shortcuts.jsx'
import Settings from './components/Settings.jsx'
import Sidebar from './components/Sidebar.jsx'
import ConversationList from './components/ConversationList.jsx'
import ConfirmDialogHost from './components/ui/ConfirmDialog.jsx'
import { BootScreen, SkeletonView } from './components/Skeleton.jsx'
import { useApp } from './store.jsx'
import { chord, isTyping, MOD_LABEL } from './keys.js'
import { NAV, byDigit, byId } from './nav.js'
import { COMPONENTS } from './views/registry.js'
import Chat from './views/Chat.jsx'

/* The workbench.

   Four columns, each with one job, instead of two columns with four jobs
   between them. The marks on the left are where you can go. The column beside
   them is what you have said. The middle is the thing you are doing. The panel
   on the right is the machinery behind it -- every tool call, every step, every
   number -- which used to be interleaved with the answer in the middle column
   and made a conversation read like a build log.

   The two outer columns collapse independently, so a narrow window loses the
   history before it loses the navigation, and a wide one can show all four. */

// Every routed view except chat, which is rendered outside <Routes> below.
const ROUTED = NAV.filter((v) => v.id !== 'chat')

/* Every binding in one listener.

   Scattering `keydown` handlers across components is how two of them end up
   owning Escape and neither works reliably. This is the only global listener;
   local ones exist inside a field or an open menu, where they are about that
   field or that menu, and they stop propagation when they act. */
function useGlobalKeys() {
  const {
    view, setView, overlay, setOverlay, chat, conversations, activeId,
    toggleRail, closeRail, compact, railOpen,
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
      // is open does it reach the running turn. The drawer sits between them --
      // it covers the page on a phone, so it is "what is open" there too.
      if (combo === 'escape') {
        if (overlay) { e.preventDefault(); setOverlay(null); return }
        if (compact && railOpen) { e.preventDefault(); closeRail(); return }
        if (chat.turnRunning) { e.preventDefault(); chat.stop?.(); return }
        return
      }

      if (combo === 'mod+k') { e.preventDefault(); setOverlay(overlay === 'palette' ? null : 'palette'); return }
      if (combo === 'mod+shift+o') { e.preventDefault(); setView('chat'); chat.startFresh?.(); return }
      if (combo === 'mod+l') { e.preventDefault(); setView('chat'); chat.focusComposer?.(); return }
      if (combo === 'mod+/') { e.preventDefault(); setView('chat'); chat.openPlus?.(); return }
      if (combo === 'mod+u') { e.preventDefault(); setView('chat'); chat.attach?.(); return }
      if (combo === 'mod+b') { e.preventDefault(); toggleRail(); return }
      if (combo === 'mod+,') { e.preventDefault(); setOverlay(overlay === 'settings' ? null : 'settings'); return }
      if (combo === 'mod+arrowup') { e.preventDefault(); cycleConversation(-1); return }
      if (combo === 'mod+arrowdown') { e.preventDefault(); cycleConversation(1); return }
      if (combo === 'mod+m') { e.preventDefault(); chat.toggleMemory?.(); return }
      if (combo === 'mod+p') { e.preventDefault(); setView('chat'); chat.togglePin?.(); return }
      if (combo === 'f2' && activeId) { e.preventDefault(); setView('chat'); chat.beginRename?.(activeId); return }

      const digit = /^mod\+([1-9])$/.exec(combo)
      if (digit) {
        e.preventDefault()
        const target = byDigit(Number(digit[1]))
        if (target) setView(target.id)
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
  }, [
    view, setView, overlay, setOverlay, chat, cycleConversation, activeId,
    toggleRail, closeRail, compact, railOpen,
  ])
}

/* The bar over the working column.

   It says where you are, which the rail no longer can now that the rail is
   marks, and it holds the two switches for the columns either side of it. */
function WorkbenchBar() {
  const {
    setOverlay, health, healthError, view, setView, compact, railOpen, toggleRail,
    panel, togglePanel,
  } = useApp()
  const degraded = health?.status === 'degraded'
  const here = byId(view)

  return (
    <header className="wb-bar">
      {compact && (
        <button
          type="button"
          className="icon-btn stage-menu"
          onClick={toggleRail}
          aria-label="Open navigation"
          aria-expanded={railOpen}
          aria-controls="rail"
        >
          <Icon name="sidebar" size={18} />
        </button>
      )}
      {!compact && !railOpen && (
        <button
          type="button"
          className="icon-btn"
          onClick={toggleRail}
          title={`Show the sidebar — ${MOD_LABEL}+B`}
          aria-label="Show the sidebar"
        >
          <Icon name="sidebar" size={16} />
        </button>
      )}

      <h1 className="wb-where">{here?.label ?? 'Chat'}</h1>

      <div className="wb-bar-actions">
        {(healthError || degraded) && (
          <button
            type="button"
            className="wb-warn"
            onClick={() => setView('dash')}
            title={healthError || 'A connector failed to start'}
          >
            <i aria-hidden="true" />
            {healthError ? 'API offline' : 'Degraded'}
          </button>
        )}
        <button
          type="button"
          className={compact ? 'icon-btn' : 'wb-search'}
          onClick={() => setOverlay('palette')}
          title="Command palette"
          aria-label="Command palette"
        >
          <Icon name="search" size={compact ? 17 : 14} />
          {/* The chord is the point of the wide form, and there is no chord on
              a touch device — so the label goes when the keyboard does. */}
          {!compact && (
            <>
              <span>Search or jump to</span>
              <kbd className="kbd">{MOD_LABEL}</kbd><kbd className="kbd">K</kbd>
            </>
          )}
        </button>
        {!compact && (
          <button
            type="button"
            className="icon-btn"
            onClick={() => setOverlay('shortcuts')}
            title="Keyboard shortcuts"
            aria-label="Keyboard shortcuts"
          >
            <Icon name="keyboard" size={16} />
          </button>
        )}
        {!compact && (
          <button
            type="button"
            className={`icon-btn${panel ? ' is-on' : ''}`}
            onClick={togglePanel}
            title={panel ? 'Hide the steps panel' : 'Show the steps panel'}
            aria-label={panel ? 'Hide the steps panel' : 'Show the steps panel'}
            aria-pressed={panel}
          >
            <Icon name="layout" size={16} />
          </button>
        )}
        <button
          type="button"
          className="icon-btn"
          onClick={() => setOverlay('settings')}
          title={`Settings — ${MOD_LABEL}+,`}
          aria-label="Settings"
        >
          <Icon name="sliders" size={compact ? 17 : 16} />
        </button>
      </div>
    </header>
  )
}

/* The drawer's backdrop.
 *
 * It is a button rather than a div because tapping it is the ordinary way out
 * of the drawer on a touch device, and an interactive element that only a
 * pointer can reach is exactly the thing this pass exists to remove. */
function RailScrim({ onClose }) {
  return (
    <button
      type="button"
      className="rail-scrim"
      aria-label="Close navigation"
      onClick={onClose}
    />
  )
}

function Toasts() {
  const { toasts } = useApp()
  /* `aria-live` is the whole point of a toast for anyone not looking at the
     corner of the screen: "connector ready, 16 tools" was visible feedback and
     silent feedback at the same time. Polite, because none of these interrupt
     anything. */
  return (
    <div className="toast-wrap" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.tone}`}>
          <span>{t.message}</span>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { view, server, retryServer, compact, railOpen, closeRail, panel } = useApp()
  useGlobalKeys()
  const stageRef = useRef(null)

  /* The tab reports where you are. It used to say the same eleven words on
     every page, which makes a row of pinned tabs unreadable and a browser's
     history search useless. */
  useEffect(() => {
    const here = byId(view)
    document.title = here && here.id !== 'chat'
      ? `${here.label} · PSOK`
      : 'PSOK · personal operating system'
  }, [view])

  // Nothing is mounted until the backend answers. Every view here opens by
  // fetching, so mounting them against a container that is still booting draws
  // a page of failures and then leaves it there -- a deploy that looks broken
  // for the fifty seconds it takes to start. The frame says what is happening
  // instead, and the views mount into real data.
  if (server.phase !== 'ready') {
    return <BootScreen server={server} onRetry={retryServer} />
  }

  const isChat = view === 'chat'
  const drawerOpen = compact && railOpen

  return (
    <div
      className={
        `wb app${compact ? ' app--compact wb--compact' : ''}`
        + `${drawerOpen ? ' app--drawer wb--drawer' : ''}`
        + `${railOpen ? '' : ' wb--rail-hidden'}`
        + `${panel ? '' : ' wb--panel-hidden'}`
      }
    >
      <Sidebar />
      <ConversationList />
      {drawerOpen && <RailScrim onClose={closeRail} />}
      {/* `inert` is what keeps a screen reader and the Tab key out of the page
          the drawer is covering. Without it the drawer looks modal and behaves
          like a decoration. */}
      {/* A real boolean: React 19 reflects `inert` from one, and an empty
          string is treated as false, which quietly left the page behind the
          drawer fully tabbable. */}
      <div className="wb-main stage" ref={stageRef} inert={drawerOpen}>
        <WorkbenchBar />
        {/* Chat stays mounted, outside <Routes>: unmounting it mid-turn
            would drop the stream. */}
        <main className={`main${isChat ? '' : ' main--hidden'}`}>
          <ErrorBoundary><Chat /></ErrorBoundary>
        </main>
        {!isChat && (
          <main className="main view-swap" key={view}>
            <ErrorBoundary>
              {/* The skeleton stands in for the chunk arriving, which on a
                  local server is one frame and on a slow connection is the
                  difference between a blank stage and a page loading. */}
              <Suspense fallback={<SkeletonView rows={5} aside={view === 'tasks' || view === 'mail'} />}>
                <Routes>
                  {ROUTED.map((v) => {
                    const Comp = COMPONENTS[v.id]
                    return <Route key={v.id} path={v.path} element={<Comp />} />
                  })}
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </main>
        )}
      </div>
      {/* The panel is a slot rather than a component: whichever view is open
          fills it through a portal, and it collapses on its own when nothing
          has anything to put there. */}
      <aside className="wb-panel" id="wb-panel" aria-label="Run detail" inert={drawerOpen} />
      <CommandPalette />
      <Shortcuts />
      <Settings />
      <ConfirmDialogHost />
      <Toasts />
    </div>
  )
}
