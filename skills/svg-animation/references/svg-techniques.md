# SVG Animation Techniques (detailed)

## 1. Stroke draw-on: the math

`stroke-dasharray` defines a dash pattern; `stroke-dashoffset` shifts where the pattern starts. Set the dash equal to the whole path length and offset it by that same length → the visible dash is pushed entirely off the path (invisible). Animating offset to 0 slides the dash into view, revealing the stroke progressively.

```
visible fraction = 1 - (dashoffset / pathLength)
```

So offset = length → 0% drawn; offset = 0 → 100% drawn; offset = length/2 → 50% drawn (useful for scroll mapping: `offset = length * (1 - progress)`).

### getTotalLength gotchas

```js
const path = document.querySelector("#sig");
const len = path.getTotalLength();           // returns user units of the path geometry
path.style.strokeDasharray = len;
path.style.strokeDashoffset = len;
requestAnimationFrame(() => {                 // next frame so the transition has a start value
  path.style.transition = "stroke-dashoffset 1.6s ease";
  path.style.strokeDashoffset = "0";
});
```

- `getTotalLength()` measures the path's own coordinate system, ignoring CSS transforms/scaling — which is what you want for dasharray.
- It only works on geometry elements (`path, line, polyline, polygon, circle, ellipse, rect`). For `<text>` draw-on you must convert text to paths first.
- Rounding: browsers can clip the last sub-pixel; pad slightly (`len + 1`) if the end never fully closes.
- Compound paths (multiple `M` subpaths in one `d`) draw all subpaths simultaneously. Split into separate `<path>`s with staggered `animation-delay` for sequential drawing.

### No-JS normalization with pathLength

`pathLength="1"` tells the browser to treat the path's length as exactly 1, regardless of real geometry. Then dash math is unit-free:

```svg
<path d="..." pathLength="1" fill="none" stroke="#111"
      style="stroke-dasharray:1; stroke-dashoffset:1; animation:draw 1.4s ease forwards"/>
```
```css
@keyframes draw { to { stroke-dashoffset: 0; } }
```

This is the cleanest pure-CSS draw-on and avoids hardcoding measured lengths that break when the path is edited. Use `pathLength="100"` if you prefer to think in percentages.

### Scroll-driven draw-on (no library, via offset)

```js
const len = path.getTotalLength();
path.style.strokeDasharray = len;
function onScroll() {
  const p = Math.min(1, Math.max(0, scrollProgress())); // 0..1
  path.style.strokeDashoffset = len * (1 - p);
}
document.addEventListener("scroll", onScroll, { passive: true });
```

## 2. Morphing

### Why naive morphs break

Path interpolation walks the `d` command list of A and B in lockstep. If A has 4 cubic curves and B has 7, or A uses `L` where B uses `C`, the browser/animator either refuses or produces garbage. Fixes: match commands by hand, or use a library that resamples.

### GSAP MorphSVG (best for arbitrary shapes)

```js
import gsap from "gsap";
import { MorphSVGPlugin } from "gsap/MorphSVGPlugin";
gsap.registerPlugin(MorphSVGPlugin);

// any shape -> path so it can morph
MorphSVGPlugin.convertToPath("#circ, #star");

gsap.to("#circ", {
  duration: 0.9, ease: "power2.inOut",
  morphSVG: { shape: "#star", shapeIndex: "auto", type: "rotational" },
});
```

- `shapeIndex` rotates the starting point mapping to minimize twisting; `"auto"` lets GSAP pick, or pass a number to tune.
- `type: "rotational"` interpolates angles/lengths instead of raw coordinates — usually smoother for organic morphs.
- `map: "size" | "position" | "complexity"` changes how sub-paths in compound shapes are matched.

### Flubber (standalone, framework-friendly)

```js
import { interpolate, separate, combine } from "flubber";

// 1 -> 1 shape
const lerp = interpolate(pathA, pathB, { maxSegmentLength: 2 });

// splitting one shape into many (or vice versa)
const split = separate(oneShape, [shape1, shape2, shape3], { single: true });
```

Drive `lerp(t)` with any tween/`requestAnimationFrame`, or inside Framer Motion:

```jsx
import { motion, useMotionValue, useTransform, animate } from "motion/react";
const progress = useMotionValue(0);
const d = useTransform(progress, [0, 1], [0, 1], { clamp: false });
const path = useTransform(d, (v) => interpolate(A, B)(v));
// animate(progress, 1, { duration: 0.6 }) then <motion.path d={path} />
```

Use Flubber when you can't add GSAP or need React-native value plumbing; use MorphSVG for the highest-quality mapping and convenience.

