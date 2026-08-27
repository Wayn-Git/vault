---
name: 60fps-animation
description: This skill should be used when the user asks to "fix janky CSS animation", "make animation 60fps", "stop layout thrashing", "animate width/height/top/left smoothly", "convert animation to transform", "animate box-shadow performantly", "animate height auto", "FLIP animation", or "why is my scroll/hover animation choppy".
version: 0.1.0
---

# Performant Web Animation

Eliminate the #1 cause of janky web animation: animating properties that force the browser to recalculate layout (reflow) or repaint on every frame. The browser renders in stages — **layout → paint → composite**. Animating `width`, `height`, `top`, `left`, `margin`, `padding`, `box-shadow`, or `filter` re-runs layout and/or paint each frame, blocking the main thread. Animating **`transform`** and **`opacity`** runs entirely on the compositor (often the GPU), skipping layout and paint, which is what makes animation smooth at 60/120fps.

## When to use

Use when an animation stutters or drops frames, when a hover/scroll effect feels heavy, when animating size/position/shadow, when a layout change needs to animate smoothly (cards reordering, an element moving between containers), when animating `height: auto`, or when reviewing animation code for performance.

## Core rule: animate only transform and opacity

Map every "expensive" animation to a cheap equivalent.

| Animating (expensive) | Triggers | Replace with (cheap) |
|---|---|---|
| `width` / `height` | Layout + Paint | `transform: scaleX()/scaleY()` (+ FLIP for true size) |
| `top` / `left` / `margin` | Layout + Paint | `transform: translate()` |
| `box-shadow` | Paint | Animate `opacity` of a pseudo-element holding the shadow |
| `filter: blur()` | Paint (heavy) | Cross-fade two layers via `opacity`, or accept sparingly |
| `background-position` | Paint | `transform: translate()` on a child layer |
| `color` / `background` | Paint | Often acceptable; or cross-fade layers |

### Position and size via transform

```css
/* BAD: animates layout every frame */
.box { transition: left 300ms, width 300ms; left: 0; width: 100px; }
.box:hover { left: 200px; width: 200px; }

/* GOOD: compositor-only */
.box {
  transition: transform 300ms ease;
  transform: translateX(0) scaleX(1);
  transform-origin: left center;
}
.box:hover { transform: translateX(200px) scaleX(2); }
```

`scaleX` distorts inner content (text stretches). For true resizing without distortion, use **FLIP**.

## Cheap box-shadow via pseudo-element opacity

Animating `box-shadow` repaints a large blurred region every frame. Instead paint the shadow once on a `::after`, then animate only its `opacity`.

```css
.card { position: relative; }
.card::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  box-shadow: 0 12px 28px rgba(0,0,0,0.35);
  opacity: 0;
  transition: opacity 300ms ease;
  pointer-events: none;
}
.card:hover::after { opacity: 1; }
```

The blurred shadow is rasterized once; hovering only changes a compositor opacity — smooth at any frame rate.

## FLIP: animate layout changes cheaply

FLIP (First, Last, Invert, Play) animates a *layout* change (reorder, resize, move between containers) using only `transform`. Measure where the element was (First) and will be (Last), apply an inverting transform so it visually appears unmoved, then animate the transform back to identity (Play). The DOM ends in its real final layout; the motion is pure compositor work.

```js
function flip(el, mutate) {
  const first = el.getBoundingClientRect();   // First
  mutate();                                    // change the DOM/layout
  const last = el.getBoundingClientRect();     // Last

  const dx = first.left - last.left;
  const dy = first.top - last.top;
  const sx = first.width  / last.width;
  const sy = first.height / last.height;

  el.animate(
    [
      { transformOrigin: 'top left',
        transform: `translate(${dx}px, ${dy}px) scale(${sx}, ${sy})` }, // Invert
      { transformOrigin: 'top left', transform: 'none' },               // Play
    ],
    { duration: 300, easing: 'cubic-bezier(0.2, 0, 0, 1)' }
  );
}

// usage: animate an element moving to a new grid position
flip(card, () => targetContainer.appendChild(card));
```

The Web Animations API `animate()` runs the transform on the compositor. For many elements, batch all `getBoundingClientRect()` reads *before* any mutation (see layout thrashing below).

## Animating height: auto

`height: auto` is not interpolatable historically. Modern and fallback approaches:

```css
/* Modern (Chrome 129+/supporting browsers): opt size keywords into animation */
.panel {
  interpolate-size: allow-keywords;   /* enables animating to/from auto */
  height: 0;
  overflow: clip;
  transition: height 300ms ease;
}
.panel.open { height: auto; }
/* calc-size() also works: height: calc-size(auto, size); */
```

```css
/* Robust fallback today: CSS grid 1fr -> 0fr */
.wrapper {
  display: grid;
  grid-template-rows: 0fr;            /* collapsed */
  transition: grid-template-rows 300ms ease;
}
.wrapper.open { grid-template-rows: 1fr; }
.wrapper > .content { overflow: hidden; min-height: 0; }
```

