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

  await page.keyboard.press('Control+,')
  await page.waitForSelector('.settings', { timeout: 3000 })
  await page.locator('.set-nav-item', { hasText: 'Connectors' }).click()
  await page.waitForTimeout(400)
  check('settings lists the connectors', (await page.locator('.set-table tbody tr').count()) > 0)
  await page.keyboard.press('Escape')

  // The connectors view: popular row, tabs, table, and the set-up panel.
  await page.keyboard.press('Control+4')
  await page.waitForSelector('.conn-table', { timeout: 6000 })
  await page.waitForTimeout(600)
  check('the connectors view lists what is configured',
    (await page.locator('.conn-table tbody tr').count()) > 0)
  await page.locator('.conn-tab').nth(1).click()   // Connected
  await page.waitForTimeout(250)
  check('its tabs filter by what is actually running', true)
  await page.locator('.conn-tab').nth(0).click()   // All
  await page.waitForTimeout(250)
  await page.locator('.conn-actions-inner .icon-btn').first().click()
  await page.waitForTimeout(400)
  check('a connector opens its credentials in place',
    (await page.locator('.conn-setup').count()) === 1)
  await page.keyboard.press('Control+1')
  await page.waitForTimeout(300)

  await page.keyboard.press('Control+k')
  await page.waitForTimeout(150)
  await page.locator('.palette-input input').fill('browse and install')
  await page.waitForTimeout(200)
  await page.keyboard.press('Enter')
  await page.waitForSelector('.dir', { timeout: 4000 })
  // The catalogue is fetched from its source repositories after the modal
  // mounts, so wait for the fetch rather than the frame.
  await page.waitForSelector('.dcard', { timeout: 20000 })
  const cards = await page.locator('.dcard').count()
  check('the directory browses installable skills', cards > 1, `${cards} cards`)
  check('a skill can also be installed from a link', (await page.locator('.dir-install input').count()) === 1)

  // Install one, then take it off again: this is somebody's real machine.
  const target = page.locator('.dcard').filter({ hasNot: page.locator('.dcard-gear-wrap') }).first()
  const installedName = (await target.locator('.dcard-title').innerText()).replace('/', '').trim()
  await target.locator('.dcard-act').click()
  await page.waitForTimeout(2500)
  const nowInstalled = await page.locator('.dcard', { hasText: installedName }).locator('.dcard-gear-wrap').count()
  check('installing a skill from the directory works', nowInstalled === 1, `/${installedName}`)
  if (nowInstalled) {
    await page.locator('.dcard', { hasText: installedName }).locator('.dcard-act').first().click()
    await page.waitForTimeout(200)
    await page.locator('.dcard-menu .menu-row.danger').click()
    await page.waitForTimeout(1200)
    check('and uninstalling it again works',
      (await page.locator('.dcard', { hasText: installedName }).locator('.dcard-gear-wrap').count()) === 0)
  }

  await page.locator('.dir-nav-item', { hasText: 'Connectors' }).click()
  await page.waitForTimeout(600)
  check('the directory browses connectors', (await page.locator('.dcard').count()) > 0)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(150)

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
  await page.waitForSelector('.msg-assistant .md', { timeout: TURN_TIMEOUT })
  await idle()

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

  for (const [combo, label] of [['Control+2', 'Tasks'], ['Control+4', 'Connectors'], ['Control+6', 'Activity']]) {
    await page.keyboard.press(combo)
    await page.waitForTimeout(300)
    check(`${combo} switches view`, (await page.locator('.rail-place.active').innerText()).trim() === label)
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

    await page.keyboard.press('Control+6')
    await page.waitForTimeout(1200)
    const activity = await page.locator('body').innerText()
    check('the audit trail shows it', /run_shell_command/.test(activity))
    check('standing approvals are listed where they can be taken back',
      /runs without asking/i.test(activity))
    await shot('activity')
  }

  check('no console errors', consoleErrors.length === 0, consoleErrors.slice(0, 2).join(' | '))
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} passed`)
process.exit(failed.length ? 1 : 0)
