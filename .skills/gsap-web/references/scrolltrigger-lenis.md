# ScrollTrigger + Lenis / Locomotive smooth-scroll sync

Wire GSAP ScrollTrigger together with Lenis (or Locomotive) smooth scrolling so there is no jitter, no marker drift, no broken pins, and no flipped/laggy scroll direction. Every one of those bugs has the same root cause: two animation loops running independently. Lenis transforms the scroll position on its own `requestAnimationFrame` loop while ScrollTrigger reads scroll on GSAP's ticker — when they tick separately, ScrollTrigger samples a stale position and everything desyncs. The fix is to run one loop: let GSAP's ticker drive Lenis, and tell ScrollTrigger to update on every Lenis scroll.

## The one canonical wiring (Lenis)

This is the entire correct setup. Do not add a separate `requestAnimationFrame` loop for Lenis — that is the most common mistake and the source of nearly all desync.

```js
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

const lenis = new Lenis({
  duration: 1.2,
  smoothWheel: true,
  // do NOT enable Lenis's own rAF; GSAP's ticker drives it (below)
});

// 1. Update ScrollTrigger every time Lenis scrolls
lenis.on('scroll', ScrollTrigger.update);

// 2. Drive Lenis from GSAP's ticker (single shared loop).
//    gsap.ticker time is in SECONDS; Lenis expects MILLISECONDS.
gsap.ticker.add((time) => {
  lenis.raf(time * 1000);
});

// 3. Disable GSAP's lag smoothing so ScrollTrigger never defers/
//    catches up against Lenis (prevents jitter on heavy frames)
gsap.ticker.lagSmoothing(0);
```

Three lines do all the work:

1. `lenis.on('scroll', ScrollTrigger.update)` — ScrollTrigger recomputes positions the instant Lenis moves the page, so triggers/markers/pins track the smoothed scroll exactly.
2. `gsap.ticker.add(time => lenis.raf(time * 1000))` — Lenis advances inside GSAP's loop, guaranteeing both run on the same frame and in the same order. Critical unit conversion: `gsap.ticker` passes seconds, `lenis.raf()` wants milliseconds, so multiply by 1000.
3. `gsap.ticker.lagSmoothing(0)` — disables GSAP's catch-up behavior that, combined with Lenis, causes visible jitter when a frame is slow.

After this, never call `requestAnimationFrame(raf)` for Lenis yourself. If any tutorial code has a standalone `function raf(time){ lenis.raf(time); requestAnimationFrame(raf) }` loop, delete it — it competes with the ticker and reintroduces jitter and direction lag.

## Locomotive Scroll variant

Locomotive needs `scrollerProxy` because it scrolls an inner element, not `window`. The principle is identical (one loop, update ScrollTrigger on scroll), but the proxy maps coordinates:

```js
const locoScroll = new LocomotiveScroll({
  el: document.querySelector('[data-scroll-container]'),
  smooth: true,
});

locoScroll.on('scroll', ScrollTrigger.update);

ScrollTrigger.scrollerProxy('[data-scroll-container]', {
  scrollTop(value) {
    return arguments.length
      ? locoScroll.scrollTo(value, { duration: 0, disableLerp: true })
      : locoScroll.scroll.instance.scroll.y;
  },
  getBoundingClientRect() {
    return { top: 0, left: 0, width: innerWidth, height: innerHeight };
  },
  pinType: document.querySelector('[data-scroll-container]').style.transform
    ? 'transform' : 'fixed',
});

ScrollTrigger.addEventListener('refresh', () => locoScroll.update());
ScrollTrigger.refresh();
```

Every ScrollTrigger then needs `scroller: '[data-scroll-container]'`. Lenis is simpler because it scrolls the real document, so no `scrollerProxy` is needed.

## Pins, refresh, and resize

- Pinned ScrollTriggers work without `scrollerProxy` under Lenis because Lenis scrolls the document body. If pins still jump, ensure no rogue rAF loop exists and that `ScrollTrigger.update` is wired.
- On dynamic content/resize, call `ScrollTrigger.refresh()` after layout settles. With Lenis, also call `lenis.resize()` if container size changes.
- For elements that should *not* be smoothed (e.g. a modal that scrolls natively), mark with `data-lenis-prevent` so Lenis ignores them.

## Anchor links with smooth scroll

Native `<a href="#section">` jumps bypass Lenis (instant jump, then Lenis fights it). Route anchors through `lenis.scrollTo`:

```js
document.querySelectorAll('a[href^="#"]').forEach((a) => {
  a.addEventListener('click', (e) => {
    const id = a.getAttribute('href');
    if (id.length > 1) {
      e.preventDefault();
      lenis.scrollTo(id, { offset: 0 });  // accepts selector, element, or number
    }
  });
});
```

If a sticky header overlaps the target, pass a negative offset or an offset callback:

```js
lenis.scrollTo(targetEl, { offset: -80 }); // 80px sticky header
```

## Reduced-motion gate

Respect `prefers-reduced-motion`: skip smooth scrolling entirely (do not instantiate Lenis, or stop it) and let ScrollTrigger run on native scroll.

```js
const prefersReduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

let lenis;
if (!prefersReduced) {
  lenis = new Lenis({ duration: 1.2 });
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add((time) => lenis.raf(time * 1000));
  gsap.ticker.lagSmoothing(0);
}
// ScrollTrigger animations are defined normally and work with or without Lenis
```

