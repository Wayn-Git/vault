import { useEffect, useRef } from 'react'
import Icon from './Icon.jsx'
import { useApp } from '../store.jsx'
import { MOD_LABEL } from '../keys.js'
import { forRail } from '../nav.js'
import { prefetchView } from '../views/registry.js'

/* The rail, reduced to what it is actually for.

   It used to be one 262px column carrying three unrelated jobs at once: the
   product's name, the list of places, and every conversation ever had. That is
   why it was the widest thing on the screen and still felt cramped, and it is
   why hiding it took the conversation list with it.

   The workbench splits those jobs. This is the first column: places, as marks,
   at the width a mark needs. The conversation list is its own column next
   door, and it survives the rail being collapsed because the two are no longer
   the same object. */

const PLACES = forRail()

export default function Sidebar() {
  const {
    view, setView, setOverlay, health, healthError,
    compact, railOpen, closeRail,
  } = useApp()
  const firstRef = useRef(null)

  /* Opening the drawer moves focus into it. A drawer that opens behind the
     keyboard's cursor is a drawer a keyboard user has to hunt for. */
  useEffect(() => {
    if (compact && railOpen) firstRef.current?.focus()
  }, [compact, railOpen])

  // Every way out of the drawer, in one place. The store closes it on a route
  // change, which covers the places -- but opening a conversation stays on
  // /chat, so the route never changes and the drawer sat over the transcript
  // the tap had just asked for.
  const leave = (act) => () => { act(); closeRail() }

  const status = healthError
    ? 'API offline'
    : health ? `${health.tools} tools · ${health.skills} skills` : 'connecting…'

  return (
    <nav
      id="rail"
      className="wb-rail"
      aria-label="Places"
      aria-hidden={compact && !railOpen ? 'true' : undefined}
    >
      <span className="wb-mark" aria-hidden="true">P</span>

      {PLACES.map((place) => (
        <button
          key={place.id}
          ref={place.id === PLACES[0].id ? firstRef : undefined}
          type="button"
          className={`wb-place${view === place.id ? ' active' : ''}`}
          aria-current={view === place.id ? 'page' : undefined}
          aria-label={place.label}
          title={place.label}
          onClick={leave(() => setView(place.id))}
          // Each view is its own script now, so the hover is where it gets
          // fetched: by the time the click lands it is already parsed.
          onPointerEnter={() => prefetchView(place.id)}
          onFocus={() => prefetchView(place.id)}
        >
          <Icon name={place.icon} size={19} />
          {place.beta && <i className="wb-place-beta" aria-hidden="true" />}
          <span className="wb-tip">{place.label}{place.beta && <i>beta</i>}</span>
        </button>
      ))}

      <button
        type="button"
        className="wb-place wb-place--foot"
        onClick={leave(() => setOverlay('settings'))}
        aria-label="Settings"
        title={`Settings — ${MOD_LABEL}+,`}
      >
        <Icon name="sliders" size={19} />
        <span className="wb-tip">Settings<i>{status}</i></span>
      </button>
    </nav>
  )
}
