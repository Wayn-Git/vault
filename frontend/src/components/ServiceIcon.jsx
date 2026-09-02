/* Brand marks for the connectors PSOK ships in its catalogue.

   These used to be drawn by hand in this file: an approximation of the GitHub
   octocat, a four-colour shape standing in for the Google G, a green circle
   with three arcs meant to read as Spotify. Every one of them was wrong in the
   way a traced logo is always wrong — proportions off, curves invented, colours
   guessed — and a wrong logo is worse than no logo, because it claims to be
   the thing it is not.

   They come from Simple Icons now (CC0, https://simpleicons.org), which is the
   brand's own published path data on a 24px grid. Each `.svg` is imported by
   Vite as an asset URL and painted through a CSS mask, so the geometry is
   authentic and the colour is still ours to control.

   Where a brand is not in Simple Icons — LinkedIn, Microsoft and Slack have
   asked to be removed, and Playwright, Tavily, Exa and Firecrawl were never in
   it — there is deliberately no mark. The initial on a neutral tile is honest
   about being a placeholder, which is the only alternative to inventing one. */

import githubMark from 'simple-icons/icons/github.svg'
import googleMark from 'simple-icons/icons/google.svg'
import chromeMark from 'simple-icons/icons/googlechrome.svg'
import gmailMark from 'simple-icons/icons/gmail.svg'
import calendarMark from 'simple-icons/icons/googlecalendar.svg'
import driveMark from 'simple-icons/icons/googledrive.svg'
import docsMark from 'simple-icons/icons/googledocs.svg'
import sheetsMark from 'simple-icons/icons/googlesheets.svg'
import slidesMark from 'simple-icons/icons/googleslides.svg'
import formsMark from 'simple-icons/icons/googleforms.svg'
import tasksMark from 'simple-icons/icons/googletasks.svg'
import googleChatMark from 'simple-icons/icons/googlechat.svg'
import vercelMark from 'simple-icons/icons/vercel.svg'
import spotifyMark from 'simple-icons/icons/spotify.svg'

/* Each brand's own colour, as Simple Icons publishes it. Kept beside the mark
   rather than fetched from `simple-icons/icons.json`, which is three and a half
   thousand entries this application would ship to read fourteen of. */
const MARKS = {
  github: { src: githubMark, hex: '#181717' },
  google: { src: googleMark, hex: '#4285F4' },
  chrome: { src: chromeMark, hex: '#4285F4' },
  gmail: { src: gmailMark, hex: '#EA4335' },
  calendar: { src: calendarMark, hex: '#4285F4' },
  drive: { src: driveMark, hex: '#4285F4' },
  docs: { src: docsMark, hex: '#4285F4' },
  sheets: { src: sheetsMark, hex: '#34A853' },
  slides: { src: slidesMark, hex: '#FBBC04' },
  forms: { src: formsMark, hex: '#7248B9' },
  tasks: { src: tasksMark, hex: '#2684FC' },
  chat: { src: googleChatMark, hex: '#34A853' },
  vercel: { src: vercelMark, hex: '#000000' },
  spotify: { src: spotifyMark, hex: '#1DB954' },
}

/* The Google applications each carry their own mark rather than nine copies of
   the Google G: a directory where every Google row looks identical is the
   problem the marks exist to solve. */
const ALIASES = {
  'google-workspace': 'google',
  'chrome-devtools': 'chrome',
  'google-gmail': 'gmail',
  'google-calendar': 'calendar',
  'google-drive': 'drive',
  'google-docs': 'docs',
  'google-sheets': 'sheets',
  'google-slides': 'slides',
  'google-forms': 'forms',
  'google-tasks': 'tasks',
  'google-chat': 'chat',
}

/* Two of the catalogue's entries are not brands at all — `fetch` is an HTTP
   client and `memory` is a store — so they get a drawn UI primitive, which is
   what a shape with nothing to be faithful to should be. */
const PRIMITIVES = new Set(['fetch', 'memory'])

/** sRGB relative luminance, for deciding whether a brand colour survives the
 *  tile it is being painted on. GitHub's #181717 on a near-black console is a
 *  logo you cannot see; the brand's own monochrome-on-dark treatment is the
 *  answer, not a colour nobody published. */
function tooDarkForDark(hex) {
  const n = parseInt(hex.slice(1), 16)
  const channel = (v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }
  const l = 0.2126 * channel((n >> 16) & 255)
    + 0.7152 * channel((n >> 8) & 255)
    + 0.0722 * channel(n & 255)
  return l < 0.16
}

export default function ServiceIcon({ name, size = 34, kind = 'connector' }) {
  const key = ALIASES[name] || name
  const mark = MARKS[key]

  if (mark) {
    return (
      <span className="svc svc--brand" style={{ width: size, height: size }} aria-hidden="true">
        <span
          className="svc-mark"
          style={{
            width: size * 0.6,
            height: size * 0.6,
            // `currentColor` through a mask: the published geometry, in a
            // colour that is legible against the surface it sits on.
            color: tooDarkForDark(mark.hex) ? 'var(--text)' : mark.hex,
            '--svc-mask': `url("${mark.src}")`,
          }}
        />
      </span>
    )
  }

  if (PRIMITIVES.has(key) || kind === 'skill') {
    return (
      <span
        className={`svc svc--primitive svc--${PRIMITIVES.has(key) ? key : 'skill'}`}
        style={{ width: size, height: size }}
        aria-hidden="true"
      >
        <svg width={size * 0.56} height={size * 0.56} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
          {key === 'fetch' && (
            <>
              <circle cx="12" cy="12" r="8.6" />
              <path d="M3.4 12h17.2M12 3.4c2.4 2.5 3.6 5.4 3.6 8.6s-1.2 6.1-3.6 8.6c-2.4-2.5-3.6-5.4-3.6-8.6S9.6 5.9 12 3.4Z" />
            </>
          )}
          {key === 'memory' && (
            <>
              <circle cx="7" cy="8" r="2.4" />
              <circle cx="16.6" cy="7" r="2" />
              <circle cx="13" cy="16.6" r="2.6" />
              <path d="M8.7 9.7 11.7 14M9.4 7.4l5.2-.3M15.8 8.9 14 14" />
            </>
          )}
          {!PRIMITIVES.has(key) && (
            <>
              <path d="M5.5 5.8A1.6 1.6 0 0 1 7.1 4.2H18v15.6H7.1a1.6 1.6 0 0 1-1.6-1.6Z" />
              <path d="M8.6 8.4h6.6M8.6 11.4h6.6M8.6 14.4h4.2" />
            </>
          )}
        </svg>
      </span>
    )
  }

  /* No published mark, and nothing to draw that would be true. An initial on a
     neutral tile says "this is a placeholder", which is the honest answer. */
  return (
    <span
      className="svc svc--generic"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.42) }}
      aria-hidden="true"
    >
      {(name || '?').slice(0, 1).toUpperCase()}
    </span>
  )
}
