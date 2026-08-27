---
name: svg-animation
description: This skill should be used when the user asks to "animate an SVG", "make a line draw itself on", "do a stroke draw-on / signature animation", "morph one shape into another", "move an element along a path", "animate an icon/logo", or "animate an SVG gradient or filter". Covers stroke-dashoffset draw-on, path morphing, motion-along-path, and animated icons/gradients/filters via CSS, SMIL, and GSAP.
version: 0.1.0
---

# SVG Animation

Crisp, lightweight, infinitely scalable vector motion — ideal for icons, illustrations, logos, and data marks. SVG can be animated three ways: CSS (declarative, simple), SMIL (`<animate>` inside the SVG), and JS (GSAP/Web Animations, for control and morphing). Choose per task; the techniques below say which.

## When to use

- Stroke "draw-on" of icons, illustrations, signatures, maps
- Shape/path morphing and animated icon state changes (menu ↔ close, play ↔ pause)
- Moving an element along a path (motion path)
- Animated gradients, filters (glow, displacement), and animated logos

## Core techniques

### Stroke draw-on (the staple)

Draw the dash array as long as the path, offset it fully (invisible), then animate the offset to 0.

```css
.path {
  stroke-dasharray: var(--len);
  stroke-dashoffset: var(--len);
  animation: draw 1.4s ease forwards;
}
@keyframes draw { to { stroke-dashoffset: 0; } }
```

Getting the length:
- JS (most reliable): `const len = path.getTotalLength(); path.style.setProperty("--len", len);`
- No-JS trick: set `pathLength="1"` on the `<path>`, then `stroke-dasharray: 1; stroke-dashoffset: 1;` and animate to `0`. This normalizes any path to a 0–1 length so no measurement is needed.

Reverse (erase) by animating offset from 0 back to `len`. Stagger multiple paths with `animation-delay`. Direction of drawing follows the path's point order; reverse it in the editor or negate the offset sign if it draws "backwards".

### Morphing one path into another

Paths interpolate point-by-point, so a naive morph requires both `d` attributes to have the **same number and type of commands**. Two robust approaches:

- **GSAP MorphSVG** (free as of GSAP 3.12) — handles mismatched point counts automatically and finds a good mapping:

```js
gsap.registerPlugin(MorphSVGPlugin);
gsap.to("#start", { morphSVG: "#end", duration: 0.8, ease: "power2.inOut" });
// Convert any shape to a morph-able path:
MorphSVGPlugin.convertToPath("circle, rect, ellipse, line, polygon");
```

- **Flubber** (small standalone lib) — generates interpolators without GSAP, good with React/Framer Motion:

```js
import { interpolate } from "flubber";
const interpolator = interpolate(pathA, pathB, { maxSegmentLength: 2 });
// interpolator(0) === pathA, interpolator(1) === pathB; feed t into a tween.
```

For hand-authored morphs (icon toggles), keep both paths with identical command structure and animate `d` directly via Web Animations or CSS (`d` is animatable in modern browsers via `path("...")`).

### Motion along a path

- **GSAP MotionPath** (preferred — control, alignment, scrub):

```js
gsap.registerPlugin(MotionPathPlugin);
gsap.to("#rocket", {
  duration: 4, repeat: -1, ease: "none",
  motionPath: { path: "#track", align: "#track", autoRotate: true, alignOrigin: [0.5, 0.5] },
});
```

`autoRotate: true` orients the object to the path tangent; `align` makes coordinates relative to the path element.

- **SMIL** (no JS):

```svg
<path id="track" d="M10,80 C40,10 120,10 150,80" fill="none"/>
<circle r="6" fill="#3b82f6">
  <animateMotion dur="3s" repeatCount="indefinite" rotate="auto">
    <mpath href="#track"/>
  </animateMotion>
</circle>
```

- **CSS** offset-path (modern, declarative): `offset-path: path("M10,80 C..."); animation: move 3s linear infinite;` with `@keyframes move { to { offset-distance: 100%; } }` and `offset-rotate: auto`.

### Animated gradients and filters

Gradients: animate `gradientTransform` or stop offsets. A sheen sweep:

```svg
<linearGradient id="sheen">
  <stop offset="0%"  stop-color="#fff" stop-opacity="0"/>
  <stop offset="50%" stop-color="#fff" stop-opacity=".8"/>
  <stop offset="100%" stop-color="#fff" stop-opacity="0"/>
  <animateTransform attributeName="gradientTransform" type="translate"
    from="-1 0" to="1 0" dur="2s" repeatCount="indefinite"/>
</linearGradient>
```

