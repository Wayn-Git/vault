import { memo, useCallback, useEffect, useState } from 'react'
import Icon from '../Icon.jsx'
import { copyText } from '../../api.js'
import { parseBlocks, parseInline, SAFE_PROTOCOL } from './parse.js'
import { grammarFor, loadGrammar, tokenize } from './highlight.js'

/* Model output, rendered to React elements rather than HTML.
 *
 * Nothing here reaches `dangerouslySetInnerHTML`, so a model that emits a
 * `<script>` tag or an `onerror=` attribute produces visible text and not an
 * execution. The syntax highlighter is held to the same rule — `highlight.js`
 * returns a token tree for this file to build spans from, never markup.
 *
 * The parsing lives in `parse.js`, which has no React in it and is asserted
 * against by `tests/markdown.mjs`. This file is the mapping and nothing else.
 */

/* ---------------------------------------------------------------- inline */

/* An image in model output is a URL the page would fetch on sight.
 *
 * Rendering it announces the reader's address to whichever host the model
 * named, on every message, before anyone has decided to trust it — and a 1×1
 * at an attacker's domain is the cheapest read receipt there is. So the alt
 * text and the destination are offered, and following one is a decision. */
function ImageRef({ alt, href }) {
  const label = alt || 'image'
  if (!SAFE_PROTOCOL.test(href || '')) return <span className="md-image">{label}</span>
  return (
    <a href={href} target="_blank" rel="noreferrer noopener nofollow" className="md-image" title={href}>
      <Icon name="image" size={12} />
      {label}
    </a>
  )
}

function inline(nodes, keyBase = 'i') {
  return nodes.map((node, n) => {
    const key = `${keyBase}${n}`
    switch (node.type) {
      case 'text': return node.value
      case 'br': return <br key={key} />
      case 'code': return <code key={key} className="md-code">{node.value}</code>
      case 'strong': return <strong key={key}>{inline(node.children, `${key}-`)}</strong>
      case 'em': return <em key={key}>{inline(node.children, `${key}-`)}</em>
      case 'del': return <s key={key}>{inline(node.children, `${key}-`)}</s>
      case 'image': return <ImageRef key={key} alt={node.alt} href={node.href} />
      case 'link':
        // An unsupported scheme keeps its text and loses its link: `javascript:`
        // and `data:` are the two that matter, and neither should be one click
        // from a transcript the user did not write.
        if (!SAFE_PROTOCOL.test(node.href || '')) return <span key={key}>{inline(node.children, `${key}-`)}</span>
        return (
          <a key={key} href={node.href} target="_blank" rel="noreferrer noopener nofollow" className="md-link">
            {inline(node.children, `${key}-`)}
          </a>
        )
      default: return null
    }
  })
}

const text = (src) => inline(parseInline(src))

/* The tail of a path, for a header that is one line tall.
 *
 * The first attempt did this with `direction: rtl` and `text-overflow`, which
 * elides from the correct end and then silently reorders the string: a slash
 * is a neutral character, so `/home/wayne/app.py` rendered as
 * `home/wayne/app.py/`. Absolute paths are exactly what a model writes when it
 * is showing you a file. Trimming the segments is unambiguous, and the whole
 * path stays in the tooltip. */
function shortPath(path, keep = 2) {
  const parts = String(path).split('/').filter(Boolean)
  if (parts.length <= keep) return path
  return `…/${parts.slice(-keep).join('/')}`
}

/* ------------------------------------------------------------ code blocks */

/* hast -> React. `refractor` hands back element and text nodes only, with
   nothing on them but a class list, so this is the whole mapping. */
function spans(nodes, keyBase = 't') {
  return nodes.map((node, i) => {
    if (node.type === 'text') return node.value
    const cls = node.properties?.className
    return (
      <span key={`${keyBase}${i}`} className={Array.isArray(cls) ? cls.join(' ') : cls}>
        {spans(node.children || [], `${keyBase}${i}-`)}
      </span>
    )
  })
}

/* A fenced block, with the two controls a reader of model output reaches for.
 *
 * Highlighting waits for the closing fence. Re-tokenising a growing buffer on
 * every streamed delta is work thrown away sixty times a second, and a token
 * that is half-written highlights as the wrong thing and then changes colour
 * when the rest of it arrives — which reads worse than plain text for the
 * second it takes. */
