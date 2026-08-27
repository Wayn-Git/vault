---
name: lottie-animation
description: This skill should be used when the user asks to "add a Lottie animation", "play a .lottie or .json animation", "integrate a Bodymovin/After Effects animation on web or mobile", "control Lottie playback / segments", "make a scroll-driven Lottie", "recolor a Lottie at runtime", or "export an AE animation to Lottie". Covers dotLottie/lottie-web integration, playback control, interactivity, theming, and the AE export checklist.
version: 0.1.0
---

# Lottie Animation

The bridge from After Effects to product: vector animation shipped as JSON (or zipped `.lottie`), tiny and resolution-independent, played by a runtime on web, iOS, Android, and React Native. This skill covers integrating, controlling, and exporting Lottie.

## When to use

- Ship a designer's AE animation to web/iOS/Android/React Native
- Looping illustrations, onboarding, empty states, animated icons
- Scroll-driven or interaction-driven vector playback (hover, click, cursor)
- Runtime theming/recoloring instead of re-exporting per brand

## Formats: .json vs .lottie

- `.json` — the raw Bodymovin output. Human-readable, larger.
- `.lottie` — a zipped container (often 60–80% smaller) that can bundle multiple animations, images, and theming. Preferred for shipping. Player: `@lottiefiles/dotlottie-web` (modern, canvas + WASM) supersedes the older `lottie-web`.

Prefer the **dotLottie** runtime for new work; use `lottie-web` only for legacy `.json` + SVG renderer needs.

## Core workflow (web, dotLottie)

```bash
npm i @lottiefiles/dotlottie-web        # vanilla
npm i @lottiefiles/dotlottie-react      # React wrapper
```

Vanilla:

```js
import { DotLottie } from "@lottiefiles/dotlottie-web";

const dotLottie = new DotLottie({
  canvas: document.querySelector("#lottie"),  // a <canvas> element
  src: "/hero.lottie",                         // or .json
  loop: true,
  autoplay: true,
  // speed: 1, mode: "forward" | "reverse" | "bounce", renderConfig: { autoResize: true }
});
```

React:

```jsx
import { DotLottieReact } from "@lottiefiles/dotlottie-react";

function Hero() {
  return <DotLottieReact src="/hero.lottie" loop autoplay style={{ width: 320 }} />;
}
```

Capture the instance to control it:

```jsx
const [dl, setDl] = useState(null);
<DotLottieReact src="/icon.lottie" dotLottieRefCallback={setDl} />;
// dl?.play(); dl?.pause(); dl?.setSpeed(2);
```

## Playback control

```js
dotLottie.play();
dotLottie.pause();
dotLottie.stop();
dotLottie.setSpeed(1.5);
dotLottie.setMode("bounce");        // forward | reverse | bounce | reverse-bounce
dotLottie.setFrame(42);             // jump to a frame
dotLottie.setSegment(30, 90);       // constrain playback to a frame range (e.g. a "loading" loop)
```

Events drive sequencing and UI:

```js
dotLottie.addEventListener("load", () => { /* totalFrames now available */ });
dotLottie.addEventListener("complete", () => { /* non-looping playback finished */ });
dotLottie.addEventListener("frame", ({ currentFrame }) => { /* per-frame */ });
```

State-machine style (e.g. button that plays "checked" segment then idles): play a segment, listen for `complete`, then `setSegment` to the idle loop.

## Scroll-driven Lottie (no GSAP needed)

Map scroll progress (0–1) to a frame. Pause autoplay and drive frames yourself.

```js
const dotLottie = new DotLottie({ canvas, src: "/scroll.lottie", autoplay: false });
let total = 0;
dotLottie.addEventListener("load", () => { total = dotLottie.totalFrames; });

window.addEventListener("scroll", () => {
  const el = canvas.closest(".scrolly");
  const rect = el.getBoundingClientRect();
  const p = clamp(-rect.top / (rect.height - window.innerHeight), 0, 1); // 0..1 through the section
  dotLottie.setFrame(p * (total - 1));
}, { passive: true });

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
```

For richer interaction (hover-to-play, click toggles, cursor-follow) without writing the wiring, use `@lottiefiles/lottie-interactivity`, which maps `scroll`, `hover`, `click`, `play`, and `cursor` modes to frame ranges declaratively.

## Runtime theming / recoloring

