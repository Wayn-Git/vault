---
name: gsap-web
description: This skill should be used when the user asks to "build a scroll animation", "add ScrollTrigger", "pin a section while scrolling", "scrub an animation to scroll", "create a hero timeline", "do a horizontal scroll section", "split text and animate words", "animate a layout change with GSAP Flip", "sync ScrollTrigger with Lenis", "Lenis smooth scroll jittery", "ScrollTrigger markers drift", "ScrollTrigger pins break with Lenis/Locomotive", or "set up smooth scroll with GSAP pinning". Covers GSAP timelines, ScrollTrigger, SplitText, Flip, and Lenis/Locomotive smooth-scroll sync for code-driven web motion.
version: 0.1.0
---

# GSAP for the Web

GSAP (GreenSock Animation Platform) is the workhorse for code-driven web motion: sequenced timelines, scroll-driven storytelling, text reveals, and layout transitions. As of GSAP 3.12+, every plugin (ScrollTrigger, SplitText, Flip, MotionPath, MorphSVG, Draggable, Observer) is 100% free, including for commercial use.

## When to use

- Scroll-driven storytelling: pinned sections, parallax, progress scrubbing, horizontal scroll
- Sequenced hero animations and complex multi-element timelines with precise overlap control
- Text reveals split into chars/words/lines (SplitText)
- Layout transitions where an element changes position/size/parent (Flip)
- Any motion needing fine timing control, easing precision, or imperative orchestration

## Install and register

```js
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { SplitText } from "gsap/SplitText";
import { Flip } from "gsap/Flip";

gsap.registerPlugin(ScrollTrigger, SplitText, Flip);
```

Plugins MUST be registered before use or they silently no-op. With a bundler, register once at app entry.

## Core techniques

### Timelines first

Prefer one timeline over many independent tweens — it gives a single playhead, relative positioning, and easy reversal.

```js
const tl = gsap.timeline({ defaults: { ease: "power3.out", duration: 0.6 } });
tl.from(".title", { yPercent: 100, opacity: 0 })
  .from(".sub",   { y: 20, opacity: 0 }, "-=0.3")  // start 0.3s before prev ends
  .from(".cta",   { scale: 0.9, opacity: 0 }, "<"); // align to prev tween START
```

Position parameter cheat sheet:
- `"+=0.5"` / `"-=0.3"` — relative to the end of the timeline (gap / overlap)
- `"<"` — start of the previous tween; `">"` — end of the previous tween
- `"<0.2"` — 0.2s after the previous tween's start
- `"myLabel"` — at a named label added via `tl.addLabel("myLabel")`

Use `.from()` for entrances (animates FROM the given values TO current CSS), `.to()` for exits, `.fromTo()` when both ends must be explicit (most robust against re-runs).

### gsap.to vs set vs quickTo

```js
gsap.set(el, { autoAlpha: 0 });           // instant, no tween (autoAlpha = opacity + visibility)
const xTo = gsap.quickTo(el, "x", { duration: 0.4, ease: "power3" });
window.addEventListener("pointermove", (e) => xTo(e.clientX)); // fast repeated updates
```

`autoAlpha` is preferred over raw `opacity` because it also toggles `visibility:hidden` at 0, removing the element from hit-testing.

### ScrollTrigger basics

```js
gsap.to(".panel", {
  xPercent: -100,
  ease: "none",
  scrollTrigger: {
    trigger: ".wrap",
    start: "top top",      // when trigger top hits viewport top
    end: "+=2000",         // 2000px of scroll distance
    pin: true,             // freeze .wrap while the tween plays
    scrub: 1,              // tie progress to scrollbar (1 = 1s catch-up smoothing)
    markers: true,         // dev-only visual markers — remove for prod
  },
});
```

Key semantics:
- `start`/`end` take `"triggerPos viewportPos"` (e.g. `"top center"`) or `"+=px"`.
- `scrub: true` locks animation progress to scroll exactly; `scrub: <number>` adds smoothing lag.
- `toggleActions: "play pause resume reverse"` controls onEnter/onLeave/onEnterBack/onLeaveBack for non-scrubbed triggers.
- Use `ease: "none"` for scrubbed tweens so motion tracks scroll linearly.

