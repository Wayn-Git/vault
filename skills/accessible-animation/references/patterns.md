# Reduced Motion — Detailed Patterns

## Reusable wrapper: animate with motion preference

A single helper that picks a "full" or "reduced" variant and stays live-reactive.

```js
const REDUCE = '(prefers-reduced-motion: reduce)';

export function createMotionController() {
  const mq = window.matchMedia(REDUCE);
  const listeners = new Set();
  mq.addEventListener('change', () => listeners.forEach((fn) => fn(mq.matches)));

  return {
    get reduced() { return mq.matches; },
    subscribe(fn) { listeners.add(fn); fn(mq.matches); return () => listeners.delete(fn); },
    // Pick a variant object: { full, reduced }
    pick(variants) { return mq.matches ? variants.reduced : variants.full; },
  };
}

// Usage
const motion = createMotionController();
const opts = motion.pick({
  full:    { translateY: ['40px', '0'], opacity: [0, 1], duration: 500 },
  reduced: { opacity: [0, 1], duration: 150 },
});
```

## GSAP: full matchMedia with teardown

`gsap.matchMedia()` automatically reverts (kills tweens, restores inline styles) when a condition stops matching, so toggling the OS setting cleans up correctly.

```js
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
gsap.registerPlugin(ScrollTrigger);

const mm = gsap.matchMedia();

mm.add({
  motionOK: '(prefers-reduced-motion: no-preference)',
  motionReduce: '(prefers-reduced-motion: reduce)',
}, (ctx) => {
  const { motionOK } = ctx.conditions;

  if (motionOK) {
    // Tier 1 parallax — only when allowed
    gsap.to('.parallax-layer', {
      yPercent: -30,
      ease: 'none',
      scrollTrigger: { trigger: '.section', scrub: true },
    });
    gsap.from('.card', {
      y: 60, opacity: 0, stagger: 0.1,
      scrollTrigger: { trigger: '.grid', start: 'top 80%' },
    });
  } else {
    // Reduced: no parallax at all; cards cross-fade in place (Tier 2)
    gsap.from('.card', {
      opacity: 0, duration: 0.15, stagger: 0.03,
      scrollTrigger: { trigger: '.grid', start: 'top 80%' },
    });
  }

  return () => { /* optional extra cleanup; mm reverts tweens automatically */ };
});

// Tear everything down (e.g. SPA route change)
// mm.revert();
```

## Framer Motion: MotionConfig for app-wide reduction

`MotionConfig reducedMotion="user"` makes every child `motion` component automatically drop transform/layout animations while keeping opacity. Set it once at the root.

```jsx
import { MotionConfig, motion } from 'framer-motion';

export function App() {
  return (
    <MotionConfig reducedMotion="user">
      {/* All descendant motion components honor the OS setting */}
      <motion.section
        initial={{ opacity: 0, y: 80 }}   // y is auto-dropped when reduced
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
      />
    </MotionConfig>
  );
}
```

For per-component control, Framer's own hook:

```jsx
import { useReducedMotion } from 'framer-motion';

function Hero() {
  const reduced = useReducedMotion();
  const variants = reduced
    ? { hidden: { opacity: 0 }, show: { opacity: 1, transition: { duration: 0.15 } } }
    : { hidden: { opacity: 0, scale: 0.9 }, show: { opacity: 1, scale: 1, transition: { duration: 0.8 } } };
  return <motion.div variants={variants} initial="hidden" animate="show" />;
}
```

## Lenis: start/stop on live toggle

Lenis hijacks scroll (Tier 1). Destroy it when reduced motion turns on, recreate when it turns off.

```js
import Lenis from 'lenis';

let lenis = null;
let rafId = null;

function startLenis() {
  if (lenis) return;
  lenis = new Lenis({ smoothWheel: true });
  const loop = (t) => { lenis.raf(t); rafId = requestAnimationFrame(loop); };
  rafId = requestAnimationFrame(loop);
}
function stopLenis() {
  if (!lenis) return;
  cancelAnimationFrame(rafId);
  lenis.destroy();
  lenis = null;
  // Restore native scroll so the page is still usable
  document.documentElement.style.removeProperty('scroll-behavior');
}

const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
function sync() { mq.matches ? stopLenis() : startLenis(); }
mq.addEventListener('change', sync);
sync();
```

## Auto-carousel / marquee with a pause control (WCAG 2.2.2)

Auto-playing motion longer than 5s needs a pause/stop control regardless of the media query. Reduced-motion users get it stopped by default; everyone gets the control.

```html
<div class="marquee" data-playing="true">
  <button class="marquee__toggle" aria-pressed="false">Pause</button>
  <ul class="marquee__track"><!-- items --></ul>
</div>
```

```css
.marquee__track { animation: scroll-left 20s linear infinite; }
.marquee[data-playing="false"] .marquee__track { animation-play-state: paused; }
@media (prefers-reduced-motion: reduce) {
  .marquee__track { animation-play-state: paused; } /* paused by default */
}
@keyframes scroll-left { to { transform: translateX(-50%); } }
```

```js
const root = document.querySelector('.marquee');
const btn = root.querySelector('.marquee__toggle');
// Respect the OS setting for the initial state
if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  root.dataset.playing = 'false';
  btn.textContent = 'Play';
  btn.setAttribute('aria-pressed', 'true');
}
btn.addEventListener('click', () => {
  const playing = root.dataset.playing === 'true';
  root.dataset.playing = String(!playing);
  btn.textContent = playing ? 'Play' : 'Pause';
  btn.setAttribute('aria-pressed', String(playing));
});
```

## Tier classification audit checklist

For each animation in the codebase, ask in order:

1. Is it essential to meaning (e.g. a progress bar, a diagram step)? -> Tier 3, keep.
2. Does a large area move, scale, spin, or imply depth/self-motion (parallax, zoom hero, slide-over)? -> Tier 1, remove under reduce.
3. Is it a small entrance with displacement (pop-in, slide-up)? -> Tier 2, replace displacement with a ≤200ms opacity fade.
4. Is it only opacity/color/focus? -> Tier 3, keep (shorten if >300ms).
5. Does it auto-play >5s (carousel, marquee, looping video bg)? -> Add a pause control (2.2.2) on top of any tier handling.

## Testing

- macOS: System Settings > Accessibility > Display > Reduce motion.
- Windows 11: Settings > Accessibility > Visual effects > Animation effects (off).
- Chrome DevTools: Rendering panel > "Emulate CSS media feature prefers-reduced-motion".
- Verify the `change` listener: toggle the OS setting with the page open and confirm motion stops without reload.
- Confirm `transitionend`/`animationend`-dependent flows still complete (the `0.01ms` rule).

---
Honor prefers-reduced-motion at every tier and motion stays inclusive by default. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=accessible-animation)** — the AI motion agent for editable, on-brand motion graphics.