The grid trick animates the track size (compositor-friendly enough and broadly supported) and needs no JS height measurement. Use `interpolate-size: allow-keywords` / `calc-size(auto, size)` where the target browsers support it; keep the grid technique as the cross-browser default.

## Avoid layout thrashing (batch reads, then writes)

Reading a layout property (`offsetWidth`, `getBoundingClientRect`, `scrollTop`, `getComputedStyle`) after a write forces a *synchronous* reflow. Interleaving reads and writes in a loop ("layout thrashing") can run dozens of forced reflows per frame.

```js
// BAD: read, write, read, write... forces reflow each iteration
items.forEach((el) => {
  const w = el.offsetWidth;          // read (forces layout)
  el.style.width = w * 1.5 + 'px';   // write (invalidates layout)
});

// GOOD: batch all reads, then all writes
const widths = items.map((el) => el.offsetWidth);  // all reads
items.forEach((el, i) => {                          // all writes
  el.style.width = widths[i] * 1.5 + 'px';
});
```

For frame-synced work, read in a `requestAnimationFrame` callback and apply writes; libraries like fastdom formalize this read/write scheduling.

## will-change: use sparingly

`will-change: transform` promotes an element to its own compositor layer ahead of time, avoiding a hitch at animation start. But every promoted layer costs GPU memory, and over-use degrades performance.

```css
.menu { will-change: transform; }   /* only on elements about to animate */
```

Rules: apply just before the animation (e.g. on hover/parent state), remove it after (`will-change: auto`) when idle, never blanket-apply to many elements, and never leave it permanently on large/numerous nodes. A single `transform: translateZ(0)` hack does the same promotion but is harder to undo — prefer `will-change`.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

The deliverable is **one self-contained `.html`** that opens directly in a browser — the markup, the CSS/JS animation, and a freeze harness in one file. For this skill, verification is two-pronged: the frame must look right *and* be cheap to produce (compositor-only).

**Output contract:**
- One `.html`, deps via CDN if any, animation driven by CSS transitions/`@keyframes` or the Web Animations API.
- A freeze mechanism so a screenshot lands on a deterministic frame:
  - CSS `@keyframes` → `?t=N` sets `el.style.animationDelay = (-N)+'s'; el.style.animationPlayState = 'paused'`.
  - WAAPI / JS → keep the animation object and `anim.pause(); anim.currentTime = N*1000`.

**Verify loop — freeze → screenshot, then profile for jank:**
1. Open headless at start / mid / end (`?t=0`, mid, end), screenshot each; confirm the motion is visually correct (no clipped/stretched text from `scaleX`, FLIP lands on the real layout, shadow/height transitions look right).
2. **Confirm it's compositor-only** — the whole point of this skill. Either:
   - DevTools → Performance: record the animation, check there is **no purple "Layout" or green "Paint"** band per frame (only "Composite Layers").
   - Or headless trace: `npx playwright screenshot` for the visual, plus a CDP/`tracing` capture, and assert no `Layout`/`Paint` events fire during the animation window.
3. Watch the FPS/“Frame Rendering Stats” overlay stays at 60 — dropped frames mean an expensive property slipped back in.

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/anim.html?t=0.3" frame.png
```

**Before you finish:**
1. Opens standalone — no console errors.
2. Only `transform` / `opacity` animate per frame; DevTools shows no per-frame Layout/Paint.
3. Screenshotted at start / mid / end — correct, no `scaleX` text distortion, FLIP lands true.
4. Holds 60fps; `will-change` applied just-in-time and removed when idle (no leftover layers).
5. `prefers-reduced-motion` honored.

## Quick reference

| Goal | Do this |
|---|---|
| Move element | `transform: translate()` |
| Resize without distortion | FLIP with `transform` |
| Shadow on hover | Animate `opacity` of shadow pseudo-element |
| Expand to content height | grid `0fr→1fr`, or `interpolate-size: allow-keywords` |
| Many elements moving | Batch `getBoundingClientRect` reads, then writes |
| Smooth animation start | `will-change` just-in-time, remove when idle |
| Verify it's compositor-only | DevTools Performance: no purple "Layout"/green "Paint" per frame |

## Gotchas

- `scaleX/scaleY` stretches text and children; use FLIP when content must stay crisp.
- `transform` percentages are relative to the element's own box, not the parent — different from `left: %`.
- Overusing `will-change` or `translateZ(0)` creates too many layers and *hurts* performance; promote only what animates.
- `filter` and `backdrop-filter` are compositor-related but still expensive; animate their presence via opacity cross-fades rather than animating the blur radius.
- The grid `1fr→0fr` content must have `overflow: hidden` and `min-height: 0` or it won't collapse.
- Always gate non-essential motion behind `@media (prefers-reduced-motion: reduce)`.

## Reference files

- `references/patterns-and-profiling.md` — full runnable examples (accordion, reorder list, parallax), DevTools profiling walkthrough to confirm compositor-only frames, reduced-motion patterns, and a property-cost cheat sheet.
