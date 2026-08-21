import { memo, useCallback, useState } from 'react'
import Icon from './Icon.jsx'
import { copyText } from '../api.js'

/* Markdown for model output, rendered to React elements rather than HTML.

   Nothing here ever reaches `dangerouslySetInnerHTML`, so a model that emits a
   `<script>` tag or an `onerror=` attribute produces visible text and not an
   execution. That property is why this is hand-written rather than a parser
   plus a sanitiser: there is no HTML in the pipeline to sanitise.

   It also has to survive a half-finished document. Text arrives token by token,
   so an unterminated code fence, a table with one row written, and a link whose
   closing bracket has not arrived yet are all normal intermediate states, not
   errors. Every block parser closes itself at end of input. */

const SAFE_PROTOCOL = /^(https?:|mailto:)/i

function Anchor({ href, children }) {
  if (!SAFE_PROTOCOL.test(href || '')) return <>{children}</>
  return (
    <a href={href} target="_blank" rel="noreferrer noopener nofollow" className="md-link">
      {children}
    </a>
  )
}

/* Inline spans. One pass, longest-match-first, so `**a**` never resolves as two
   emphasis runs. */
const INLINE = [
  { re: /^`([^`]+)`/, node: (m, k) => <code key={k} className="md-code">{m[1]}</code> },
  { re: /^\*\*([^*]+)\*\*/, node: (m, k, walk) => <strong key={k}>{walk(m[1])}</strong> },
  { re: /^__([^_]+)__/, node: (m, k, walk) => <strong key={k}>{walk(m[1])}</strong> },
  { re: /^~~([^~]+)~~/, node: (m, k, walk) => <s key={k}>{walk(m[1])}</s> },
  { re: /^\*([^*\n]+)\*/, node: (m, k, walk) => <em key={k}>{walk(m[1])}</em> },
  { re: /^_([^_\n]+)_/, node: (m, k, walk) => <em key={k}>{walk(m[1])}</em> },
  {
    re: /^\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/,
    node: (m, k, walk) => <Anchor key={k} href={m[2]}>{walk(m[1]) }</Anchor>,
  },
  {
    re: /^<(https?:\/\/[^>\s]+)>/,
    node: (m, k) => <Anchor key={k} href={m[1]}>{m[1]}</Anchor>,
  },
  {
    re: /^(https?:\/\/[^\s<>()[\]]+)/,
    node: (m, k) => <Anchor key={k} href={m[1]}>{m[1]}</Anchor>,
  },
]

function inline(src) {
  const out = []
  let buf = ''
  let rest = src ?? ''
  let key = 0
  const flush = () => {
    if (buf) { out.push(buf); buf = '' }
  }
  while (rest) {
    let hit = null
    for (const rule of INLINE) {
      const m = rule.re.exec(rest)
      if (m) { hit = { rule, m }; break }
    }
    if (hit) {
      flush()
      out.push(hit.rule.node(hit.m, `i${key++}`, inline))
      rest = rest.slice(hit.m[0].length)
      continue
    }
    if (rest[0] === '\n') {
      flush()
      out.push(<br key={`b${key++}`} />)
      rest = rest.slice(1)
      continue
    }
    buf += rest[0]
    rest = rest.slice(1)
  }
  flush()
  return out
}

function CodeBlock({ lang, text, open }) {
  const [copied, setCopied] = useState(false)
  const copy = useCallback(async () => {
    setCopied(await copyText(text) ? 'copied' : 'blocked')
    setTimeout(() => setCopied(false), 1600)
  }, [text])

  return (
    <div className="md-pre-wrap">
      <div className="md-pre-head">
        <span className="md-pre-lang">{lang || 'text'}{open ? ' · writing' : ''}</span>
        <button type="button" className="md-copy" onClick={copy} title="Copy this block">
          <Icon name={copied === 'copied' ? 'check' : copied === 'blocked' ? 'x' : 'copy'} size={12} />
          {copied || 'copy'}
        </button>
      </div>
      <pre className="md-pre"><code>{text}</code></pre>
    </div>
  )
}

const BULLET = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/
const HEADING = /^(#{1,6})\s+(.*)$/
const QUOTE = /^>\s?(.*)$/
const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+-]*)\s*$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const TABLE_SEP = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$/

const cells = (row) =>
  row.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim())

/** One indentation level of list items, consumed recursively. */
function readList(lines, start, indent) {
  const items = []
  const first = BULLET.exec(lines[start])
  const ordered = /\d/.test(first[2])
  let i = start
  while (i < lines.length) {
    const m = BULLET.exec(lines[i])
    if (!m || m[1].length < indent) break
    if (m[1].length > indent) {
      const [nested, next] = readList(lines, i, m[1].length)
      if (items.length) items[items.length - 1].children.push(nested)
      i = next
      continue
    }
    if (/\d/.test(m[2]) !== ordered) break
    const item = { text: m[3], children: [] }
    i += 1
    // A wrapped line belongs to the item it follows.
    while (i < lines.length && lines[i].trim() && !BULLET.test(lines[i]) && !HEADING.test(lines[i]) && !FENCE.test(lines[i])) {
      item.text += `\n${lines[i].trim()}`
      i += 1
    }
    items.push(item)
  }
  return [{ type: ordered ? 'ol' : 'ul', items }, i]
}

function parse(src) {
  const lines = (src ?? '').split('\n')
  const blocks = []
  let i = 0
  let para = []

  const flushPara = () => {
    if (para.length) {
      blocks.push({ type: 'p', text: para.join('\n') })
      para = []
    }
  }

  while (i < lines.length) {
    const line = lines[i]
    const fence = FENCE.exec(line)
    if (fence) {
      flushPara()
      const marker = fence[1][0]
      const body = []
      i += 1
      let closed = false
      while (i < lines.length) {
        const end = FENCE.exec(lines[i])
        if (end && end[1][0] === marker) { closed = true; i += 1; break }
        body.push(lines[i])
        i += 1
      }
      blocks.push({ type: 'code', lang: fence[2], text: body.join('\n'), open: !closed })
      continue
    }
    if (!line.trim()) { flushPara(); i += 1; continue }
    const heading = HEADING.exec(line)
    if (heading) {
      flushPara()
      blocks.push({ type: 'h', level: heading[1].length, text: heading[2] })
      i += 1
      continue
    }
    if (RULE.test(line)) { flushPara(); blocks.push({ type: 'hr' }); i += 1; continue }
    if (QUOTE.test(line)) {
      flushPara()
      const body = []
      while (i < lines.length && QUOTE.test(lines[i])) {
        body.push(QUOTE.exec(lines[i])[1])
        i += 1
      }
      blocks.push({ type: 'quote', text: body.join('\n') })
      continue
    }
    if (BULLET.test(line)) {
      flushPara()
      const [list, next] = readList(lines, i, BULLET.exec(line)[1].length)
      blocks.push(list)
      i = next
      continue
    }
    if (line.includes('|') && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      flushPara()
      const head = cells(line)
      const rows = []
      i += 2
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(cells(lines[i]))
        i += 1
      }
      blocks.push({ type: 'table', head, rows })
      continue
    }
    para.push(line)
    i += 1
  }
  flushPara()
  return blocks
}

function List({ block, keyBase }) {
  const Tag = block.type === 'ol' ? 'ol' : 'ul'
  return (
    <Tag className="md-list">
      {block.items.map((item, n) => (
        <li key={`${keyBase}-${n}`}>
          {inline(item.text)}
          {item.children.map((child, c) => (
            <List key={`${keyBase}-${n}-${c}`} block={child} keyBase={`${keyBase}-${n}-${c}`} />
          ))}
        </li>
      ))}
    </Tag>
  )
}

function render(blocks) {
  return blocks.map((block, n) => {
    const key = `b${n}`
    switch (block.type) {
      case 'code':
        return <CodeBlock key={key} lang={block.lang} text={block.text} open={block.open} />
      case 'h': {
        const Tag = `h${Math.min(block.level + 2, 6)}`
        return <Tag key={key} className="md-h">{inline(block.text)}</Tag>
      }
      case 'hr':
        return <hr key={key} className="md-hr" />
      case 'quote':
        return <blockquote key={key} className="md-quote">{inline(block.text)}</blockquote>
      case 'ul':
      case 'ol':
        return <List key={key} block={block} keyBase={key} />
      case 'table':
        return (
          <div key={key} className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>{block.head.map((c, x) => <th key={x}>{inline(c)}</th>)}</tr>
              </thead>
              <tbody>
                {block.rows.map((row, y) => (
                  <tr key={y}>{row.map((c, x) => <td key={x}>{inline(c)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      default:
        return <p key={key} className="md-p">{inline(block.text)}</p>
    }
  })
}

function Markdown({ text }) {
  return <div className="md">{render(parse(text))}</div>
}

export default memo(Markdown)
