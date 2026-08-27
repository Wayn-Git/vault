# Patterns, profiling, and cost cheat sheet

## Property cost cheat sheet

| Property | Pipeline stage triggered | Verdict |
|---|---|---|
| `transform` | Composite only | Cheap — animate freely |
| `opacity` | Composite only | Cheap — animate freely |
| `filter` | Paint (+composite) | Expensive — avoid animating radius |
| `box-shadow` | Paint (large area) | Expensive — use pseudo + opacity |
| `width`, `height` | Layout + Paint | Avoid — use scale/FLIP |
| `top`, `left`, `right`, `bottom` | Layout + Paint | Avoid — use translate |
| `margin`, `padding` | Layout + Paint | Avoid |
| `border-width` | Layout + Paint | Avoid |
| `color`, `background-color` | Paint | Acceptable in moderation |
| `background-position` | Paint | Prefer translate on child |
| `clip-path` | Paint | Moderate; cheaper than filter |

## Accordion with grid height (no JS measurement)

```html
<button class="acc-trigger" aria-expanded="false">Details</button>
<div class="acc-wrap"><div class="acc-content">…content…</div></div>
```

```css
.acc-wrap {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 280ms cubic-bezier(0.2,0,0,1);
}
.acc-wrap.open { grid-template-rows: 1fr; }
.acc-content { overflow: hidden; min-height: 0; }

@media (prefers-reduced-motion: reduce) {
  .acc-wrap { transition: none; }
}
```

```js
trigger.addEventListener('click', () => {
  const open = wrap.classList.toggle('open');
  trigger.setAttribute('aria-expanded', String(open));
});
```

## FLIP reorder list (batched reads)

```js
function flipReorder(container, mutate) {
  const items = [...container.children];
  const firsts = new Map(items.map((el) => [el, el.getBoundingClientRect()])); // all reads

  mutate(); // e.g. sort/reinsert children

  items.forEach((el) => {
    const first = firsts.get(el);
    const last = el.getBoundingClientRect();
    const dx = first.left - last.left;
    const dy = first.top - last.top;
    if (dx || dy) {
      el.animate(
        [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
        { duration: 300, easing: 'cubic-bezier(0.2,0,0,1)' }
      );
    }
  });
}
```

Reading every rect *before* mutating, and using `animate()` (compositor), keeps a 50-item reorder smooth.

## Just-in-time will-change

```js
el.addEventListener('pointerenter', () => { el.style.willChange = 'transform'; });
el.addEventListener('transitionend', () => { el.style.willChange = 'auto'; });
```

Promote on intent, demote when the animation ends, so layers don't accumulate.

## Reduced-motion gate

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}
```

For JS: `const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;` and skip/shorten animations when true.

## Profiling: prove it's compositor-only

1. Open DevTools > **Performance**. Record while the animation runs.
2. Inspect the flame chart frames during the animation:
   - **Purple "Layout"** or **green "Paint"** bars on every frame → still hitting layout/paint; the animation is not compositor-only. Find the offending property.
   - Only **"Composite Layers"** / GPU work per frame → success.
3. Use **Rendering** tab tools:
   - **Paint flashing** — green flashes show repainted regions; a good transform/opacity animation flashes nothing.
   - **Layer borders** — confirms which elements are on their own compositor layer (watch for too many from over-using `will-change`).
   - **Frame Rendering Stats / FPS meter** — confirm a stable 60/120fps.
4. The **Layers** panel shows layer count and memory; excessive layers indicate `will-change` overuse.

## Parallax without scroll-jank

Drive parallax with `transform: translate3d()` updated inside a single `requestAnimationFrame` loop reading `scrollY` once per frame — never read layout per element per frame.

```js
let ticking = false;
addEventListener('scroll', () => {
  if (!ticking) {
    requestAnimationFrame(() => {
      const y = window.scrollY;              // single read
      layers.forEach((l, i) => {             // writes only
        l.style.transform = `translate3d(0, ${y * (0.1 * (i + 1))}px, 0)`;
      });
      ticking = false;
    });
    ticking = true;
  }
}, { passive: true });
```

`{ passive: true }` lets the browser scroll without waiting on the handler.

---
Stay on transform and opacity, profile the jank away, and motion holds 60fps. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=60fps-animation)** — the AI motion agent for editable, on-brand motion graphics.