### Hand-authored icon toggle (hamburger ↔ close) — no morph library

When you control both shapes, give them identical structure and animate transforms instead of `d`:

```svg
<svg viewBox="0 0 24 24" class="menu" aria-label="Menu">
  <line class="top" x1="3" y1="6"  x2="21" y2="6"/>
  <line class="mid" x1="3" y1="12" x2="21" y2="12"/>
  <line class="bot" x1="3" y1="18" x2="21" y2="18"/>
</svg>
```
```css
.menu line { stroke:#111; stroke-width:2; transition: transform .25s ease, opacity .2s ease;
  transform-origin: center; transform-box: fill-box; }
.menu.open .top { transform: translateY(6px) rotate(45deg); }
.menu.open .mid { opacity: 0; }
.menu.open .bot { transform: translateY(-6px) rotate(-45deg); }
```

`transform-box: fill-box` makes `transform-origin: center` resolve to the element's own bounding box — essential for SVG rotation; without it the origin is the SVG viewport origin.

## 3. Motion along a path — details

### GSAP MotionPath

```js
gsap.to("#dot", {
  duration: 5, repeat: -1, ease: "none",
  motionPath: {
    path: "#route",
    align: "#route",          // coordinates relative to the path element
    alignOrigin: [0.5, 0.5],  // pin the object's center to the path
    autoRotate: true,         // or a number to add a constant offset angle
    start: 0, end: 1,         // animate a sub-segment, e.g. 0.2..0.8
  },
});
```

Convert a series of points into a smooth path: `MotionPathPlugin.convertToPath(...)`, or pass `motionPath: [{x:0,y:0},{x:100,y:50},...]` and GSAP draws a curve through them.

### CSS offset-path (declarative, modern)

```css
.dot {
  offset-path: path("M10,80 C40,10 120,10 150,80");
  offset-rotate: auto;                 /* face direction of travel */
  animation: travel 3s linear infinite;
}
@keyframes travel { to { offset-distance: 100%; } }
```

Newer syntax also accepts `offset-path: url(#route)` referencing a `<path>` id and shapes like `ray()`. Good support in evergreen browsers; no JS needed.

### SMIL animateMotion

Self-contained inside the SVG; use `rotate="auto"` and `<mpath href="#id"/>`. Best for portable icon assets where you don't want external CSS/JS. Avoid when you need scroll-sync or broad legacy support.

## 4. SMIL vs CSS vs JS — tradeoffs

| Axis | SMIL | CSS | JS (GSAP/WAAPI) |
|------|------|-----|-----------------|
| Bundle cost | none (inline) | none | library (GSAP ~JS) |
| Works in `<img>` SVG | yes | yes (internal) | no |
| Reach (legacy IE/Edge) | no | partial | yes |
| Scroll/scrub sync | hard | hard | easy |
| Morph mismatched paths | no | no | yes (MorphSVG/Flubber) |
| Timeline orchestration | limited | limited | full |
| Animate `d`/gradients/filters | yes | partial | yes |

Default: CSS for simple declarative effects, GSAP for anything coordinated/scrubbable/morphing, SMIL only for portable self-animating assets in evergreen targets.

## 5. SVGO config tuned for animation

Aggressive SVGO defaults will strip the very things you animate. Use a config like:

```js
// svgo.config.js
module.exports = {
  multipass: true,
  plugins: [
    { name: "preset-default", params: { overrides: {
      removeViewBox: false,        // keep responsive scaling
      cleanupIds: false,           // DO NOT rename ids referenced by CSS/JS/SMIL/gradients
      mergePaths: false,           // keep sub-paths separate for staggered draw-on
      convertShapeToPath: false,   // keep <circle>/<rect> if SMIL/CSS targets them
      removeHiddenElems: false,    // keep elements you toggle visible via animation
      inlineStyles: false,         // preserve class hooks
    } } },
    { name: "removeDimensions" },  // drop width/height, keep viewBox -> fluid scaling
    { name: "prefixIds" },         // namespace ids if inlining many SVGs to avoid id collisions
  ],
};
```

If multiple inlined SVGs share gradient/filter ids, id collisions make the LAST definition win for everyone — `prefixIds` (or unique authoring) prevents this classic bug.

## 6. Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  .path { animation: none; stroke-dashoffset: 0; } /* show final drawn state instantly */
}
```

For looping decorative SVG (spinners, ambient gradients), pause or hide them under reduced-motion; for functional icon toggles, keep the state change but drop the easing duration.

---
Pick the right method per shape and SVG draws, morphs, and travels smoothly. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=svg-animation)** — the AI motion agent for editable, on-brand motion graphics.
