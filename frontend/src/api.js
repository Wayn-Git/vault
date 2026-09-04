/* Where the API is.

   Empty in development and in the single-process build, where the API is served
   from the same origin as this bundle and `/api` is a relative path. Set
   `VITE_API_BASE` at build time to point a separately deployed interface at a
   separately deployed backend -- a Vercel frontend at a Render service, say.
   Trailing slashes are trimmed so `https://host/` and `https://host` mean the
   same thing rather than producing `https://host//api`. */
export const API_ORIGIN = (import.meta.env?.VITE_API_BASE || '').trim().replace(/\/+$/, '')

const BASE = `${API_ORIGIN}/api`

/* Waking the backend.

   A free-tier container is stopped when nothing has asked it for anything, and
   the request that wakes it waits out a cold start -- tens of seconds, during
   which every call the interface makes on mount is queued behind the same boot.
   Rendering a blank page for that long reads as a broken deploy.

   So: one request goes out the moment this module is evaluated, which is before
   React has mounted, and the interface draws its own frame around the wait
   instead of waiting for the first answer to arrive. Views read `phase` and
   show a skeleton rather than an empty room.

   Same-origin builds resolve this on the first attempt and never see it. */
const WAKE_ATTEMPT_TIMEOUT = 9000
const WAKE_GAP = 1500
const WAKE_GIVE_UP_AFTER = 90000

let state = { phase: 'waking', since: Date.now(), attempts: 0, error: null }
const watchers = new Set()

function publish(patch) {
  state = { ...state, ...patch }
  for (const fn of watchers) {
    try { fn(state) } catch { /* a bad watcher must not stop the others */ }
  }
}

/** Subscribe to the backend's reachability. Called immediately with the
 *  current state, and returns the unsubscribe. */
export function onServerState(fn) {
  watchers.add(fn)
  fn(state)
  return () => watchers.delete(fn)
}

export const serverState = () => state

