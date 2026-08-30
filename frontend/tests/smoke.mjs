/* Drive the real interface against a real backend.

   Every bug worth having a test for here was invisible to unit tests: a
   confirmation prompt that never appeared, a stream that rendered the answer
   twice, a shortcut two components both claimed. So this drives a browser
   against `psok serve` and a configured model, and asserts what a person would
   see.

     psok serve                      # in another terminal
     npm run smoke                   # BASE=http://127.0.0.1:8000 by default

   It sends real messages to whichever provider the machine has configured, so
   it costs whatever a few short turns cost. `SMOKE_SHELL=0` skips the part that
   asks the agent to run `echo`, if approving a shell call is not wanted. */

import { existsSync, readdirSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { chromium } from 'playwright-core'

const BASE = process.env.BASE || 'http://127.0.0.1:8000'
const OUT = process.env.OUT || null
const WITH_SHELL = process.env.SMOKE_SHELL !== '0'
const TURN_TIMEOUT = Number(process.env.SMOKE_TURN_TIMEOUT || 300000)

/** Chromium from the Playwright cache; playwright-core does not ship one. */
function findChromium() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH
  const root = join(process.env.HOME, '.cache', 'ms-playwright')
  if (!existsSync(root)) return null
  for (const dir of readdirSync(root).filter((d) => d.startsWith('chromium-')).sort().reverse()) {
    for (const candidate of ['chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium']) {
      const exe = join(root, dir, candidate)
      if (existsSync(exe)) return exe
    }
  }
  return null
}

const results = []
const check = (name, ok, detail = '') => {
  results.push({ name, ok })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}
const skip = (name, why) => console.log(`SKIP  ${name} — ${why}`)

const exe = findChromium()
if (!exe) {
  console.error('No Chromium found. Install one with:  npx playwright install chromium')
  process.exit(2)
}

const health = await fetch(`${BASE}/api/health`).catch(() => null)
if (!health?.ok) {
  console.error(`No API at ${BASE}. Start one with:  psok serve`)
  process.exit(2)
}

