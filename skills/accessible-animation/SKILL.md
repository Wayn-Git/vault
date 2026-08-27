---
name: accessible-animation
description: This skill should be used when the user asks to "respect prefers-reduced-motion", "honor reduced motion", "make my animations accessible", "fix vestibular / motion-sickness issues", "add a useReducedMotion hook", "gate GSAP / Framer Motion / Lenis for reduced motion", or "meet WCAG 2.3.3 / C39". Provides tiered (not all-or-nothing) reduced-motion patterns in CSS and JS.
version: 0.1.0
---

# Accessible Animation (Reduced Motion, Tiered)

Honor `prefers-reduced-motion: reduce` as a *graceful degradation*, not a kill switch. The OS-level setting (macOS: Settings > Accessibility > Display > Reduce motion; Windows: Settings > Accessibility > Visual effects > Animation effects; iOS/Android equivalents) signals that *vestibular-triggering* motion causes nausea, dizziness, or migraines. The correct response is to remove the dangerous motion while keeping orientation cues.

## When to use

Use when adding or auditing animation in a web UI, when a user reports motion sickness or WCAG findings, or when integrating animation libraries (GSAP, Framer Motion, Lenis smooth scroll, Anime.js, CSS keyframes) into an accessible product.

## The core principle: tier motion, do not nuke it

Removing *all* animation is a common over-correction. An instant state change with no transition can be more disorienting (elements teleport) and removes useful affordances (focus rings, loading spinners that communicate progress). Sort every animation into three tiers:

- **Tier 1 — Remove entirely (vestibular triggers).** Parallax; large-area slides/translates across the viewport; scale/zoom of large elements; 3D rotation and spin; continuous auto-playing carousels and marquees; smooth-scroll hijacking (Lenis/Locomotive); scroll-jacked pinned scenes; motion-path animation; anything that moves a large portion of the screen or implies depth/self-motion.
- **Tier 2 — Soften / shorten.** Replace movement with a short opacity fade (≤200ms). Reduce distance and duration. Keep the *fact* of a transition (so elements don't teleport) but strip the displacement. Replace a 600ms slide-in-from-left with a 150ms cross-fade.
- **Tier 3 — Always keep.** Opacity fades, color/background transitions, focus-ring transitions, loading indicators, and motion that is *essential* to meaning (WCAG allows essential animation). These rarely trigger vestibular responses because they imply no self-motion.

## CSS layer: media-query gating

Write motion as the default, then override under the reduce query. Prefer a global safety net plus targeted overrides.

```css
/* Global safety net: neutralize runaway motion but DO NOT set 0s blindly,
   which can break JS that waits for transitionend/animationend. Use 0.01ms. */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;   /* stop infinite spins/marquees */
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;          /* kill smooth scroll */
  }
}
```

The global net is a backstop. Layer *intentional, tiered* overrides on top so Tier 3 motion survives:

```css
.card {
  transition: transform 400ms ease, opacity 400ms ease, background-color 200ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .card {
    /* Tier 2: drop the transform (movement), keep opacity + color (Tier 3) */
    transition: opacity 150ms ease, background-color 150ms ease;
  }
  .parallax-layer { transform: none !important; }        /* Tier 1: remove */
  .hero-zoom      { animation: none !important; }        /* Tier 1: remove */
}
```

Use the *positive* query `(prefers-reduced-motion: no-preference)` to opt motion IN, which is the safest pattern for elaborate effects:

```css
.hero { opacity: 1; } /* visible, static by default */
@media (prefers-reduced-motion: no-preference) {
  .hero { animation: zoom-in 1.2s ease both; } /* only animate when allowed */
}
```

## JS layer: matchMedia gating

CSS cannot gate JS-driven animation (GSAP timelines, Framer's `animate`, canvas/WebGL, Lenis). Read the same signal via `matchMedia` and react to live changes (users toggle the OS setting without reloading).

```js
const REDUCE_QUERY = '(prefers-reduced-motion: reduce)';

export function prefersReducedMotion() {
  return typeof window !== 'undefined'
    && window.matchMedia
    && window.matchMedia(REDUCE_QUERY).matches;
}

// Live updates: listen so toggling the OS setting takes effect immediately.
export function onReducedMotionChange(cb) {
  const mq = window.matchMedia(REDUCE_QUERY);
  const handler = (e) => cb(e.matches);
  mq.addEventListener('change', handler);          // modern API
  return () => mq.removeEventListener('change', handler);
}
```

### Library gating, applied as one reusable layer

```js
// GSAP — use matchMedia(): GSAP reverts conditional setups on change.
import gsap from 'gsap';
const mm = gsap.matchMedia();
mm.add({
  motionOK: '(prefers-reduced-motion: no-preference)',
  motionReduce: '(prefers-reduced-motion: reduce)',
}, (ctx) => {
  const { motionOK } = ctx.conditions;
  if (motionOK) {
    gsap.from('.hero', { y: 80, opacity: 0, duration: 1 });   // Tier 1 move
  } else {
    gsap.from('.hero', { opacity: 0, duration: 0.15 });        // Tier 2 fade
  }
});

// Lenis smooth scroll — do not instantiate at all when reduced.
import Lenis from 'lenis';
let lenis = null;
if (!prefersReducedMotion()) {
  lenis = new Lenis();
  const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); };
  requestAnimationFrame(raf);
}
```

## React: a `useReducedMotion` hook

```jsx
import { useState, useEffect } from 'react';

export function useReducedMotion() {
  const query = '(prefers-reduced-motion: reduce)';
  const get = () =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia(query).matches
      : false;
  const [reduced, setReduced] = useState(get);

  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setReduced(mq.matches);
    onChange();                                   // sync after hydration
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return reduced;
}
```

```jsx
// Framer Motion has its own useReducedMotion(); the hook above also works.
import { motion } from 'framer-motion';
function Card() {
  const reduced = useReducedMotion();
  return (
    <motion.div
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? 0.15 : 0.5 }}
    />
  );
}
```

Initialize SSR-rendered state to `false` (motion) and re-sync in `useEffect` to avoid a hydration mismatch; the OS value is only known client-side.

## WCAG mapping

- **2.3.3 Animation from Interactions (AAA).** Motion triggered by interaction (scroll, hover) must be disable-able unless essential. Honoring `prefers-reduced-motion` is the standard technique.
- **C39 (CSS technique).** Use the `prefers-reduced-motion` query to prevent motion. This is the named sufficient technique.
- **2.2.2 Pause, Stop, Hide (A).** Any auto-playing motion lasting >5s must offer pause/stop. Auto-carousels and marquees fail this regardless of the media query — give a control too.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained demo the deliverable is **one HTML file that opens directly in a browser** — markup, CSS, and any JS (GSAP/`matchMedia` from CDN) inline, no build step. For *this* skill the verification is the point: you must screenshot **both** the normal and the reduced-motion path and confirm the tiering is correct.

**Output contract:**
- One `.html` file with the full motion AND its tiered reduced-motion overrides (CSS query + `matchMedia`/`gsap.matchMedia()` for JS-driven motion).
- A seek harness to freeze a frame, plus a way to force the reduced-motion code path for screenshots.

**Seek harness — freeze a frame, force the preference.** `?t=N` freezes the timeline; `?reduce=1` forces the reduced path even when the OS setting is off (CSS can't be toggled from JS, so query the same flag you gate JS on, and screenshot with the OS/browser preference emulated for the CSS layer):

```html
<script>
  const q = new URLSearchParams(location.search);
  const reduce = q.get("reduce") === "1"
    || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  // build motion conditionally on `reduce` (Tier-1 removed, Tier-2 softened, Tier-3 kept)
  const t = q.get("t");
  if (t !== null) { tl.pause(); tl.seek(parseFloat(t)); }      // GSAP; CSS: el.style.animationDelay=(-t)+"s"; playState="paused"
  window.__ready = true;
</script>
```

**Verify loop — screenshot BOTH states:** capture the normal path AND the reduced path, mid-animation each, and confirm Tier-1 motion is gone, Tier-2 is a short fade, Tier-3 survives. Emulate the preference for the CSS layer (Playwright `--reduced-motion=reduce`; the agent's browser tool can emulate it too):

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/demo.html?t=0.6" normal.png
npx playwright screenshot --reduced-motion=reduce --wait-for-timeout=500 "file://$PWD/demo.html?t=0.6&reduce=1" reduced.png
```

**Before you finish:**
1. Opens standalone — no console errors, CDN (if any) loads.
2. The freeze + `?reduce=1` (and `--reduced-motion=reduce`) reliably exercises both code paths.
3. Screenshotted in BOTH states, mid-animation — normal looks intentional, reduced strips Tier-1/softens Tier-2.
4. `prefers-reduced-motion` honored as *tiering*, not a kill switch — no teleporting, Tier-3 fades/focus rings/spinners kept; any >5s auto-motion still has a pause control (2.2.2).
5. Easing is intentional in both paths — no accidental `linear`, durations sane (reduced fades ≤200ms, `0.01ms` not `0s`).

## Quick reference

| Motion type | Tier | Reduced behavior |
|---|---|---|
| Parallax / depth | 1 | Remove (`transform: none`) |
| Large slide / translate | 1 | Remove or replace with fade |
| Scale / zoom (large) | 1 | Remove |
| Spin / 3D rotate | 1 | Remove (`animation: none`) |
| Auto carousel / marquee | 1 | Stop + provide pause control (2.2.2) |
| Smooth-scroll (Lenis) | 1 | Don't instantiate |
| Small slide / pop-in | 2 | Cross-fade ≤200ms |
| Opacity fade | 3 | Keep (shorten if long) |
| Color / focus-ring transition | 3 | Keep |
| Loading spinner | 3 | Keep (essential feedback) |

## Gotchas

- `animation-duration: 0s` can break code waiting on `animationend`/`transitionend`; use `0.01ms` so the event still fires.
- The global `*` reset alone over-removes Tier 3 motion; always layer intentional overrides.
- Forgetting `animation-iteration-count: 1` leaves infinite spins running at near-zero duration (CPU churn, still animating).
- No media query covers JS/canvas/WebGL — gate those with `matchMedia` or the loop never stops.
- Toggling the OS setting fires no page reload; without a `change` listener the page keeps its stale state.
- SSR: reading `matchMedia` during render throws or mismatches; default to motion and sync in an effect.
- Auto-playing motion needs a visible pause control even when reduced-motion is off (2.2.2 is Level A).

## Reference files

- `references/patterns.md` — Full GSAP `matchMedia` teardown, Framer Motion `MotionConfig`, Lenis start/stop on live toggle, a reusable `animateWithMotionPreference` wrapper, marquee with pause control, and a tier-classification audit checklist.