### Smooth scroll (Lenis) + ScrollTrigger

Pairing Lenis (or Locomotive) smooth scrolling with ScrollTrigger desyncs unless both run on one loop. Lenis smooths scroll on its own rAF while ScrollTrigger reads scroll on GSAP's ticker; when they tick independently ScrollTrigger samples a stale position. The fix: drive Lenis from GSAP's ticker and update ScrollTrigger on every Lenis scroll.

```js
import Lenis from "lenis";

const lenis = new Lenis({ duration: 1.2, smoothWheel: true });

lenis.on("scroll", ScrollTrigger.update);          // 1. update ScrollTrigger on every Lenis scroll
gsap.ticker.add((t) => lenis.raf(t * 1000));       // 2. one loop: ticker drives Lenis (seconds → ms)
gsap.ticker.lagSmoothing(0);                        // 3. stop GSAP catch-up jitter on heavy frames
```

Critical: `gsap.ticker` passes time in **seconds**, `lenis.raf()` wants **milliseconds** — multiply by 1000. Do NOT also run a standalone `requestAnimationFrame(raf)` loop for Lenis; that double-drives it.

Common bugs:
- **Jitter/stutter** — a leftover `requestAnimationFrame(raf)` loop competing with the ticker, or missing `lagSmoothing(0)`. Remove the rogue loop; set lag smoothing to 0.
- **Markers drift** from their triggers — `ScrollTrigger.update` is not subscribed to `lenis.on("scroll", …)`.
- **Pins break** — under Lenis do NOT set a `scrollerProxy` (it scrolls the document). Under Locomotive you MUST wire `scrollerProxy` + `pinType` and set `scroller:` on every trigger.
- **Scroll stuck / flipped direction** — missing the `* 1000` unit conversion, or two loops out of order.

Cleanup on SPA unmount: `gsap.ticker.remove(update)` + `lenis.destroy()`, else loops stack per navigation. Gate behind `prefers-reduced-motion` (skip Lenis, run native scroll). Full Lenis + Locomotive wiring, anchor-link routing, `data-lenis-prevent`, React (`useGSAP`/`useEffect`), and a symptom→cause table are in `references/scrolltrigger-lenis.md`.

### SplitText (text reveal)

```js
const split = SplitText.create(".headline", { type: "lines, words", linesClass: "line" });
gsap.from(split.lines, { yPercent: 100, opacity: 0, stagger: 0.08, duration: 0.7, ease: "power4.out" });
```

Gotchas:
- Wrap line-mask reveals: set `overflow: hidden` on the line wrapper so `yPercent: 100` hides cleanly. Add `autoSplit: true` (GSAP 3.13+) to re-split on font load / resize.
- Call `split.revert()` before re-splitting or on unmount to restore original DOM and avoid duplicated nodes.
- Always split AFTER web fonts load (`document.fonts.ready.then(...)`) to prevent wrong line breaks.

### Flip (layout transitions)

Flip records state, lets the DOM change instantly, then animates the visual difference (FLIP technique). Ideal for grid<->list, expanding cards, and reparenting.

```js
const state = Flip.getState(".item");   // 1. capture BEFORE
container.classList.toggle("grid");      // 2. mutate DOM/CSS (instant)
Flip.from(state, {                        // 3. animate the delta
  duration: 0.6, ease: "power2.inOut", stagger: 0.05,
  absolute: true,                         // take items out of flow during move (prevents reflow jitter)
});
```

### Easing quick guide

- `power2/3.out` — entrances (fast then settle)
- `power2.inOut` — moves between two on-screen states
- `back.out(1.7)` — overshoot/pop (number = overshoot amount)
- `elastic.out(1, 0.3)` — bouncy, use sparingly
- `none` — scrubbed scroll tweens
- `steps(n)` — sprite/stepped motion
- Custom cubic-bezier equivalent: `CustomEase.create("x", "M0,0 C0.2,0 0,1 1,1")` (CustomEase is free)

## Performance and cleanup

- Animate `transform` (`x/y/xPercent/scale/rotation`) and `opacity` only — they are GPU-composited and skip layout/paint. Avoid animating `top/left/width/height`.
- Set `will-change: transform` on heavy/pinned elements; remove after.
- Batch many similar scroll reveals with `ScrollTrigger.batch()` instead of one trigger per element.
- After a viewport/content change, call `ScrollTrigger.refresh()`.