Filters: animate `feDisplacementMap` `scale` for gooey/wobble, `feGaussianBlur` `stdDeviation` for focus pulls, or `feColorMatrix`/`feFlood` for glow. Filters are paint-heavy — animate sparingly and prefer `transform`/`opacity` where possible.

## Implementation choice (pick fast)

| Need | Use |
|------|-----|
| Single declarative draw/fade | CSS |
| Self-contained, no JS bundle | SMIL (`<animate*>` in the SVG) |
| Coordinated, scrubbable, scroll-tied | GSAP |
| Mismatched-point morph | GSAP MorphSVG or Flubber |
| Path following with rotation | GSAP MotionPath / CSS offset-path |

SMIL caveat: not supported in IE/old Edge and historically deprecation-flagged; for max reach or scroll-syncing, prefer CSS or JS. SMIL is still fine for self-contained icon assets in evergreen browsers.

## Authoring and optimization

- Build/clean with **SVGO**: keep `viewBox`, drop editor metadata, but disable `cleanupIds`/`removeViewBox` and any plugin that renames IDs you reference from CSS/JS/SMIL. Disable `mergePaths` and `convertShapeToPath` if you animate individual sub-paths or shapes.
- Inline the SVG in the DOM (not `<img src>`) so CSS/JS can reach its internals; `<img>`-embedded SVG can only self-animate via internal SMIL/CSS.
- Set explicit `viewBox` and avoid fixed `width`/`height` so the asset scales fluidly.
- For draw-on, ensure paths are actual strokes (`fill:none; stroke:...`), not filled outlines — dashoffset only affects strokes.
- Respect `prefers-reduced-motion`: gate looping/large motion; keep a static final state.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained icon/logo/draw-on the deliverable is **one HTML file that opens directly in a browser** — inline the SVG in the markup, drive the animation with one mechanism, no build step. One file is the right tier for a vector asset; don't reach for a bundler.

**Output contract:**
- One `.html` file: inline `<svg>`, plus CSS `@keyframes` / a `<script>` with GSAP from CDN / SMIL `<animate*>` — pick one driver.
- Include the seek harness matching that driver so any moment can be frozen for a screenshot.

**Seek harness — freeze an exact moment.** `?t=N` seeks and pauses so a screenshot lands on a still frame. Use the mechanism that matches how the SVG animates:

```html
<script>
  const t = new URLSearchParams(location.search).get("t");
  if (t !== null) {
    const N = parseFloat(t);
    // SMIL: pause the SVG's own clock and scrub it
    const svg = document.querySelector("svg");
    svg.pauseAnimations(); svg.setCurrentTime(N);
    // CSS @keyframes draw-on: el.style.animationDelay=(-N)+"s"; el.style.animationPlayState="paused";
    // GSAP timeline: tl.pause(); tl.seek(N);
  }
  window.__ready = true;
</script>
```

**Verify loop — render → freeze → screenshot → check:** open the file at start / mid / end (`?t=0`, `?t=<dur/2>`, `?t=<dur>`), screenshot each, and check **fidelity** (stroke draws in the right direction, morph endpoints clean) plus **artifacts** (path clipped by `viewBox`, stroke vanishing from a stale dashoffset, FOUC, jank at the morph seam). Any headless tool works:

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/icon.html?t=0.7" frame-mid.png
```

**Before you finish:**
1. Opens standalone — no console errors, inline SVG reachable, CDN (if any) loads.
2. The seek mechanism for your driver freezes a deterministic frame.
3. Screenshotted at start / mid / end — matches the brief, no clipping or off-`viewBox` strokes.
4. `prefers-reduced-motion` honored — looping/large motion gated, static final state kept.
5. Easing is intentional — `ease`/GSAP ease chosen on purpose, no accidental `linear` draw-on.

## Reference files

- `references/svg-techniques.md` — full dashoffset math and `getTotalLength` gotchas, the `pathLength="1"` normalization, GSAP MorphSVG vs Flubber decision guide with code, an icon-toggle morph (hamburger↔close), MotionPath/offset-path details, SMIL-vs-CSS-vs-JS tradeoffs, and an SVGO config tuned for animation.