async function ping(timeout) {
  // `/api/ping` on purpose rather than `/api/health`: health surveys every
  // provider, which can itself take seconds and is the wrong thing to make a
  // cold start wait for. Any request wakes the container; the cheapest one
  // should be the one that does it.
  const stop = new AbortController()
  const timer = setTimeout(() => stop.abort(), timeout)
  try {
    const res = await fetch(`${BASE}/ping`, { signal: stop.signal, cache: 'no-store' })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

/** Keep asking until the backend answers, or until it has had long enough. */
export async function wakeBackend() {
  if (state.phase === 'ready') return true
  publish({ phase: 'waking', since: Date.now(), attempts: 0, error: null })
  const deadline = Date.now() + WAKE_GIVE_UP_AFTER
  for (let attempt = 1; ; attempt += 1) {
    if (await ping(WAKE_ATTEMPT_TIMEOUT)) {
      publish({ phase: 'ready', attempts: attempt, error: null })
      return true
    }
    if (Date.now() >= deadline) {
      publish({
        phase: 'down',
        attempts: attempt,
        error: API_ORIGIN
          ? `No answer from ${API_ORIGIN} after ${Math.round(WAKE_GIVE_UP_AFTER / 1000)}s.`
          : 'No answer from the API. Is `psok serve` running?',
      })
      return false
    }
    publish({ attempts: attempt })
    await new Promise((done) => setTimeout(done, WAKE_GAP))
  }
}

/* DNS, TCP and TLS to the API host, started before the first request needs
   them. Only when the API is somewhere else -- a same-origin build is already
   connected to its own origin, and a preconnect to it would be a wasted hint. */
if (API_ORIGIN && typeof document !== 'undefined') {
  const hint = document.createElement('link')
  hint.rel = 'preconnect'
  hint.href = API_ORIGIN
  hint.crossOrigin = ''
  document.head.appendChild(hint)
}

/** Started here rather than from a component, so the container is already
 *  booting while React is still parsing. */
export const backendReady = wakeBackend()

async function j(url, opts) {
  let res
  try {
    res = await fetch(BASE + url, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    })
  } catch (err) {
    // `fetch` rejects with a bare "Failed to fetch" for a container that has
    // gone back to sleep, a CORS origin that was never allowed, and a laptop
    // with no wifi alike. The interface showed that string verbatim, which
    // named none of them. Say where it was trying to reach, and put the backend
    // back into waking so the boot frame comes up rather than a dead page.
    if (state.phase === 'ready') { publish({ phase: 'waking', since: Date.now(), attempts: 0 }) }
    const where = API_ORIGIN || window.location.origin
    throw new Error(`Could not reach ${where} — ${err.message || 'the request failed'}`)
  }
  if (state.phase !== 'ready') publish({ phase: 'ready', error: null })
  if (!res.ok) {
    // A 405 on a path this interface knows about means the endpoint is not in
    // the running server, which in practice means one thing: `psok serve` has
    // been up since before the bundle it is serving was built. "405: Method
    // Not Allowed" sends someone looking for a bug in their own request; this
    // says what to actually do about it.
    if (res.status === 405) {
      throw new Error(
        `This server does not have ${opts?.method || 'that'} ${url} — it is running an older`
        + ' build than the interface it is serving. Restart psok serve.',
      )
    }
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail || body.error || detail
    } catch { /* keep statusText */ }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

const json = (method, body) => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export const api = {
  // Cheap by design: it exists to be the request that wakes a stopped
  // container, so it must not do any work of its own.
  ping: () => j('/ping'),
  health: () => j('/health'),

  // Providers. `addProvider` is the only call that carries a key, and nothing
  // gives one back: the server stores it in the OS keychain and every response
  // reports whether a key exists, never what it is.
  providers: () => j('/providers'),
  addProvider: (body) => j('/providers', json('POST', body)),
  removeProvider: (name) => j(`/providers/${encodeURIComponent(name)}`, json('DELETE')),
  // A fresh liveness check the user asked for, cache ignored. `pingAll` is the
  // one-button version; both update the picker's badge from what came back.
  pingProvider: (name) => j(`/providers/${encodeURIComponent(name)}/ping`, json('POST')),
  pingAll: () => j('/providers/ping-all', json('POST')),
  // The models this provider's own API lists right now, so the menu offers what
  // the endpoint serves instead of asking the user to retype an id from docs.
  providerModels: (name) => j(`/providers/${encodeURIComponent(name)}/models`),

  // Tiers: which model does which job. `default` is the go-to model; `fast` is
  // the quick cheap one; `heavy` is what the fast model escalates to.
  settings: () => j('/settings'),
  updateSettings: (patch) => j('/settings', json('PATCH', patch)),

  tiers: () => j('/tiers'),
  setTier: (tier, provider, model) =>
    j(`/tiers/${encodeURIComponent(tier)}`, json('PUT', { provider, model })),
  clearTier: (tier) => j(`/tiers/${encodeURIComponent(tier)}`, json('DELETE')),

  conversations: () => j('/conversations'),
  createConversation: (provider, model, title) =>
    j('/conversations', json('POST', { provider, model, title })),
  updateConversation: (id, patch) => j(`/conversations/${id}`, json('PATCH', patch)),
  deleteConversation: (id) => j(`/conversations/${id}`, json('DELETE')),
  deleteAllConversations: () => j('/conversations', json('DELETE')),
  messages: (id) => j(`/conversations/${id}/messages`),
  pinMessage: (id, messageId, pinned) =>
    j(`/conversations/${id}/messages/${messageId}/pin`, json('POST', { pinned })),

  // `mode` is 'chat' or 'plan'. It is a field rather than a sentence glued to
  // the message: the sentence landed in the transcript and was replayed on
  // every later turn, and the server had no idea the mode existed.
  turn: async ({ conversationId, message, workspace, mode, onEvent, signal }) => {
    const res = await fetch(`${BASE}/conversations/${conversationId}/turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, workspace, mode: mode || 'chat' }),
      signal,
    })
    if (!res.ok || !res.body) {
      let detail = res.statusText
      try { detail = (await res.json()).detail || detail } catch { /* ignore */ }
      throw new Error(`${res.status}: ${detail}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let done = false
    while (!done) {
      const { value, done: streamDone } = await reader.read()
      done = streamDone
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      let idx
      while ((idx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, idx).trim()
        buffer = buffer.slice(idx + 1)
        if (!line.startsWith('data: ')) continue
        try {
          const evt = JSON.parse(line.slice(6))
          onEvent(evt)
        } catch { /* malformed frame, skip */ }
      }
    }
  },

  // Stops the turn on the server. Aborting the browser's read only closes the
  // response: the loop behind it keeps calling models and tools.
  stopTurn: (id) => j(`/conversations/${id}/turn/stop`, json('POST', {})),

  confirmations: () => j('/confirmations'),
  decideConfirmation: (id, { allow, remember }) =>
    j(`/confirmations/${id}`, json('POST', { allow, remember })),

  standingApprovals: () => j('/confirmations/preferences'),
  revokeApproval: (operationKey) =>
    j(`/confirmations/preferences/${encodeURIComponent(operationKey)}`, json('DELETE')),

  // Automations — beta. A turn that runs without anyone typing.
  automations: () => j('/automations'),
  createAutomation: (body) => j('/automations', json('POST', body)),
  updateAutomation: (id, patch) => j(`/automations/${id}`, json('PATCH', patch)),
  deleteAutomation: (id) => j(`/automations/${id}`, json('DELETE')),
  runAutomation: (id) => j(`/automations/${id}/run`, json('POST', {})),
  // Every kept run of one automation. They are out of the conversation rail,
  // so this is where they are read.
  automationRuns: (id) => j(`/automations/${id}/runs`),

  logs: (limit = 100) => j(`/logs?limit=${limit}`),

  memory: (conversationId) =>
    j(`/memory${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''}`),
  toggleMemory: (enabled, conversationId) =>
    j('/memory/toggle', json('POST', { enabled, conversation_id: conversationId || null })),
  forgetMemory: (id) => j(`/memory/${id}`, json('DELETE')),
  forgetAllMemories: () => j('/memory', json('DELETE')),

  skills: () => j('/skills'),
  skillCatalogue: (refresh = false) => j(`/skills/catalogue${refresh ? '?refresh=true' : ''}`),
  installSkill: (url, overwrite = false) => j('/skills/install', json('POST', { url, overwrite })),
  createSkill: ({ name, description, instruction, overwrite = false }) =>
    j('/skills/create', json('POST', { name, description, instruction, overwrite })),
  removeSkill: (name) => j(`/skills/${encodeURIComponent(name)}`, json('DELETE')),

  tools: () => j('/tools'),
  tasks: ({ bucket = 'all', listId = null, limit = 200 } = {}) =>
    j(listId
      ? `/tasks?list_id=${listId}&limit=${limit}`
      : `/tasks?bucket=${encodeURIComponent(bucket)}&limit=${limit}`),
  taskBuckets: () => j('/tasks/buckets'),
  taskLists: () => j('/task-lists'),
  createTaskList: (name) => j('/task-lists', json('POST', { name })),
  renameTaskList: (id, name) => j(`/task-lists/${id}`, json('PATCH', { name })),
  calendar: (days = 14) => j(`/calendar?days=${days}`),
  syncTasks: () => j('/tasks/sync', json('POST')),

  // Mail. Straight from Gmail rather than through the connector -- the
  // connector answers in prose written for a model, see backend/mail/gmail.py.
  mailAccount: () => j('/mail/account'),
  mailThreads: ({ q = 'in:inbox', limit = 25 } = {}) =>
    j(`/mail/threads?q=${encodeURIComponent(q)}&limit=${limit}`),
  mailThread: (id) => j(`/mail/threads/${encodeURIComponent(id)}`),
  mailReply: (id, body) => j(`/mail/threads/${encodeURIComponent(id)}/reply`, json('POST', { body })),
  mailLabels: () => j('/mail/labels'),
  mailModifyLabels: (messageId, patch) =>
    j(`/mail/messages/${encodeURIComponent(messageId)}/labels`, json('POST', patch)),
  createTask: (body) => j('/tasks', json('POST', body)),
  updateTask: (id, patch) => j(`/tasks/${id}`, json('PATCH', patch)),
  deleteTask: (id) => j(`/tasks/${id}`, json('DELETE')),

  // A browser cannot hand the agent a path, so the file is uploaded first and
  // the message carries where it landed.
  upload: async (file) => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(`${BASE}/attachments`, { method: 'POST', body: form })
    if (!res.ok) {
      let detail = res.statusText
      try { detail = (await res.json()).detail || detail } catch { /* keep statusText */ }
      throw new Error(`${res.status}: ${detail}`)
    }
    return res.json()
  },
  skillSearch: (q, conversationId) =>
    j(`/skills/search?q=${encodeURIComponent(q)}${conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ''}`),

  capabilities: (conversationId) =>
    j(`/capabilities${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''}`),
  toggleCapability: (kind, name, enabled, conversationId) =>
    j(`/capabilities/${kind}/${encodeURIComponent(name)}`, json('POST', { enabled, conversation_id: conversationId || null })),
  resetCapability: (kind, name, conversationId) =>
    j(`/capabilities/${kind}/${encodeURIComponent(name)}?${conversationId ? `conversation_id=${encodeURIComponent(conversationId)}` : ''}`, json('DELETE')),

  capabilityProfiles: () => j('/capabilities/profiles'),
  saveCapabilityProfile: (name, conversationId) =>
    j('/capabilities/profiles', json('POST', { name, conversation_id: conversationId || null })),
  applyCapabilityProfile: (name, conversationId) =>
    j(`/capabilities/profiles/${encodeURIComponent(name)}/apply`, json('POST', { conversation_id: conversationId })),
  deleteCapabilityProfile: (name) =>
    j(`/capabilities/profiles/${encodeURIComponent(name)}`, json('DELETE')),

  mcpCatalogue: () => j('/mcp/catalogue'),
  // `accounts` asks each connector who it is signed in as, which can cost a
  // network round trip — so the 3s poll never asks, and the detail panel does.
  mcpServers: (accounts = false) => j(`/mcp/servers${accounts ? '?accounts=true' : ''}`),
  mcpAdd: (body) => j('/mcp/servers', json('POST', body)),
  mcpRemove: (name) => j(`/mcp/servers/${encodeURIComponent(name)}`, json('DELETE')),
  mcpOauthClient: (name, body) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/oauth-client`, json('POST', body)),
  mcpSetEnv: (name, body) => j(`/mcp/servers/${encodeURIComponent(name)}/env`, json('POST', body)),
  mcpUnsetEnv: (name, key) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/env/${encodeURIComponent(key)}`, json('DELETE')),
  // `force` signs out first, so the provider shows its account chooser rather
  // than silently handing back the session it already has.
  mcpLogin: (name, { force = false, accountHint = null } = {}) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/login`,
      json('POST', { force, account_hint: accountHint })),
  mcpCancelLogin: (name) => j(`/mcp/servers/${encodeURIComponent(name)}/login`, json('DELETE')),
  mcpLogout: (name) => j(`/mcp/servers/${encodeURIComponent(name)}/logout`, json('POST', {})),
  mcpAuthorizations: () => j('/mcp/authorizations'),
  // Start every switched-on connector now, the way the first turn would.
  mcpReconcile: () => j('/mcp/reconcile', json('POST', {})),
  mcpConnect: (name) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/connect`, json('POST', {})),

  // One read for the whole Today page: the day's events, what is owed, what is
  // unread, what was logged, and this morning's briefing. `degraded` names any
  // section that could not be read, so the page says so instead of showing a
  // zero nobody measured.
  today: () => j('/today'),

  journal: (kind) => j(`/journal${kind ? `?kind=${encodeURIComponent(kind)}` : ''}`),
  journalEntry: (id) => j(`/journal/${id}`),
  // `force` rewrites an entry that already exists — the Regenerate button.
  generateJournal: (kind, { date = null, force = false } = {}) =>
    j(`/journal/${encodeURIComponent(kind)}/generate?force=${force ? 'true' : 'false'}`
      + (date ? `&entry_date=${encodeURIComponent(date)}` : ''), json('POST')),
  // The check-in answers. Stored before the model runs, so a provider that
  // fails costs the write-up and never what was typed.
  answerJournal: (id, userNotes) => j(`/journal/${id}`, json('PATCH', { user_notes: userNotes })),
  deleteJournal: (id) => j(`/journal/${id}`, json('DELETE')),

  // With `q`, a hybrid search over captured text; without it, the most recent
  // items. Both come back as items rather than passages.
  library: ({ q = '', kind = '', limit = 50 } = {}) =>
    j(`/library?limit=${limit}`
      + (q ? `&q=${encodeURIComponent(q)}` : '')
      + (kind ? `&kind=${encodeURIComponent(kind)}` : '')),
  addLibraryItem: (body) => j('/library', json('POST', body)),
  updateLibraryItem: (id, patch) => j(`/library/${id}`, json('PATCH', patch)),
  deleteLibraryItem: (id) => j(`/library/${id}`, json('DELETE')),
  // Clears the process-wide "that embedder refused" cache first, so starting
  // Ollama and pressing this is enough — no restart.
  reindexLibraryItem: (id) => j(`/library/${id}/reindex`, json('POST')),

  // Voice, values, palette, fonts. The response carries `prompt_block`: the
  // literal text the model will be handed, so the effect is visible.
  brand: () => j('/brand'),
  saveBrand: (body) => j('/brand', json('PUT', body)),

  // Enrichment is the mirror of reindex: "add a provider and press this".
  enrichLibraryItem: (id) => j(`/library/${id}/enrich`, json('POST')),
  // A route rather than a path: the browser is never handed a filesystem
  // location, and a missing still is a 404 rather than a broken <img>.
  thumbnailUrl: (id) => `${BASE}/library/${id}/thumbnail`,

  // Instagram capture. Credentials go one way only — set and delete; the status
  // reports whether each is present, never what it is.
  instagram: () => j('/instagram'),
  saveInstagramCredentials: (body) => j('/instagram/credentials', json('PUT', body)),
  clearInstagramCredentials: () => j('/instagram/credentials', json('DELETE')),
  updateInstagram: (patch) => j('/instagram/settings', json('PATCH', patch)),
  allowInstagramSender: (id) => j(`/instagram/senders/${encodeURIComponent(id)}`, json('POST')),
  denyInstagramSender: (id) => j(`/instagram/senders/${encodeURIComponent(id)}`, json('DELETE')),
  instagramEvents: () => j('/instagram/events'),
  retryInstagramEvent: (id) => j(`/instagram/events/${id}/retry`, json('POST')),

  // Sharing is off until a token exists. The token comes back exactly once,
  // from `rotateShareToken`, and nothing reads it out of the keychain again.
  shareStatus: () => j('/share'),
  rotateShareToken: () => j('/share/token', json('POST')),
  revokeShareToken: () => j('/share/token', json('DELETE')),
}

