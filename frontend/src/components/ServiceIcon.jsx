/* Brand marks for the connectors PSOK ships in its catalogue.

   A directory of tiles is unreadable without them: every row looks identical
   when the only difference is a word. These are drawn rather than fetched --
   the page must not reach out to a CDN to render a menu, and a broken image is
   worse than a letter in a coloured square. Anything unknown falls back to its
   initial on a neutral tile, which is honest about being a placeholder. */

const MARKS = {
  github: {
    bg: '#1c2128',
    node: (
      <path
        fill="#e6edf3"
        d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7C6.73 19.9 6.14 18 6.14 18c-.45-1.16-1.1-1.47-1.1-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2Z"
      />
    ),
  },
  google: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#4285F4" d="M21.6 12.23c0-.71-.06-1.4-.18-2.05H12v3.88h5.38a4.6 4.6 0 0 1-2 3.02v2.5h3.24c1.89-1.74 2.98-4.3 2.98-7.35Z" />
        <path fill="#34A853" d="M12 22c2.7 0 4.96-.9 6.62-2.42l-3.24-2.5c-.9.6-2.05.96-3.38.96-2.6 0-4.8-1.76-5.59-4.12H3.06v2.58A10 10 0 0 0 12 22Z" />
        <path fill="#FBBC05" d="M6.41 13.92a6 6 0 0 1 0-3.83V7.5H3.06a10 10 0 0 0 0 9l3.35-2.58Z" />
        <path fill="#EA4335" d="M12 5.98c1.47 0 2.79.51 3.83 1.5l2.87-2.87C16.95 2.99 14.7 2 12 2a10 10 0 0 0-8.94 5.5l3.35 2.59C7.2 7.73 9.4 5.98 12 5.98Z" />
      </>
    ),
  },
  chrome: {
    bg: '#ffffff',
    node: (
      <>
        <circle cx="12" cy="12" r="9.5" fill="#fff" />
        <path fill="#EA4335" d="M12 2.5a9.5 9.5 0 0 1 8.23 4.76H12a4.74 4.74 0 0 0-4.1 2.37L4.4 4.6A9.47 9.47 0 0 1 12 2.5Z" />
        <path fill="#FBBC05" d="M4.4 4.6 8 9.63a4.74 4.74 0 0 0 .12 4.9L4.03 19.2A9.5 9.5 0 0 1 4.4 4.6Z" />
        <path fill="#34A853" d="M20.23 7.26a9.5 9.5 0 0 1-8.6 14.22l4.1-7.1a4.74 4.74 0 0 0 .3-4.75l4.2-2.37Z" />
        <circle cx="12" cy="12" r="3.6" fill="#4285F4" />
      </>
    ),
  },
  playwright: {
    bg: '#2d4a3e',
    node: (
      <>
        <circle cx="12" cy="12" r="8.5" fill="#2ead6a" />
        <path fill="#0b1a12" d="M8.4 10.4h2.2v1.5H8.4zm5 0h2.2v1.5h-2.2zM7.5 15c1.4 1.6 3 2.4 4.7 2.4s3.2-.8 4.4-2.4c-1.5.8-3 1.2-4.5 1.2s-3-.4-4.6-1.2Z" />
      </>
    ),
  },
  fetch: {
    bg: '#1f2a37',
    node: (
      <>
        <circle cx="12" cy="12" r="8.5" fill="none" stroke="#7dd3fc" strokeWidth="1.6" />
        <path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.3 3.6 8.5s-1.2 6.1-3.6 8.5c-2.4-2.4-3.6-5.3-3.6-8.5S9.6 5.9 12 3.5Z" fill="none" stroke="#7dd3fc" strokeWidth="1.4" />
      </>
    ),
  },
  memory: {
    bg: '#2a2440',
    node: (
      <>
        <circle cx="7" cy="8" r="2.4" fill="#c4b5fd" />
        <circle cx="16.5" cy="7" r="2" fill="#a78bfa" />
        <circle cx="13" cy="16.5" r="2.6" fill="#8b5cf6" />
        <path d="M8.6 9.6 11.6 14M9.3 7.4l5.3-.3M15.7 8.8 13.9 14" stroke="#7c6bb0" strokeWidth="1.2" />
      </>
    ),
  },
  gmail: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#EA4335" d="M3 7.1 12 13l9-5.9V6a1.4 1.4 0 0 0-1.4-1.4H4.4A1.4 1.4 0 0 0 3 6v1.1Z" />
        <path fill="#34A853" d="M3 8.9V18a1.4 1.4 0 0 0 1.4 1.4h2.4V11L3 8.9Z" />
        <path fill="#4285F4" d="M17.2 19.4h2.4A1.4 1.4 0 0 0 21 18V8.9L17.2 11v8.4Z" />
        <path fill="#FBBC05" d="M6.8 19.4h10.4V11L12 14.5 6.8 11v8.4Z" />
      </>
    ),
  },
  calendar: {
    bg: '#ffffff',
    node: (
      <>
        <rect x="3.5" y="4.5" width="17" height="15" rx="2" fill="#fff" stroke="#4285F4" strokeWidth="1.6" />
        <path d="M3.5 8.5h17" stroke="#4285F4" strokeWidth="1.6" />
        <path fill="#4285F4" d="M7 2.8h1.6v3H7zm8.4 0H17v3h-1.6z" />
        <text x="12" y="16.6" textAnchor="middle" fontSize="7.5" fontWeight="700" fill="#4285F4" fontFamily="system-ui, sans-serif">31</text>
      </>
    ),
  },
  drive: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#0F9D58" d="m8.6 3.5 6.8 11.8h-6.8L5.2 9.4 8.6 3.5Z" />
        <path fill="#F4B400" d="M15.4 3.5H8.6l6.8 11.8 3.4-5.9L15.4 3.5Z" />
        <path fill="#4285F4" d="M2 15.3h13.6l-3.4 5.9H5.4L2 15.3Z" opacity="0.95" />
      </>
    ),
  },
  docs: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#4285F4" d="M6 2.6h7l5 5v13.8H6V2.6Z" />
        <path fill="#a1c2fa" d="M13 2.6l5 5h-5v-5Z" />
        <path d="M8.6 11h6.8M8.6 13.8h6.8M8.6 16.6h4.4" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" />
      </>
    ),
  },
  sheets: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#0F9D58" d="M6 2.6h7l5 5v13.8H6V2.6Z" />
        <path fill="#a8dbc0" d="M13 2.6l5 5h-5v-5Z" />
        <path d="M8.6 11.2h6.8v6.2H8.6zM8.6 13.3h6.8M8.6 15.4h6.8M12 11.2v6.2" stroke="#fff" strokeWidth="1.2" fill="none" />
      </>
    ),
  },
  slides: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#F4B400" d="M6 2.6h7l5 5v13.8H6V2.6Z" />
        <path fill="#fae2a6" d="M13 2.6l5 5h-5v-5Z" />
        <rect x="8.6" y="11.4" width="6.8" height="5" rx="0.6" fill="#fff" />
      </>
    ),
  },
  forms: {
    bg: '#ffffff',
    node: (
      <>
        <path fill="#7248B9" d="M6 2.6h7l5 5v13.8H6V2.6Z" />
        <path fill="#c3aee0" d="M13 2.6l5 5h-5v-5Z" />
        <path d="M9.4 11.6h5.6M9.4 14.2h5.6M9.4 16.8h3.4" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" />
      </>
    ),
  },
  tasks: {
    bg: '#ffffff',
    node: (
      <>
        <circle cx="12" cy="12" r="9" fill="#2684FC" />
        <path d="M8 12.2l2.6 2.6L16 9.4" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </>
    ),
  },
  chat: {
    bg: '#ffffff',
    node: (
      <path
        fill="#00AC47"
        d="M4.6 3.5h14.8A1.6 1.6 0 0 1 21 5.1v9.6a1.6 1.6 0 0 1-1.6 1.6H9.8L5 20.5v-4.2h-.4A1.6 1.6 0 0 1 3 14.7V5.1a1.6 1.6 0 0 1 1.6-1.6Z"
      />
    ),
  },
  vercel: {
    bg: '#000000',
    node: <path fill="#ffffff" d="M12 3.5 21.5 20.5H2.5L12 3.5Z" />,
  },
  linkedin: {
    bg: '#0a66c2',
    node: (
      <>
        <rect x="3" y="3" width="18" height="18" rx="2.4" fill="#0a66c2" />
        <circle cx="7.4" cy="7.4" r="1.7" fill="#fff" />
        <path fill="#fff" d="M6.1 10.2h2.6v8H6.1zM10.4 10.2H13v1.1a3 3 0 0 1 2.6-1.3c2 0 3 1.3 3 3.6v4.6h-2.6v-4.1c0-1.1-.4-1.8-1.4-1.8s-1.6.7-1.6 1.8v4.1h-2.6v-8Z" />
      </>
    ),
  },
  spotify: {
    bg: '#1db954',
    node: (
      <>
        <circle cx="12" cy="12" r="9.2" fill="#1db954" />
        <path
          d="M7.4 9.6c3-.8 6.2-.5 8.8 1M8 12.5c2.5-.6 5.1-.4 7.3.9M8.6 15.3c2-.5 4-.3 5.8.7"
          stroke="#000"
          strokeWidth="1.5"
          strokeLinecap="round"
          fill="none"
        />
      </>
    ),
  },
  'microsoft-todo': {
    bg: '#ffffff',
    node: (
      <>
        <rect x="3.2" y="4.5" width="17.6" height="15" rx="1.8" fill="#2564cf" />
        <path d="M3.2 8.2h17.6" stroke="#fff" strokeWidth="1.2" opacity="0.5" />
        <path d="M8 13.8l2.4 2.4 5-5" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </>
    ),
  },
  skill: {
    bg: '#2b2721',
    node: (
      <>
        <path d="M5 5.6A1.6 1.6 0 0 1 6.6 4H18v16H6.6A1.6 1.6 0 0 1 5 18.4V5.6Z" fill="#e9b872" opacity="0.9" />
        <path d="M8 8h7M8 11h7M8 14h4.5" stroke="#2b2721" strokeWidth="1.3" strokeLinecap="round" />
      </>
    ),
  },
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

export default function ServiceIcon({ name, size = 34, kind = 'connector' }) {
  const key = ALIASES[name] || name
  const mark = MARKS[key] || (kind === 'skill' ? MARKS.skill : null)

  if (!mark) {
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

  return (
    <span className="svc" style={{ width: size, height: size, background: mark.bg }} aria-hidden="true">
      <svg width={size * 0.66} height={size * 0.66} viewBox="0 0 24 24" fill="none">
        {mark.node}
      </svg>
    </span>
  )
}