## Cleanup (SPA / React / route changes)

Destroy Lenis and remove the ticker callback on unmount, or stacked loops accumulate:

```js
function setup() {
  const update = (time) => lenis.raf(time * 1000);
  lenis.on('scroll', ScrollTrigger.update);
  gsap.ticker.add(update);
  gsap.ticker.lagSmoothing(0);
  return () => {
    gsap.ticker.remove(update);
    lenis.destroy();
    ScrollTrigger.getAll().forEach((t) => t.kill());
  };
}
```

## Debugging checklist (work top to bottom)

1. **Is there a rogue rAF loop?** Search the codebase for `requestAnimationFrame` near `lenis.raf`. If Lenis is also driven by `gsap.ticker`, delete the standalone loop. Two loops = jitter, lag, flipped feel.
2. **Unit conversion present?** Confirm `lenis.raf(time * 1000)` inside the ticker. Missing `* 1000` makes scroll feel stuck or wildly slow.
3. **Is `ScrollTrigger.update` subscribed?** `lenis.on('scroll', ScrollTrigger.update)` must exist. Without it, markers and triggers drift behind the smoothed position.
4. **Is `lagSmoothing(0)` set?** Without it, heavy frames cause GSAP to "catch up", visible as jitter.
5. **Markers on for diagnosis.** Add `markers: true` to a trigger. If markers sit at the *native* scroll position but content moves with smoothed scroll, the update subscription is missing or a proxy is mis-set.
6. **Pins jumping?** Confirm no proxy is set for Lenis (it scrolls the document). For Locomotive, confirm `pinType` and `scroller` are correct.
7. **After dynamic content / fonts / images load**, call `ScrollTrigger.refresh()`. Stale measurements cause triggers to fire at wrong offsets.
8. **Nested scroll areas** (modals, code blocks) misbehave? Add `data-lenis-prevent` to the scrollable child.
9. **Cleanup on route change?** In SPAs, verify `gsap.ticker.remove(update)`, `lenis.destroy()`, and killing ScrollTriggers — otherwise each navigation stacks another loop.

## Symptom → cause table

| Symptom | Most likely cause |
|---|---|
| General jitter/stutter | Standalone rAF loop + ticker both driving Lenis |
| Scroll stuck / barely moves | Missing `* 1000` unit conversion |
| Markers offset from triggers | `ScrollTrigger.update` not bound to `lenis.on('scroll')` |
| Jitter only on heavy frames | `lagSmoothing(0)` not set |
| Pins jump / break | Proxy wrongly set under Lenis, or wrong `pinType` (Loco) |
| Animations a frame behind | Two loops out of order; consolidate to one ticker |
| Anchor links jump then snap back | Native `#hash` jump not routed via `lenis.scrollTo` |
| Triggers fire at wrong scroll position | Missing `ScrollTrigger.refresh()` after content/layout change |
| Worse after each route change | No cleanup; loops/triggers accumulating |
| Inner scroll container won't scroll | Lenis intercepting; add `data-lenis-prevent` |

## Complete React integration (useGSAP)

```jsx
'use client';
import { useRef } from 'react';
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { useGSAP } from '@gsap/react';

gsap.registerPlugin(ScrollTrigger, useGSAP);

export default function ScrollSection() {
  const root = useRef(null);

  useGSAP(() => {
    const prefersReduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

    let lenis;
    let update;
    if (!prefersReduced) {
      lenis = new Lenis({ duration: 1.2, smoothWheel: true });
      lenis.on('scroll', ScrollTrigger.update);
      update = (time) => lenis.raf(time * 1000);
      gsap.ticker.add(update);
      gsap.ticker.lagSmoothing(0);
    }

    gsap.to('.panel', {
      xPercent: -100,
      ease: 'none',
      scrollTrigger: {
        trigger: '.panel',
        start: 'top top',
        end: '+=1500',
        scrub: true,
        pin: true,
        // markers: true, // enable while debugging
      },
    });

    return () => {
      if (lenis) {
        gsap.ticker.remove(update);
        lenis.destroy();
      }
    };
  }, { scope: root });

  return (
    <div ref={root}>
      <section className="panel">…</section>
    </div>
  );
}
```

`useGSAP` auto-reverts GSAP tweens/ScrollTriggers created in its scope on unmount; the returned function additionally tears down Lenis and the ticker callback so nothing leaks across navigations.

## Plain useEffect equivalent

```jsx
useEffect(() => {
  const lenis = new Lenis({ duration: 1.2 });
  lenis.on('scroll', ScrollTrigger.update);
  const update = (t) => lenis.raf(t * 1000);
  gsap.ticker.add(update);
  gsap.ticker.lagSmoothing(0);

  const ctx = gsap.context(() => {
    // ...ScrollTrigger animations here...
  });

  return () => {
    gsap.ticker.remove(update);
    lenis.destroy();
    ctx.revert();
  };
}, []);
```

## Excluding regions from smooth scroll

```html
<div class="code-block" data-lenis-prevent>…natively scrollable…</div>
```

`data-lenis-prevent` on a scrollable element makes Lenis ignore wheel/touch there, so inner scrolling works normally while the page stays smooth.

---
Sync ScrollTrigger to smooth scroll and the timeline tracks the page perfectly. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=gsap-web)** — the AI motion agent for editable, on-brand motion graphics.
