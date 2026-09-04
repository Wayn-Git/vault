/* What the markdown parser has to get right about model output.
 *
 * Every case below is something a model on this machine actually wrote and
 * this parser rendered wrongly, or something adjacent enough to break the same
 * way. It runs under plain `node` — `src/components/markdown/parse.js` has no
 * React in it precisely so that this file can exist:
 *
 *     npm run test:markdown
 *
 * The renderer on top of it is covered by `smoke.mjs`, which needs a browser
 * and a backend. This needs neither, so there is no excuse for a parser change
 * to go untested.
 */

import { strict as assert } from 'node:assert'
import { parseBlocks, parseInline, readInfo, SAFE_PROTOCOL } from '../src/components/markdown/parse.js'

let passed = 0
const failures = []

function test(name, fn) {
  try {
    fn()
    passed += 1
  } catch (err) {
    failures.push({ name, message: err.message })
  }
}

/** Flatten an inline tree back to the characters a reader would see. */
function flatten(nodes) {
  return nodes.map((n) => {
    if (n.type === 'text') return n.value
    if (n.type === 'code') return n.value
    if (n.type === 'br') return '\n'
    if (n.type === 'image') return n.alt
    return flatten(n.children || [])
  }).join('')
}

const types = (nodes) => nodes.map((n) => n.type)

/* -------------------------------------------------- fences and info strings

   The bug: the info string was `[\w+-]*` anchored to end of line, so a fence
   naming its file was not a fence. Its body was parsed as prose and its
   closing fence opened a second block that ate the rest of the message. */

test('a bare fence is a code block', () => {
  const [b] = parseBlocks('```\nx = 1\n```')
  assert.equal(b.type, 'code')
  assert.equal(b.text, 'x = 1')
  assert.equal(b.open, false)
})

test('a fence with a language keeps it', () => {
  const [b] = parseBlocks('```python\nx = 1\n```')
  assert.equal(b.lang, 'python')
  assert.equal(b.file, '')
})

test('a fence naming a file after the language is still a fence', () => {
  const [b] = parseBlocks('```python backend/runtime/http.py\nx = 1\n```')
  assert.equal(b.type, 'code')
  assert.equal(b.lang, 'python')
  assert.equal(b.file, 'backend/runtime/http.py')
  assert.equal(b.text, 'x = 1')
})

test('a fence using lang:path is still a fence', () => {
  const [b] = parseBlocks('```js:src/api.js\nx\n```')
  assert.equal(b.lang, 'js')
  assert.equal(b.file, 'src/api.js')
})

test('a fence naming only a file has no language', () => {
  assert.deepEqual(readInfo('app.py'), { lang: '', file: 'app.py' })
})

test('a braced info string is unwrapped', () => {
  assert.deepEqual(readInfo('{python}'), { lang: 'python', file: '' })
})

test('the block after a named fence is not swallowed', () => {
  // The original failure, in miniature: one filename turned everything after
  // the block into the inside of another block.
  const blocks = parseBlocks(
    '```python app.py\ncode\n```\n\nAfter the block.\n\n| a | b |\n| - | - |\n| 1 | 2 |',
  )
  assert.deepEqual(blocks.map((b) => b.type), ['code', 'p', 'table'])
  assert.equal(blocks[1].text, 'After the block.')
})

test('an unterminated fence is open, not lost', () => {
  const [b] = parseBlocks('```ts\nexport function parse(')
  assert.equal(b.open, true)
  assert.equal(b.text, 'export function parse(')
})

test('a closing fence must be at least as long as the opener', () => {
  const [b] = parseBlocks('````\n```\nstill inside\n````')
  assert.equal(b.text, '```\nstill inside')
})

test('a line with an info string does not close a block', () => {
  const [b] = parseBlocks('```\na\n``` js\nb\n```')
  assert.equal(b.text, 'a\n``` js\nb')
})

test('a tilde fence is not closed by backticks', () => {
  const [b] = parseBlocks('~~~\n```\n~~~')
  assert.equal(b.text, '```')
})

test('an inline code span at the start of a line does not open a fence', () => {
  const [b] = parseBlocks('```js` is how you label one')
  assert.equal(b.type, 'p')
})

/* --------------------------------------------------------------- emphasis

   The bug: `_` matched inside words, so every snake_case identifier in prose
   came apart. And `*` had no flanking rule, so arithmetic became italics. */

test('underscores inside an identifier are not emphasis', () => {
  const nodes = parseInline('tests/test_runtime_and_agent.py')
  assert.deepEqual(types(nodes), ['text'])
  assert.equal(flatten(nodes), 'tests/test_runtime_and_agent.py')
})

test('a bare snake_case word survives', () => {
  assert.equal(flatten(parseInline('max_tool_calls')), 'max_tool_calls')
})

test('underscore emphasis still works between words', () => {
  const nodes = parseInline('a _real_ emphasis')
  assert.deepEqual(types(nodes), ['text', 'em', 'text'])
})

test('spaced asterisks are multiplication, not emphasis', () => {
  const nodes = parseInline('Math.min(2 ** n * 250, 8_000)')
  assert.deepEqual(types(nodes), ['text'])
  assert.equal(flatten(nodes), 'Math.min(2 ** n * 250, 8_000)')
})

test('asterisk emphasis still works when it is emphasis', () => {
  assert.deepEqual(types(parseInline('*yes*')), ['em'])
  assert.deepEqual(types(parseInline('**bold**')), ['strong'])
})

test('emphasis does not open against whitespace', () => {
  assert.deepEqual(types(parseInline('a * b * c')), ['text'])
})

