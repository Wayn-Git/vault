# ScrollTrigger Cookbook

Runnable patterns for GSAP 3.12+. Register first:

```js
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
gsap.registerPlugin(ScrollTrigger);
```

## 1. Pin a section and scrub a timeline through it

The most common scrollytelling pattern: hold a section fixed and drive a multi-step timeline with scroll.

```js
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: ".story",
    start: "top top",
    end: "+=3000",   // total scroll distance the pin lasts
    pin: true,
    scrub: 1,
    anticipatePin: 1, // reduces a 1-frame jump when pinning fast scroll
  },
});

tl.from(".story .step-1", { autoAlpha: 0, y: 60 })
  .from(".story .step-2", { autoAlpha: 0, y: 60 })
  .to(".story .bg", { scale: 1.2, ease: "none" }, 0); // runs across whole timeline
```

Tips:
- Each tween occupies an equal slice of the pinned distance unless you set durations/positions.
- `pinSpacing: true` (default) adds padding so content below does not jump. Set `false` only when overlaying.
- If the pinned element is inside a transformed/`overflow` ancestor, pinning breaks — pin a top-level element or set `pinReparent: true`.

## 2. Horizontal scroll (panels move sideways as the page scrolls vertically)

```html
<section class="h-wrap"><div class="track">
  <div class="panel">1</div><div class="panel">2</div><div class="panel">3</div>
</div></section>
```

```css
.track { display: flex; width: max-content; }
.panel { width: 100vw; height: 100vh; flex: 0 0 100vw; }
```

```js
const track = document.querySelector(".track");
gsap.to(track, {
  x: () => -(track.scrollWidth - window.innerWidth), // function = recalculated on refresh
  ease: "none",
  scrollTrigger: {
    trigger: ".h-wrap",
    pin: true,
    scrub: 1,
    end: () => "+=" + (track.scrollWidth - window.innerWidth),
    invalidateOnRefresh: true, // re-run the x function on resize
  },
});
```

`invalidateOnRefresh: true` plus function-based values is the correct way to stay responsive.

## 3. Snap to sections

```js
gsap.to(".sections", {
  scrollTrigger: {
    trigger: ".sections",
    pin: true,
    scrub: 1,
    end: "+=4000",
    snap: {
      snapTo: 1 / 4,        // 5 evenly spaced points (labels also possible: "labels")
      duration: { min: 0.2, max: 0.6 },
      delay: 0.05,
      ease: "power1.inOut",
    },
  },
});
```

To snap to timeline labels: build a labeled timeline and use `snap: "labelsDirectional"`.

## 4. Batch reveals (performant many-element fade-in)

Instead of creating one ScrollTrigger per card (expensive at scale), batch them:

```js
ScrollTrigger.batch(".card", {
  start: "top 85%",
  onEnter: (els) =>
    gsap.from(els, { autoAlpha: 0, y: 40, stagger: 0.12, overwrite: true }),
  onLeaveBack: (els) =>
    gsap.to(els, { autoAlpha: 0, y: 40, stagger: 0.12, overwrite: true }),
});
```

Set the initial hidden state to avoid a flash before JS runs: `gsap.set(".card", { autoAlpha: 0 })`.

## 5. Parallax layers

```js
gsap.utils.toArray(".parallax").forEach((layer) => {
  const depth = layer.dataset.depth || 0.3; // 0 = static, 1 = scrolls with page
  gsap.to(layer, {
    yPercent: -depth * 100,
    ease: "none",
    scrollTrigger: { trigger: layer.parentElement, scrub: true, start: "top bottom", end: "bottom top" },
  });
});
```

## 6. Linked timelines / containerAnimation (triggers inside horizontal scroll)

To trigger animations off elements that move horizontally inside a pinned horizontal scroller, pass the horizontal tween as `containerAnimation`:

```js
const scrollTween = gsap.to(track, { x: -2000, ease: "none",
  scrollTrigger: { trigger: ".h-wrap", pin: true, scrub: 1, end: "+=2000" } });

gsap.from(".panel-2 .title", {
  autoAlpha: 0, y: 50,
  scrollTrigger: { trigger: ".panel-2 .title", containerAnimation: scrollTween, start: "left center" },
});
```

Note `start: "left center"` uses horizontal keywords because the trigger moves horizontally.

## 7. Refresh on dynamic content

Images and lazy content change layout after triggers are computed. Refresh when ready:

```js
window.addEventListener("load", () => ScrollTrigger.refresh());
imagesLoaded(document.body, () => ScrollTrigger.refresh()); // if using imagesLoaded lib
```

For accordions/tabs that change height, call `ScrollTrigger.refresh()` after the layout settles.

## 8. SPA / React cleanup (critical)

Orphaned ScrollTriggers cause ghost pins, leaks, and stacking bugs on route changes. Always scope and revert.

React with `@gsap/react`:

```jsx
import { useGSAP } from "@gsap/react";

function Section() {
  const root = useRef(null);
  useGSAP(() => {
    gsap.from(".item", {
      autoAlpha: 0, y: 40, stagger: 0.1,
      scrollTrigger: { trigger: ".item", start: "top 80%" },
    });
  }, { scope: root }); // auto-reverts on unmount
  return <div ref={root}>...</div>;
}
```

Plain SPA / manual:

```js
const ctx = gsap.context(() => { /* all gsap code */ }, rootEl);
// on teardown / route leave:
ctx.revert();
```

Nuclear option (e.g. global router hook): `ScrollTrigger.getAll().forEach((t) => t.kill());`

## Debugging checklist

- Triggers fire at wrong scroll position → likely created before images loaded; call `ScrollTrigger.refresh()`.
- Pinned element jumps to top-left → it has a transformed/`will-change`/`overflow:hidden` ancestor; pin higher up.
- Animation plays once then never resets → set appropriate `toggleActions` or use `scrub`.
- Horizontal scroll not responsive → use function-based `x`/`end` + `invalidateOnRefresh: true`.
- Markers misaligned → leftover triggers from previous render; ensure cleanup runs.