Two paths:
- **dotLottie themes**: a `.lottie` can embed named color themes; switch with `dotLottie.setTheme("dark")` / `loadTheme(...)`. Authored in LottieFiles tooling — no re-export to recolor.
- **Manual color override**: load the JSON, walk `layers[].shapes[]` and patch `c.k` color arrays (normalized 0–1 RGBA), then init the player with the modified object. Brittle (depends on layer structure) — prefer themes or CSS-driven SVG-renderer (`lottie-web` `rendererSettings`) when you must restyle by class.

## Mobile runtimes (parity)

- iOS — `lottie-ios` (`LottieAnimationView`): `.play()`, `.currentProgress`, `.play(fromFrame:toFrame:)`.
- Android — `lottie-android` (`LottieAnimationView` / Compose `LottieAnimation`): `setMinAndMaxFrame`, `progress`.
- React Native — `lottie-react-native` (`<LottieView source={...} progress={anim} />`, drive `progress` with `Animated`).

The same `.lottie`/`.json` plays across all; segments and progress concepts match the web API.

## Optimization

- Ship `.lottie` (zipped) over raw `.json`; lazy-load offscreen players and pause when not visible (`IntersectionObserver` → `play`/`pause`).
- Prefer the canvas/WASM dotLottie renderer for many simultaneous animations; SVG renderer (lottie-web) is fine for one crisp icon but costs more DOM for complex files.
- Keep AE comps small: fewer layers/keyframes, no large embedded rasters; flatten precomps where possible. File size tracks keyframe and path complexity, not duration.
- Recolor at runtime (themes) instead of exporting a file per brand/theme.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained Lottie demo (looping illustration, animated icon, empty state) the deliverable is **one HTML file that opens directly in a browser** — the dotLottie/lottie-web runtime from CDN, a `<canvas>`, and your `.lottie`/`.json` (a relative file or a data URL). No build step. One file is the right tier for shipping a player; don't reach for a bundler.

**Output contract:**
- One `.html` file: the runtime via CDN (`@lottiefiles/dotlottie-web`), the canvas, and `autoplay:false` so the frame is yours to drive.
- Include the seek harness so any frame can be frozen for a screenshot.

**Seek harness — freeze an exact frame.** `?t=N` jumps to a frame and holds it so a screenshot lands on a still, deterministic frame. Lottie's playhead is in frames, so stop on the frame directly:

```html
<script>
  const dl = new DotLottie({ canvas, src: "/icon.lottie", autoplay: false });
  dl.addEventListener("load", () => {
    const t = new URLSearchParams(location.search).get("t");
    if (t !== null) dl.setFrame(parseFloat(t));      // freeze on frame N (lottie-web: anim.goToAndStop(N, true))
    else dl.play();
    console.log("totalFrames", dl.totalFrames);       // read for end-frame
    window.__ready = true;
  });
</script>
```

**Verify loop — render → freeze → screenshot → check:** open the file at first / mid / last frame (`?t=0`, `?t=<total/2>`, `?t=<total-1>`; read `totalFrames` from the console), screenshot each, and check **fidelity** (colors/theme correct, segment loops where intended) plus **artifacts** (canvas blurry from missing `autoResize`/DPR, clipped composition, FOUC before the file loads, jank). Any headless tool works:

```bash
npx playwright screenshot --wait-for-timeout=600 "file://$PWD/lottie.html?t=42" frame-mid.png
```

**Before you finish:**
1. Opens standalone — no console errors, CDN runtime and the `.lottie`/`.json` load.
2. `?t=N` (`setFrame`/`goToAndStop`) freezes the correct, deterministic frame.
3. Screenshotted at first / mid / last frame — matches the brief, sharp, no clipping.
4. `prefers-reduced-motion` honored — don't `autoplay` a loop; show a static frame or offer a play control.
5. Easing is intentional — playback speed/segment chosen on purpose, motion baked in AE reads as designed.

## Quick reference

| Goal | Call |
|------|------|
| Play a range | `setSegment(start, end)` |
| Jump to frame | `setFrame(n)` |
| Reverse / bounce | `setMode("reverse"|"bounce")` |
| Scroll-drive | `autoplay:false` + `setFrame(p*totalFrames)` |
| Theme swap | `setTheme("dark")` |
| Know length | `totalFrames` after `load` event |
| Declarative interactivity | `@lottiefiles/lottie-interactivity` |

## Reference files

- `references/integration-and-export.md` — full dotLottie-web + React setup and event/segment control, `lottie-interactivity` mode configs, scroll/cursor patterns, runtime theming details, and the complete After Effects → Bodymovin export checklist with the list of unsupported AE features and how to work around them.