test('inline code wins over emphasis inside it', () => {
  const nodes = parseInline('`a_b_c`')
  assert.deepEqual(types(nodes), ['code'])
  assert.equal(nodes[0].value, 'a_b_c')
})

test('strikethrough is read', () => {
  assert.deepEqual(types(parseInline('~~gone~~')), ['del'])
})

/* ------------------------------------------------------------------ links */

test('a link keeps its href and its label', () => {
  const [node] = parseInline('[docs](https://example.com/a)')
  assert.equal(node.type, 'link')
  assert.equal(node.href, 'https://example.com/a')
  assert.equal(flatten([node]), 'docs')
})

test('a bare URL is linked', () => {
  const [node] = parseInline('see https://example.com now')
  assert.equal(node.type, 'text')
  assert.equal(parseInline('https://example.com')[0].type, 'link')
})

test('an image is an image node, not a link', () => {
  const [node] = parseInline('![a chart](https://example.com/x.png)')
  assert.equal(node.type, 'image')
  assert.equal(node.alt, 'a chart')
})

test('an unsafe scheme reaches the renderer as a link to refuse', () => {
  // The parser does not filter — the renderer drops the anchor and keeps the
  // text, so the rule about which schemes are allowed lives in exactly one
  // place. What matters here is that the scheme survives to be judged.
  const [node] = parseInline('[click](javascript:void)')
  assert.equal(node.type, 'link')
  assert.equal(node.href, 'javascript:void')
  assert.equal(SAFE_PROTOCOL.test(node.href), false)
})

test('a destination stops at an unbalanced bracket', () => {
  // `alert(1)` closes the link early, which is what CommonMark does with a
  // bare destination — the stray `)` is text.
  const [node] = parseInline('[click](javascript:alert(1))')
  assert.equal(node.href, 'javascript:alert(1')
})

/* -------------------------------------------------------------- task lists */

test('a checklist is read as tasks, not as the characters', () => {
  const [list] = parseBlocks('- [x] done\n- [ ] not done')
  assert.equal(list.tasks, true)
  assert.deepEqual(list.items.map((i) => i.done), [true, false])
  assert.deepEqual(list.items.map((i) => i.text), ['done', 'not done'])
})

test('an uppercase X is also done', () => {
  const [list] = parseBlocks('- [X] done')
  assert.equal(list.items[0].done, true)
})

test('an ordinary list is not a checklist', () => {
  const [list] = parseBlocks('- one\n- two')
  assert.equal(list.tasks, false)
  assert.equal(list.items[0].done, undefined)
})

test('nesting is preserved', () => {
  const [list] = parseBlocks('- one\n  - deeper\n- two')
  assert.equal(list.items.length, 2)
  assert.equal(list.items[0].children[0].items[0].text, 'deeper')
})

test('an ordered list is ordered', () => {
  const [list] = parseBlocks('1. first\n2. second')
  assert.equal(list.type, 'ol')
})

/* ---------------------------------------------------------------- callouts */

test('a GitHub admonition is a callout', () => {
  const [b] = parseBlocks('> [!WARNING]\n> Do not do that.')
  assert.equal(b.type, 'callout')
  assert.equal(b.kind, 'warning')
  assert.equal(b.text, 'Do not do that.')
})

test('an unknown admonition stays an ordinary quote', () => {
  const [b] = parseBlocks('> [!SOMETHING]\n> body')
  assert.equal(b.type, 'quote')
})

test('a plain quote is still a quote', () => {
  const [b] = parseBlocks('> just a quote')
  assert.equal(b.type, 'quote')
  assert.equal(b.text, 'just a quote')
})

/* ------------------------------------------------------- headings & tables */

test('headings carry their level', () => {
  assert.deepEqual(parseBlocks('# a\n\n### b').map((b) => b.level), [1, 3])
})

test('a table is read head-first', () => {
  const [b] = parseBlocks('| a | b |\n| - | - |\n| 1 | 2 |')
  assert.equal(b.type, 'table')
  assert.deepEqual(b.head, ['a', 'b'])
  assert.deepEqual(b.rows, [['1', '2']])
})

test('a pipe in a sentence is not a table', () => {
  const [b] = parseBlocks('use a | b to pipe')
  assert.equal(b.type, 'p')
})

test('a rule is a rule', () => {
  assert.equal(parseBlocks('---')[0].type, 'hr')
})

/* ----------------------------------------------------------- streaming */

test('every prefix of a document parses without throwing', () => {
  // The transcript renders on every delta, so each of these is a real state.
  const doc = [
    '# Title', '', 'Some **bold** and `code`.', '',
    '> [!NOTE]', '> Careful.', '',
    '```python app.py', 'x = 1', '```', '',
    '- [x] done', '- [ ] todo', '',
    '| a | b |', '| - | - |', '| 1 | 2 |',
  ].join('\n')
  for (let n = 0; n <= doc.length; n += 1) {
    assert.doesNotThrow(() => parseBlocks(doc.slice(0, n)), `prefix of length ${n}`)
  }
})

test('empty and nullish input are empty documents', () => {
  assert.deepEqual(parseBlocks(''), [])
  assert.deepEqual(parseBlocks(null), [])
  assert.deepEqual(parseInline(''), [])
})

/* ---------------------------------------------------------------- report */

for (const f of failures) console.log(`FAIL  ${f.name}\n      ${f.message}`)
console.log(`\n${passed} passed, ${failures.length} failed`)
process.exit(failures.length ? 1 : 0)