const browser = await chromium.launch({ executablePath: exe })
const context = await browser.newContext({
  viewport: { width: 1280, height: 860 },
  permissions: ['clipboard-read', 'clipboard-write'],
})
const page = await context.newPage()
const consoleErrors = []
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`))

const shot = async (name) => { if (OUT) await page.screenshot({ path: join(OUT, `${name}.png`) }) }
/* Idle means: the composer is back, it accepts typing, and nothing is waiting
   on an answer. Testing only for "not disabled" reports idle when the composer
   is missing entirely, which is how a suspended turn passed for a finished
   one. */
const idle = () => page.waitForFunction(
  () => {
    const box = document.querySelector('.composer textarea')
    return Boolean(box) && !box.disabled && !document.querySelector('.confirm-modal')
  },
  null,
  { timeout: TURN_TIMEOUT },
)

/** Wait for the turn to actually start.
 *
 *  Checking for idle straight after pressing Enter reports the turn finished
 *  before it began: the composer is still enabled for the moment it takes to
 *  create the conversation and open the stream. */
const started = () => page.waitForFunction(
  () => document.querySelector('.composer textarea')?.disabled === true,
  null,
  { timeout: 30000 },
)

/** Answer every prompt the turn raises, not just the first: one request can
 *  produce several gated calls. */
async function answerPrompts(onFirst) {
  let answered = 0
  for (;;) {
    const prompted = await Promise.race([
      page.waitForSelector('.confirm-modal', { timeout: TURN_TIMEOUT }).then(() => true),
      idle().then(() => false),
    ])
    if (!prompted) {
      // The recovery fetch runs when the turn goes idle and can legitimately
      // re-raise a prompt a moment later, so idle is confirmed rather than
      // assumed.
      await page.waitForTimeout(1200)
      if (!(await page.locator('.confirm-modal').count())) return answered
    }
    if (answered === 0 && onFirst) await onFirst()
    await page.keyboard.press('Enter')
    await page.waitForSelector('.confirm-modal', { state: 'detached', timeout: 20000 })
    answered += 1
  }
}

try {
  await page.goto(BASE, { waitUntil: 'networkidle' })
  // Cleared once rather than on every navigation: the reload check below is
  // about what the previous session left behind.
  await page.evaluate(() => localStorage.clear())
  await page.reload({ waitUntil: 'networkidle' })

  check('the app renders', await page.locator('.rail-brand').isVisible())
  const status = await page.locator('.rail-foot-sub').innerText()
  check('health reaches the rail', /tools|offline/.test(status), status.trim())

  // ------------------------------------------------------------- keyboard
  await page.keyboard.press('Control+k')
  await page.waitForSelector('.palette', { timeout: 3000 })
  await page.locator('.palette-input input').fill('connect')
  await page.waitForTimeout(200)
  check('the palette opens and filters', (await page.locator('.palette-item').count()) > 0)
  await page.keyboard.press('Escape')
  check('escape closes the palette', (await page.locator('.palette').count()) === 0)

  await page.keyboard.press('?')
  await page.waitForSelector('.shortcuts-modal', { timeout: 3000 })
  check('? lists the shortcuts', (await page.locator('.shortcut-row').count()) > 8)
  await page.keyboard.press('Escape')

  const sideBefore = await page.locator('.rail').count()
  await page.keyboard.press('Control+b')
  await page.waitForTimeout(200)
  check('the rail toggles', (await page.locator('.rail').count()) !== sideBefore)
  await page.keyboard.press('Control+b')
  await page.waitForTimeout(150)

  // ------------------------------------------------------ menus and modals
  await page.locator('.composer-chip').first().click()
  await page.waitForSelector('.menu', { timeout: 3000 })
  await page.locator('.menu-row', { hasText: 'Skills' }).first().click()
  await page.waitForTimeout(250)
  check('the + menu opens a submenu', (await page.locator('.menu-flyout').count()) === 1)
  await page.keyboard.press('Escape')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(150)

  // Settings used to carry a second, shorter Connectors page of its own. There
  // is one Skills & connectors page now, and the settings nav goes to it.
  await page.keyboard.press('Control+,')
  await page.waitForSelector('.settings', { timeout: 3000 })
  check('settings does not draw a second connectors page',
    (await page.locator('.set-table').count()) === 0)
  await page.locator('.set-nav-item', { hasText: 'Skills & connectors' }).click()
  await page.waitForSelector('.cap-tabs', { timeout: 6000 })
  check('the settings nav goes to the one capabilities page',
    (await page.locator('.settings').count()) === 0
      && (await page.locator('.rail-place.active').innerText()).trim() === 'Skills & connectors')

  // Skills and connectors are one page with two tabs, and each tab carries both
  // what is added and what could be. The directory overlay is gone.
  await page.keyboard.press('Control+4')
  await page.waitForSelector('.cap-tabs', { timeout: 6000 })
  await page.locator('.cap-tab', { hasText: 'Connectors' }).click()
  // The connectors page is a list of rows now, not a table -- one row opens
  // into its own detail panel. These selectors tracked the table and so failed
  // on markup rather than on behaviour, which is the least useful way for a
  // browser test to fail.
  await page.waitForSelector('.conn-list', { timeout: 8000 })
  await page.waitForTimeout(700)
  check('the connectors tab lists what is configured',
    (await page.locator('.conn-list .conn-row').count()) > 0)

  // A connector that has never once worked must not sit among the ones serving
  // tools right now under a heading saying they are the same thing.
  const heads = await page.locator('.cap-section-head').allInnerTexts()
  check('working and not-working connectors are kept apart',
    heads.some((h) => /connected/i.test(h)) || heads.some((h) => /not running|not started/i.test(h)),
    heads.map((h) => h.split('\n')[0]).join(' | '))
  check('a connected row reports live tools, not just a switch',
    !heads.some((h) => /^connected/i.test(h))
      || /tools?\b/.test(await page.locator('.conn-list').first().innerText()))

  // Adding happens on this page: the catalogue opens underneath.
  await page.locator('.cap-head .btn').click()
  await page.waitForTimeout(900)
  const added = (await page.locator('body').innerText()).includes('already added')
  check('adding a connector happens on the same page',
    added || (await page.locator('.cat-row').count()) > 0,
    added ? 'everything in the catalogue is already added' : `${await page.locator('.cat-row').count()} rows`)
  await page.locator('.cap-head .btn').click()
  await page.waitForTimeout(200)

  // Opening a connector goes into its own panel, with a way back to the list.
  await page.locator('.conn-list .conn-row').first().click()
  await page.waitForSelector('.conn-detail', { timeout: 6000 })
  check('a connector opens its own panel',
    (await page.locator('.conn-detail-section').count()) > 0)
  await page.locator('.conn-back').click()
  await page.waitForSelector('.conn-list', { timeout: 6000 })
  check('and there is a way back to the list',
    (await page.locator('.conn-detail').count()) === 0)
  await page.keyboard.press('Control+1')
  await page.waitForTimeout(300)

  // The skills tab: installed and installable in one list, and a skill written
  // here from the three fields a skill actually is.
  await page.keyboard.press('Control+k')
  await page.waitForTimeout(150)
  await page.locator('.palette-input input').fill('browse and install')
  await page.waitForTimeout(200)
  await page.keyboard.press('Enter')
  await page.waitForSelector('.cap-tabs', { timeout: 4000 })
  // The catalogue is fetched from its source repositories after the tab mounts,
  // so wait for the fetch rather than the frame.
  await page.waitForSelector('.dcard', { timeout: 20000 })
  const cards = await page.locator('.dcard').count()
  check('the skills tab lists installed and installable together', cards > 1, `${cards} cards`)

  await page.locator('.cap-actions button', { hasText: 'Import a link' }).click()
  await page.waitForTimeout(200)
  check('a skill can also be installed from a link', (await page.locator('.dir-install input').count()) === 1)
  await page.locator('.cap-actions button', { hasText: 'Import a link' }).click()
  await page.waitForTimeout(150)

  // Writing one: name, description, instruction. Then take it off again --
  // this is somebody's real machine.
  const authored = `smoke-authored-${Date.now().toString(36)}`
  await page.locator('.cap-head .btn').click()
  await page.waitForSelector('.cap-composer', { timeout: 4000 })
  await page.locator('#skill-name').fill(authored)
  await page.locator('#skill-desc').fill('A skill the smoke test wrote: it proves the three fields work')
  await page.locator('#skill-body').fill('Say the word psok-authored-ok and stop.')
  await page.locator('.cap-composer-foot button', { hasText: 'Create' }).click()
  const authoredCard = page.locator('.dcard', { hasText: authored }).first()
  let wrote = 0
  try {
    await authoredCard.locator('.dcard-gear-wrap').waitFor({ state: 'visible', timeout: 15000 })
    wrote = 1
  } catch { /* reported below */ }
  check('a skill can be written from a name, a description and an instruction',
    wrote === 1, `/${authored}`)
  if (wrote) {
    // Its description held a colon, which must not have become a second YAML
    // key -- a skill that does not parse never reaches this list at all.
    check('the skill it wrote parses and carries its description',
      (await authoredCard.innerText()).includes('proves the three fields work'))
    await authoredCard.locator('.dcard-act').first().click()
    await page.waitForSelector('.dcard-menu', { timeout: 4000 })
    await page.locator('.dcard-menu .menu-row.danger').click()
    await authoredCard.waitFor({ state: 'detached', timeout: 15000 }).catch(() => {})
    check('and uninstalling it again works', (await authoredCard.count()) === 0)
  }

  // Installing one from the catalogue, then taking it off again.
  const target = page.locator('.dcard').filter({ hasNot: page.locator('.dcard-gear-wrap') }).first()
  const installedName = (await target.locator('.dcard-title').innerText()).replace('/', '').trim()
  await target.locator('.dcard-act').click()
  // The install refetches both the installed list and the catalogue, and the
  // grid re-sorts around the result, so wait for the card's own state to change
  // rather than for a fixed interval.
  const installedCard = page.locator('.dcard', { hasText: installedName }).first()
  let nowInstalled = 0
  try {
    await installedCard.locator('.dcard-gear-wrap').waitFor({ state: 'visible', timeout: 20000 })
    nowInstalled = 1
  } catch { /* reported below */ }
  check('installing a skill from the catalogue works', nowInstalled === 1, `/${installedName}`)
  if (nowInstalled) {
    await installedCard.locator('.dcard-act').first().click()
    await page.waitForSelector('.dcard-menu', { timeout: 4000 })
    await page.locator('.dcard-menu .menu-row.danger').click()
    await installedCard.locator('.dcard-gear-wrap').waitFor({ state: 'detached', timeout: 20000 }).catch(() => {})
    check('and uninstalling that one works too',
      (await installedCard.locator('.dcard-gear-wrap').count()) === 0)
  }

  check('the browse-everything overlay is gone', (await page.locator('.dir').count()) === 0)
  await page.keyboard.press('Control+1')
  await page.waitForTimeout(200)

  // A file dropped into the composer becomes a path the tools can read.
  const scratch = join(tmpdir(), `psok-smoke-${Date.now()}.txt`)
  writeFileSync(scratch, 'the smoke test wrote this')
  await page.locator('input[type=file]').first().setInputFiles(scratch)
  await page.waitForSelector('.file-chip', { timeout: 8000 })
  check('an attached file is uploaded and shown', (await page.locator('.file-chip').innerText()).includes('psok-smoke'))
  await page.locator('.file-chip button').click()
  await page.waitForTimeout(150)
  check('an attachment can be taken off again', (await page.locator('.file-chip').count()) === 0)

  // ------------------------------------------------ a turn, and its markdown
  await page.keyboard.press('Control+l')
  await page.locator('.composer textarea').fill(
    'Reply with exactly: a markdown heading "## Check", then a bullet list of two items,'
    + ' then a python fenced code block that prints hello. No other text.',
  )
  await page.keyboard.press('Enter')
  await started()

  // The message that was typed has to still be there. Sending the first message
  // of a new conversation sets the conversation id, which used to fire a
  // transcript fetch that raced the stream and replaced it.
  check('the typed message survives the turn opening',
    (await page.locator('.msg-user').last().innerText()).includes('markdown heading'))

  // Reasoning, if the model exposes any, is watched while it happens rather
  // than hidden behind a collapsed block that says "thinking".
  const sawLiveThinking = await page
    .waitForSelector('.reasoning.live .reasoning-body.is-live', { timeout: 20000 })
    .then(() => true).catch(() => false)

  await page.waitForSelector('.msg-assistant .md', { timeout: TURN_TIMEOUT })
  await idle()

  // The composer comes back on `done`, not when the stream closes -- memory
  // extraction is a second model call that runs after it -- so nothing may
  // still claim to be thinking once the answer is on screen.
  await page.waitForTimeout(700)
  check('nothing is still thinking once the answer has landed',
    (await page.locator('.thinking').count()) === 0
      && (await page.locator('.reasoning.live').count()) === 0)

  if (sawLiveThinking) {
    check('the thinking is still there after the turn, folded up',
      (await page.locator('.reasoning').count()) > 0)
  } else {
    skip('the thinking is still there after the turn', 'this model streamed no reasoning')
  }

  check('the answer arrives', (await page.locator('.msg-assistant').last().innerText()).length > 0)
  check('markdown headings render', (await page.locator('.msg-assistant .md-h').count()) > 0)
  check('markdown lists render', (await page.locator('.msg-assistant .md-list li').count()) >= 2)
  check('fenced code renders as a block', (await page.locator('.msg-assistant .md-pre').count()) > 0)
  check(
    'the answer is not rendered twice',
    (await page.locator('.msg-assistant').count()) <= 2,
    `${await page.locator('.msg-assistant').count()} bubbles`,
  )

  if (await page.locator('.md-copy').count()) {
    await page.locator('.md-copy').first().click()
    await page.waitForTimeout(150)
    const clip = await page.evaluate(() => navigator.clipboard.readText())
    check('a code block copies', clip.length > 0, JSON.stringify(clip.slice(0, 28)))
  }
  await shot('chat')

  // -------------------------------------------------------------- reloading
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.msg-user', { timeout: 15000 })
  check('the open conversation survives a reload', (await page.locator('.msg-user').count()) > 0)

  // ------------------------------------------------------------------ pins
  //
  // A pin is a bookmark in a transcript that scrolls: it survives a reload,
  // because a mark that only exists in this tab is not a mark on anything.
  await page.locator('.msg-assistant').last().hover()
  await page.locator('.msg-assistant').last().locator('.msg-pin').click()
  await page.waitForSelector('.pin-strip', { timeout: 5000 })
  check('an answer can be pinned', (await page.locator('.pin-chip').count()) === 1)

  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForSelector('.msg-user', { timeout: 15000 })
  const survived = await page
    .waitForSelector('.pin-strip .pin-chip', { timeout: 8000 })
    .then(() => true).catch(() => false)
  check('the pin survives a reload', survived)

  if (survived) {
    await page.locator('.pin-chip').first().click()
    await page.waitForTimeout(700)
    check('a pinned message can be jumped to',
      (await page.locator('.msg.is-pinned').count()) > 0)
    await page.locator('.pin-chip-off').first().click()
    await page.waitForTimeout(700)
    check('and unpinned again from the strip', (await page.locator('.pin-chip').count()) === 0)
  }

  await page.keyboard.press('F2')
  const rename = page.locator('.rail-rename')
  if (await rename.count()) {
    await rename.fill('smoke test')
    await page.keyboard.press('Enter')
    await page.waitForTimeout(400)
    check(
      'F2 renames the conversation',
      (await page.locator('.rail-conv-title').first().innerText()).includes('smoke test'),
    )
  } else {
    check('F2 renames the conversation', false, 'no rename field appeared')
  }

  for (const [combo, label] of [
    ['Control+2', 'Tasks'], ['Control+4', 'Skills & connectors'],
    ['Control+5', 'Automations'], ['Control+7', 'Activity'],
  ]) {
    await page.keyboard.press(combo)
    await page.waitForTimeout(300)
    // A rail row can carry a badge on a second line ("Automations" / "beta").
    const active = (await page.locator('.rail-place.active').innerText()).split('\n')[0].trim()
    check(`${combo} switches view`, active === label, active)
  }
  await page.keyboard.press('Control+1')
  await page.waitForTimeout(200)

  // --------------------------------------------------- the permission gate
  //
  // A standing "don't ask again" for the shell is a legitimate state of this
  // machine, and it means no prompt will appear. That is the feature working,
  // not the test failing -- so the prompt is raced against the turn finishing
  // and reported accordingly rather than mutating what the user has approved.
  if (WITH_SHELL) {
    const standing = await (await fetch(`${BASE}/api/confirmations/preferences`)).json()
    const shellApproved = standing.some((p) => p.operation_key.startsWith('run_shell_command'))

    await page.keyboard.press('Control+Shift+O')
    await page.waitForTimeout(300)
    await page.locator('.composer textarea').fill(
      'Run this shell command and show me the output: echo psok-smoke-ok',
    )
    await page.keyboard.press('Enter')
    await started()

    const answered = await answerPrompts(async () => {
      check('a shell call suspends the turn and prompts', true)
      const prompt = await page.locator('.confirm-modal').innerText()
      check('the prompt names the operation key, not just the tool', /run_shell_command:\w/.test(prompt))
      await shot('confirm')

      await page.keyboard.press('r')
      await page.waitForTimeout(100)
      check('R arms "remember this decision"',
        await page.locator('.confirm-modal input[type=checkbox]').isChecked())
      // Leave no standing approval behind: this is somebody's real machine.
      await page.keyboard.press('r')
      await page.waitForTimeout(50)
    })

    if (answered > 0) {
      check('every prompt the turn raised was answerable from the keyboard', true, `${answered} answered`)
      await idle()
    } else if (shellApproved) {
      skip('a shell call suspends the turn and prompts',
        'this machine already approved the shell in advance; revoke it in Activity to exercise the prompt')
    } else {
      check('a shell call suspends the turn and prompts', false, 'the turn ended with no prompt')
    }

    check('the call is recorded in the transcript', (await page.locator('.tool-card').count()) > 0)
    await page.locator('.tool-card-head').first().click()
    await page.waitForTimeout(200)
    check('its result is visible when expanded',
      (await page.locator('.tool-card').first().innerText()).includes('psok-smoke-ok'))

    await page.keyboard.press('Control+7')
    await page.waitForTimeout(1200)
    const activity = await page.locator('body').innerText()
    check('the audit trail shows it', /run_shell_command/.test(activity))
    check('the trail is only the trail, not a second permissions page',
      (await page.locator('.card-title', { hasText: /runs without asking/i }).count()) === 0)
    await shot('activity')

    // What runs without asking is one page now, and it is in the settings.
    await page.keyboard.press('Control+,')
    await page.waitForSelector('.settings', { timeout: 3000 })
    await page.locator('.set-nav-item', { hasText: 'Permissions' }).click()
    await page.waitForTimeout(400)
    check('standing approvals are listed where they can be taken back',
      /runs without asking/i.test(await page.locator('.settings').innerText()))
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
  }

  // ------------------------------------------------------- automations (beta)
  //
  // Created and deleted, not run: a scheduled turn costs a real model call, and
  // the gate it runs behind is covered by the unit tests.
  await page.keyboard.press('Control+5')
  await page.waitForSelector('.cap-head', { timeout: 6000 })
  check('automations are marked beta where they appear',
    (await page.locator('.rail-place .beta').count()) > 0
      && (await page.locator('.cap-head .beta').count()) > 0)
  // Chat stays mounted behind every view, so `.view` alone matches two.
  const autoText = await page.locator('.view:not(.view--flush)').innerText()
  check('the page says what it does and does not do',
    /while PSOK is open/i.test(autoText) && /blocked/i.test(autoText))

  const autoName = `smoke ${Date.now().toString(36)}`
  await page.locator('.cap-head .btn').click()
  await page.waitForSelector('#auto-name', { timeout: 4000 })
  await page.locator('#auto-name').fill(autoName)
  await page.locator('#auto-prompt').fill('Say the word psok-automation-ok and stop.')
  await page.locator('.cap-composer-foot button', { hasText: 'Create' }).click()
  const madeRow = page.locator('.auto-row', { hasText: autoName })
  let madeAuto = 0
  try {
    await madeRow.waitFor({ state: 'visible', timeout: 8000 })
    madeAuto = 1
  } catch { /* reported below */ }
  check('an automation can be created', madeAuto === 1, autoName)

  if (madeAuto) {
    const meta = await madeRow.locator('.auto-meta').innerText()
    check('it is scheduled forward rather than fired on creation', /next in/.test(meta), meta)
    await madeRow.locator('button', { hasText: 'Pause' }).click()
    await page.waitForTimeout(600)
    check('and it can be paused', /paused/i.test(await madeRow.innerText()))
    page.once('dialog', (d) => d.accept())
    await madeRow.locator('.icon-btn').click()
    await madeRow.waitFor({ state: 'detached', timeout: 8000 }).catch(() => {})
    check('and deleted', (await madeRow.count()) === 0)
  }

  // ------------------------------------------------------------- discarding
  //
  // Last, and on a conversation this run created: it is somebody's real
  // machine, and the rest of the suite still needs something to talk in.
  await page.keyboard.press('Control+1')
  await page.waitForTimeout(250)
  // Deleting one: the row menu, a confirming second click, and the row is gone.
  //
  // Asserted against the id rather than the row count. The rail lists the fifty
  // most recent conversations, so on a machine that has more than fifty,
  // deleting one pulls the fifty-first into view and the count never moves.
  const doomedId = await page.evaluate(
    () => JSON.parse(localStorage.getItem('psok.ui.v1') || '{}').activeId,
  )
  if (!doomedId) throw new Error('no conversation is open to delete')
  const doomed = page.locator('.rail-conv.active').first()
  const doomedTitle = await doomed.locator('.rail-conv-title').innerText()
  await doomed.locator('.rail-conv-more').click({ force: true })
  await page.waitForSelector('.rail-conv-menu', { timeout: 3000 })
  await page.locator('.rail-conv-menu .danger').click()
  await page.waitForTimeout(200)
  check('deleting asks for a second click first',
    (await fetch(`${BASE}/api/conversations/${doomedId}/messages`)).status === 200)
  await page.locator('.rail-conv-menu .danger').click()
  await page.waitForTimeout(900)
  check('a conversation can be deleted from the rail',
    (await fetch(`${BASE}/api/conversations/${doomedId}/messages`)).status === 404,
    doomedTitle,
  )
  // Deleting the open one has to leave the interface somewhere valid rather
  // than pointed at a row the API will now refuse.
  check('the interface lands somewhere valid afterwards',
    (await page.evaluate(
      () => JSON.parse(localStorage.getItem('psok.ui.v1') || '{}').activeId,
    )) !== doomedId && consoleErrors.length === 0)


  check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} passed`)
process.exit(failed.length ? 1 : 0)