function CodeBlock({ lang, file, text: code, open }) {
  const [copied, setCopied] = useState(false)
  const [wrap, setWrap] = useState(false)
  const [tokens, setTokens] = useState(null)
  const grammar = grammarFor(lang || file)

  /* The `current` flag is the whole cancellation story, and deliberately so.
     There was a second `alive` ref here guarding against a resolve after
     unmount, and under StrictMode — which mounts, cleans up, and mounts again
     — its cleanup set it false on the first pass and nothing ever set it back.
     Every code block in the application stayed unhighlighted, in development
     and in any future remount. This effect's own cleanup already runs on
     unmount, so the ref was guarding something that was covered. */
  useEffect(() => {
    if (open || !grammar) { setTokens(null); return undefined }
    let current = true
    loadGrammar(grammar).then((refractor) => {
      if (current) setTokens(tokenize(refractor, code, grammar))
    })
    return () => { current = false }
  }, [grammar, code, open])

  const copy = useCallback(async () => {
    setCopied(await copyText(code) ? 'copied' : 'blocked')
    setTimeout(() => setCopied(false), 1600)
  }, [code])

  return (
    <div className="md-pre-wrap">
      <div className="md-pre-head">
        {/* The filename when the model gave one, the language otherwise, and
            nothing at all when it gave neither — rather than the word "text",
            which was a label for the absence of a label. */}
        {file && <span className="md-pre-file" title={file}>{shortPath(file)}</span>}
        {(lang || file) && <span className="md-pre-lang">{lang || 'text'}</span>}
        {open && (
          <span className="md-pre-live">
            writing<span className="ellipsis"><i /><i /><i /></span>
          </span>
        )}
        <div className="md-pre-actions">
          {/* Long lines scroll by default, because a shell command broken over
              three lines is no longer the command. Wrapping is offered because
              sometimes you want all of it at once. */}
          <button
            type="button"
            className={`md-pre-btn${wrap ? ' is-on' : ''}`}
            onClick={() => setWrap((w) => !w)}
            title={wrap ? 'Stop wrapping long lines' : 'Wrap long lines'}
            aria-pressed={wrap}
            aria-label="Wrap long lines"
          >
            <Icon name="wrap" size={13} />
          </button>
          <button
            type="button"
            className="md-pre-btn"
            onClick={copy}
            title="Copy this block"
            aria-label={copied === 'copied' ? 'Copied' : 'Copy this block'}
          >
            <Icon
              name={copied === 'copied' ? 'check' : copied === 'blocked' ? 'x' : 'copy'}
              size={13}
            />
          </button>
        </div>
      </div>
      <pre className={`md-pre${wrap ? ' md-pre--wrap' : ''}`}>
        <code>{tokens ? spans(tokens) : code}</code>
      </pre>
    </div>
  )
}

/* ---------------------------------------------------------------- blocks */

/* Which mark and which of the three semantic colours each admonition takes.
   `caution` and `warning` are the same shape of thing and share the mark; the
   labels differ because the model chose between them. */
const CALLOUTS = {
  note: { icon: 'info', label: 'Note' },
  tip: { icon: 'spark', label: 'Tip' },
  important: { icon: 'info', label: 'Important' },
  warning: { icon: 'alert', label: 'Warning' },
  caution: { icon: 'alert', label: 'Caution' },
}

function List({ block, keyBase }) {
  const Tag = block.type === 'ol' ? 'ol' : 'ul'
  return (
    <Tag className={`md-list${block.tasks ? ' md-list--tasks' : ''}`}>
      {block.items.map((item, n) => {
        const key = `${keyBase}-${n}`
        const task = item.done !== undefined
        return (
          <li key={key} className={task ? `md-task${item.done ? ' is-done' : ''}` : undefined}>
            {/* A real mark rather than the two characters the model typed.
                Not a checkbox input: nothing in a transcript is settable, and
                a control that looks operable and is not is worse than a
                picture of one. */}
            {task && (
              <span className="md-task-box" aria-hidden="true">
                {item.done && <Icon name="check" size={11} weight="bold" />}
              </span>
            )}
            <span className={task ? 'md-task-text' : undefined}>
              {text(item.text)}
              {item.children.map((child, c) => (
                <List key={`${key}-${c}`} block={child} keyBase={`${key}-${c}`} />
              ))}
            </span>
          </li>
        )
      })}
    </Tag>
  )
}

function block(node, key) {
  switch (node.type) {
    case 'code':
      return <CodeBlock key={key} lang={node.lang} file={node.file} text={node.text} open={node.open} />

    case 'h': {
      // Shifted down two levels: the page already owns its `h1`, and a reply
      // that opens with `#` must not become a second one.
      const Tag = `h${Math.min(node.level + 2, 6)}`
      return <Tag key={key} className="md-h">{text(node.text)}</Tag>
    }

    case 'hr':
      return <hr key={key} className="md-hr" />

    case 'callout': {
      const kind = CALLOUTS[node.kind]
      return (
        <div key={key} className={`md-callout md-callout--${node.kind}`}>
          <p className="md-callout-head">
            <Icon name={kind.icon} size={14} weight="fill" />
            {kind.label}
          </p>
          <div className="md-callout-body">{text(node.text)}</div>
        </div>
      )
    }

    case 'quote':
      return <blockquote key={key} className="md-quote">{text(node.text)}</blockquote>

    case 'ul':
    case 'ol':
      return <List key={key} block={node} keyBase={key} />

    case 'table':
      return (
        <div key={key} className="md-table-wrap" tabIndex={0} role="region" aria-label="Table">
          <table className="md-table">
            <thead>
              <tr>{node.head.map((c, x) => <th key={x} scope="col">{text(c)}</th>)}</tr>
            </thead>
            <tbody>
              {node.rows.map((row, y) => (
                <tr key={y}>{row.map((c, x) => <td key={x}>{text(c)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )

    default:
      return <p key={key} className="md-p">{text(node.text)}</p>
  }
}

function Markdown({ text: src }) {
  return <div className="md">{parseBlocks(src).map((node, n) => block(node, `b${n}`))}</div>
}

export default memo(Markdown)