/** Parse a timestamp the *server* wrote, which is UTC and does not say so.
 *
 *  Every `created_at` and `updated_at` in this schema comes from SQLite's
 *  `datetime('now')`, which is UTC and has no offset on it. JavaScript reads a
 *  bare `YYYY-MM-DD HH:MM:SS` as *local*, so a conversation from a minute ago
 *  showed up hours old -- five and a half of them on the machine this was found
 *  on, and never on the machine of anyone in London, which is why it survived.
 *  A value that already carries an offset is left alone.
 *
 *  This is only for those columns. Task dates -- `due_at`, `reminder_at`,
 *  `scheduled_at`, `completed_at` -- are written with `datetime.now()` and are
 *  genuinely local; putting them through here would break them the other way.
 */
export function serverTime(value) {
  if (!value) return null
  const text = String(value).trim()
  const bare = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?$/.test(text)
  const d = new Date(bare ? `${text.replace(' ', 'T')}Z` : text)
  return Number.isNaN(d.getTime()) ? null : d
}

export function fmtTime(iso) {
  const d = serverTime(iso)
  if (!d) return iso || ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtDate(iso) {
  const d = serverTime(iso)
  if (!d) return iso || ''
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

export function prettyJSON(value) {
  try {
    return JSON.stringify(typeof value === 'string' ? JSON.parse(value) : value, null, 2)
  } catch {
    return typeof value === 'string' ? value : JSON.stringify(value)
  }
}

/** Copy text, falling back when the Clipboard API is unavailable.
 *
 *  `navigator.clipboard` exists only in a secure context. Loopback counts, but
 *  the moment someone serves this to another machine over plain http it is
 *  gone -- and a copy button that silently does nothing is worse than one that
 *  says it failed. Resolves to whether the text actually made it.
 */
export async function copyText(text) {
  if (!text) return false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* denied, or no permission: fall through to the old mechanism */
  }
  try {
    const holder = document.createElement('textarea')
    holder.value = text
    holder.setAttribute('readonly', '')
    holder.style.cssText = 'position:fixed;top:-1000px;opacity:0'
    document.body.appendChild(holder)
    holder.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(holder)
    return ok
  } catch {
    return false
  }
}
