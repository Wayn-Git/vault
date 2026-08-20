const BASE = '/api'

async function j(url, opts) {
  const res = await fetch(BASE + url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
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
  messages: (id) => j(`/conversations/${id}/messages`),

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

  confirmations: () => j('/confirmations'),
  decideConfirmation: (id, { allow, remember }) =>
    j(`/confirmations/${id}`, json('POST', { allow, remember })),

  logs: (limit = 100) => j(`/logs?limit=${limit}`),

  skills: () => j('/skills'),
  skillSearch: (q, conversationId) =>
    j(`/skills/search?q=${encodeURIComponent(q)}${conversationId ? `&conversation_id=${encodeURIComponent(conversationId)}` : ''}`),

  capabilities: (conversationId) =>
    j(`/capabilities${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''}`),
  toggleCapability: (kind, name, enabled, conversationId) =>
    j(`/capabilities/${kind}/${encodeURIComponent(name)}`, json('POST', { enabled, conversation_id: conversationId || null })),
  resetCapability: (kind, name, conversationId) =>
    j(`/capabilities/${kind}/${encodeURIComponent(name)}?${conversationId ? `conversation_id=${encodeURIComponent(conversationId)}` : ''}`, json('DELETE')),

  mcpCatalogue: () => j('/mcp/catalogue'),
  mcpServers: () => j('/mcp/servers'),
  mcpAdd: (body) => j('/mcp/servers', json('POST', body)),
  mcpRemove: (name) => j(`/mcp/servers/${encodeURIComponent(name)}`, json('DELETE')),
  mcpOauthClient: (name, body) =>
    j(`/mcp/servers/${encodeURIComponent(name)}/oauth-client`, json('POST', body)),
  mcpLogin: (name) => j(`/mcp/servers/${encodeURIComponent(name)}/login`, json('POST', {})),
  mcpAuthorizations: () => j('/mcp/authorizations'),
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