SPA / framework cleanup is mandatory — orphaned triggers cause memory leaks and ghost pinning. Use `gsap.context()` (or `useGSAP` from `@gsap/react`):

```js
useEffect(() => {
  const ctx = gsap.context(() => {
    // all gsap + ScrollTrigger code here
  }, rootRef);
  return () => ctx.revert(); // kills tweens, triggers, and reverts inline styles
}, []);
```

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained animation (hero, reveal, loop, micro-scene) the deliverable is **one HTML file that opens directly in a browser** — no build step, no framework, no render pipeline. Match the deliverable to the weight of the work: a single file is the right tier for web motion; don't reach for a bundler when one file does the job.

**Output contract:**
- One `.html` file: GSAP + plugins from CDN, your markup, and the animation in one inline `<script>`.
- All motion on **one master timeline** (`const tl = gsap.timeline()`) — a single playhead you can seek.
- Include the seek harness below so any moment can be frozen for inspection.

**Seek harness — freeze an exact moment for screenshots.** The web parallel of a video player's frame-pin: `?t=N` seeks the master timeline to `N` seconds and pauses, so a screenshot lands on a still, deterministic frame.

```html
<script>
  // ... build your master timeline as `tl` ...
  const t = new URLSearchParams(location.search).get("t");
  if (t !== null) { tl.pause(); tl.seek(parseFloat(t)); }  // frozen at t seconds
  // no ?t → plays normally
  window.__ready = true;            // ready signal for headless wait
  console.log("duration", tl.duration());
</script>
```

**Verify loop — render → freeze → screenshot → check:**
1. Open the file at three moments across the timeline — start, mid, end:
   `…/anim.html?t=0`, `?t=<dur/2>`, `?t=<dur>`. Read `tl.duration()` from the console for the end time.
2. Screenshot each frozen frame.
3. Check both **fidelity** (does it match the brief?) and **artifacts** (clipped text, elements off-canvas, FOUC before fonts load, jank at seams). Output should look intentional and finished.

Any headless screenshot tool works — your agent's browser tool, or Playwright:

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/anim.html?t=1.2" frame-mid.png
```

**Before you finish:**
1. Opens standalone in a browser — no console errors, no missing CDN.
2. All animation on one master timeline; `?t=N` freezes correctly.
3. Screenshotted at start / mid / end — matches the brief, no artifacts.
4. `prefers-reduced-motion` honored (timeline simplified or skipped).
5. Easing is intentional — no accidental `linear` on spatial motion.

A complete runnable template with the harness wired in is in `examples/standalone-template.html`.

## Quick reference

| Goal | API |
|------|-----|
| Sequence with overlap | `tl.from(...).from(..., "-=0.3")` |
| Pin while scrolling | `scrollTrigger:{ pin:true, end:"+=N" }` |
| Scrub to scroll | `scrollTrigger:{ scrub:1, ease:"none" }` |
| Reveal lines of text | `SplitText.create(el,{type:"lines"})` |
| Animate layout change | `Flip.getState` → mutate → `Flip.from` |
| Fast pointer follow | `gsap.quickTo(el,"x",{...})` |
| Kill everything | `ScrollTrigger.getAll().forEach(t=>t.kill())` |

## Reference files

- `references/scrolltrigger-cookbook.md` — pin, scrub, horizontal scroll, snap, `ScrollTrigger.batch()` reveals, parallax, nested triggers, and SPA cleanup patterns with full code.
- `references/scrolltrigger-lenis.md` — full ScrollTrigger + Lenis/Locomotive smooth-scroll sync: canonical wiring, `scrollerProxy`, anchor links, reduced-motion, React (`useGSAP`/`useEffect`), debugging checklist, and symptom→cause table.
- `examples/hero-timeline.js` — a complete, runnable hero entrance timeline with SplitText, staggered reveals, and reduced-motion handling.
- `examples/standalone-template.html` — the deliverable template: self-contained (CDN GSAP), one master timeline, the `?t=N` seek harness for screenshot verification, and reduced-motion handling.
