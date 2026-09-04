/* Syntax highlighting for model output, as a token tree rather than as HTML.
 *
 * Every other highlighter in common use hands back a string of markup, which
 * would mean `dangerouslySetInnerHTML` on the one input in this system that a
 * model wrote. Markdown.jsx exists partly to avoid exactly that. `refractor`
 * runs Prism's grammars and returns hast — an object tree of elements and text
 * — so the spans can be built as React elements and no HTML is ever parsed.
 *
 * The grammars are fetched on demand. They are perhaps 30kB together and most
 * conversations use two of them, so shipping the set in the opening bundle
 * would be paying for Rust and SQL on the way to a page that shows neither.
 */

/* What a model actually labels its fences. The left side is what gets written;
 * the right is refractor's own name for the grammar. Anything unlisted renders
 * unhighlighted, which is the correct outcome rather than a failure. */
const ALIASES = {
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', node: 'javascript',
  jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
  py: 'python', python3: 'python',
  sh: 'bash', shell: 'bash', zsh: 'bash', console: 'bash', terminal: 'bash',
  yml: 'yaml',
  html: 'markup', xml: 'markup', svg: 'markup', vue: 'markup',
  md: 'markdown', markdown: 'markdown',
  rs: 'rust', golang: 'go', dockerfile: 'docker',
  'c++': 'cpp', 'c#': 'csharp', cs: 'csharp',
  plaintext: null, text: null, txt: null, log: null, output: null,
}

/* One dynamic import per grammar. Listed rather than built from a template
 * string because a bundler cannot split what it cannot see: `import(`.../${x}`)`
 * either fails or pulls all five hundred language files into the graph. */
const GRAMMARS = {
  bash: () => import('refractor/bash'),
  c: () => import('refractor/c'),
  cpp: () => import('refractor/cpp'),
  csharp: () => import('refractor/csharp'),
  css: () => import('refractor/css'),
  diff: () => import('refractor/diff'),
  docker: () => import('refractor/docker'),
  go: () => import('refractor/go'),
  graphql: () => import('refractor/graphql'),
  ini: () => import('refractor/ini'),
  java: () => import('refractor/java'),
  javascript: () => import('refractor/javascript'),
  json: () => import('refractor/json'),
  jsx: () => import('refractor/jsx'),
  markdown: () => import('refractor/markdown'),
  markup: () => import('refractor/markup'),
  python: () => import('refractor/python'),
  ruby: () => import('refractor/ruby'),
  rust: () => import('refractor/rust'),
  sql: () => import('refractor/sql'),
  toml: () => import('refractor/toml'),
  tsx: () => import('refractor/tsx'),
  typescript: () => import('refractor/typescript'),
  yaml: () => import('refractor/yaml'),
}

/** refractor's name for a fence label, or null when there is nothing to load. */
export function grammarFor(label) {
  const key = String(label || '').trim().toLowerCase()
  if (!key) return null
  const name = key in ALIASES ? ALIASES[key] : key
  return name && name in GRAMMARS ? name : null
}

let core = null
const loaded = new Map()

/** Load one grammar, once. Resolves to the shared refractor instance, or null
 *  when the grammar or refractor itself could not be fetched — an offline
 *  reload should render plain code, not an empty block. */
export function loadGrammar(name) {
  if (!name || !(name in GRAMMARS)) return Promise.resolve(null)
  if (loaded.has(name)) return loaded.get(name)

  const job = (async () => {
    core ??= import('refractor/core').then((m) => m.refractor)
    const refractor = await core
    const grammar = await GRAMMARS[name]()
    // Grammars carry their own dependencies (tsx needs jsx needs markup), and
    // `register` walks them, so this is one call rather than a manifest here.
    refractor.register(grammar.default ?? grammar)
    return refractor
  })().catch(() => {
    // Do not cache a failure: a second attempt after the network comes back
    // should be allowed to succeed.
    loaded.delete(name)
    return null
  })

  loaded.set(name, job)
  return job
}

/** Whether a grammar is already in memory, so the first paint of a block whose
 *  language has been seen before is highlighted rather than plain. */
export const isLoaded = (name) => loaded.has(name)

/** `refractor.highlight`, with the failure modes flattened to null. */
export function tokenize(refractor, code, name) {
  if (!refractor || !name) return null
  try {
    return refractor.highlight(code, name).children
  } catch {
    // A grammar that throws on a half-written token is a highlighting problem,
    // never a rendering one.
    return null
  }
}
