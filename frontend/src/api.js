const BASE = '/api'

async function j(url, opts) {
  const res = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
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
  health: () => j('/health'),

  conversations: () => j('/conversations'),
  createConversation: (provider, model, title) =>
    j('/conversations', json('POST', { provider, model, title })),
  updateConversation: (id, patch) => j(`/conversations/${id}`, json('PATCH', patch)),
  deleteConversation: (id) => j(`/conversations/${id}`, json('DELETE')),
  messages: (id) => j(`/conversations/${id}/messages`),
  pinMessage: (id, messageId, pinned) =>
    j(`/conversations/${id}/messages/${messageId}/pin`, json('POST', { pinned })),

  turn: async ({ conversationId, message, workspace, onEvent, signal }) => {
    const res = await fetch(`${BASE}/conversations/${conversationId}/turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, workspace }),
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

  skills: () => j('/skills'),
  skillCatalogue: (refresh = false) => j(`/skills/catalogue${refresh ? '?refresh=true' : ''}`),
  installSkill: (url, overwrite = false) => j('/skills/install', json('POST', { url, overwrite })),
  createSkill: ({ name, description, instruction, overwrite = false }) =>
    j('/skills/create', json('POST', { name, description, instruction, overwrite })),
  removeSkill: (name) => j(`/skills/${encodeURIComponent(name)}`, json('DELETE')),

  tools: () => j('/tools'),
  tasks: (includeDone = false) => j(`/tasks?include_done=${includeDone ? 'true' : 'false'}`),
  calendar: (days = 14) => j(`/calendar?days=${days}`),

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
  mcpLogout: (name) => j(`/mcp/servers/${encodeURIComponent(name)}/logout`, json('POST', {})),
  mcpAuthorizations: () => j('/mcp/authorizations'),
  // Start every switched-on connector now, the way the first turn would.
  mcpReconcile: () => j('/mcp/reconcile', json('POST', {})),
  mcpConnect: (name) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/connect`, json('POST', {})),
}

export function fmtTime(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso || ''
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function fmtDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso || ''
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
