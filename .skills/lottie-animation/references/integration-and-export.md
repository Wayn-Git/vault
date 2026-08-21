# Lottie Integration & Export (detailed)

## 1. dotLottie-web full setup

```bash
npm i @lottiefiles/dotlottie-web
```

```js
import { DotLottie } from "@lottiefiles/dotlottie-web";

const dotLottie = new DotLottie({
  canvas: document.querySelector("#lottie"),
  src: "/assets/onboarding.lottie",   // .lottie or .json (URL or same-origin path)
  autoplay: true,
  loop: true,
  speed: 1,
  mode: "forward",                    // forward | reverse | bounce | reverse-bounce
  useFrameInterpolation: true,        // smoother than the source frame rate
  renderConfig: {
    autoResize: true,                 // keep the canvas crisp on resize/DPR changes
    devicePixelRatio: window.devicePixelRatio,
  },
});
```

The canvas MUST be a real `<canvas>` element. For responsiveness, size the canvas via CSS and keep `autoResize: true`; the runtime handles the backing store.

### Lifecycle and events

```js
dotLottie.addEventListener("load",     () => console.log(dotLottie.totalFrames, dotLottie.duration));
dotLottie.addEventListener("loadError", (e) => console.error("bad src", e));
dotLottie.addEventListener("play",     () => {});
dotLottie.addEventListener("pause",    () => {});
dotLottie.addEventListener("complete", () => {});       // fires when a non-looping play finishes
dotLottie.addEventListener("loop",     ({ loopCount }) => {});
dotLottie.addEventListener("frame",    ({ currentFrame }) => {});

// always clean up (SPA/unmount)
dotLottie.destroy();
```

`totalFrames`, `duration`, and segment data are only valid AFTER the `load` event — read them there, not synchronously after construction.

### Multi-animation .lottie files

A single `.lottie` can hold several animations:

```js
dotLottie.addEventListener("load", () => {
  console.log(dotLottie.manifest.animations); // list of animation ids
});
dotLottie.loadAnimation("success");           // switch by id without re-fetching
```

## 2. React wrapper

```bash
npm i @lottiefiles/dotlottie-react
```

```jsx
import { DotLottieReact } from "@lottiefiles/dotlottie-react";
import { useState, useEffect } from "react";

function PlayButton() {
  const [dl, setDl] = useState(null);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    if (!dl) return;
    const onComplete = () => setPlaying(false);
    dl.addEventListener("complete", onComplete);
    return () => dl.removeEventListener("complete", onComplete);
  }, [dl]);

  return (
    <DotLottieReact
      src="/play.lottie"
      autoplay
      loop={false}
      dotLottieRefCallback={setDl}     // capture instance for imperative control
      onClick={() => (playing ? dl.pause() : dl.play(), setPlaying((p) => !p))}
      style={{ width: 200, height: 200 }}
    />
  );
}
```

Props mirror the constructor: `src, autoplay, loop, speed, mode, useFrameInterpolation, renderConfig, themeId, segment`.

## 3. Segments and state machines

```js
// Loop only the "loading" portion (frames 30–90), then jump to a success segment.
dotLottie.setSegment(30, 90);
dotLottie.setLoop(true);
dotLottie.play();

function resolveSuccess() {
  dotLottie.setLoop(false);
  dotLottie.setSegment(91, 140);   // success burst
  dotLottie.play();
}
```

Pattern for icon toggles (e.g. like button): keep distinct frame ranges for each state in one file, and `setSegment` + `play` per interaction; listen for `complete` to settle into an idle range.

dotLottie also supports embedded **state machines** (`.lottie` with a `state-machine` definition): `dotLottie.stateMachineLoad("sm_id"); dotLottie.stateMachineStart();` then fire inputs/events — useful for complex interactive icons authored in LottieFiles without writing JS state logic.

## 4. lottie-interactivity (declarative)

```bash
npm i @lottiefiles/lottie-interactivity
```

Works with a `lottie-web`/dotLottie player instance (commonly the `<dotlottie-player>` / `<lottie-player>` web component):

```html
<dotlottie-player id="firstLottie" src="/scroll.lottie" style="width:300px"></dotlottie-player>
<script>
  LottieInteractivity.create({
    player: "#firstLottie",
    mode: "scroll",
    actions: [
      { visibility: [0, 0.3], type: "stop", frames: [0] },
      { visibility: [0.3, 1.0], type: "seek", frames: [0, 120] }, // map scroll → frames 0..120
    ],
  });
</script>
```

Modes:
- `scroll` — tie frames to scroll position / element visibility (the canonical scrolly use).
- `cursor` — drive frames from cursor position over the element (hover scrub).
- `hover` — play on hover, control `loop`/`reset` on leave.
- `click` — advance to the next sync state on each click.
- `chain` — sequence multiple animations.

Use `type: "seek"` to scrub frames, `type: "loop"` / `"play"` / `"stop"` for segment behaviors.

## 5. Manual scroll mapping (full control, no extra lib)

```js
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
let total = 0;
dotLottie.addEventListener("load", () => { total = dotLottie.totalFrames - 1; });

const section = document.querySelector(".scrolly");
function update() {
  const r = section.getBoundingClientRect();
  const scrollable = r.height - window.innerHeight;
  const p = clamp(-r.top / scrollable, 0, 1);
  dotLottie.setFrame(p * total);
}
window.addEventListener("scroll", update, { passive: true });
window.addEventListener("resize", update);
```

Pause when offscreen to save CPU:

```js
new IntersectionObserver(([e]) => e.isIntersecting ? dotLottie.unfreeze() : dotLottie.freeze())
  .observe(canvas);
```

## 6. Runtime theming

### Embedded themes (recommended)

A `.lottie` authored with named color themes:

```js
dotLottie.addEventListener("load", () => {
  console.log(dotLottie.manifest.themes); // available theme ids
  dotLottie.setTheme("dark");             // swap colors with no re-fetch / re-export
});
// or per slot:
dotLottie.setThemeData({ /* theme JSON */ });
```

### Manual color patching (last resort)

```js
const json = await fetch("/icon.json").then((r) => r.json());
// Lottie colors are normalized 0..1 [r,g,b,a] arrays at shapes[].it[].c.k
function recolor(layers, hex) {
  const [r, g, b] = hexToRgb01(hex);
  for (const layer of layers) {
    for (const sh of layer.shapes ?? []) {
      for (const it of sh.it ?? []) {
        if (it.ty === "fl" || it.ty === "st") { it.c.k = [r, g, b, 1]; } // fill / stroke
      }
    }
    if (layer.layers) recolor(layer.layers, hex); // precomps
  }
}
recolor(json.layers, "#ff5500");
new DotLottie({ canvas, data: JSON.stringify(json), autoplay: true });
```

This depends on the exact layer/shape structure and breaks if the file changes — prefer embedded themes, or use the `lottie-web` SVG renderer and target paths with CSS where the markup is stable.

## 7. After Effects → Bodymovin export checklist

Plugin: **Bodymovin** (or LottieFiles plugin). `Window → Extensions → Bodymovin`. Select the comp, set destination, configure, Render.

Pre-export checklist:
1. Comp set to a sensible size and frame rate (24/30/60); avoid huge resolutions — Lottie is vector, the canvas scales.
2. Name layers/comps clearly — names survive into JSON and aid runtime theming/targeting.
3. Convert text you want crisp/animated-by-path to shapes if it uses unsupported text features; otherwise enable "Glyphs"/"Fonts" in Bodymovin settings for live text.
4. Trim the work area to exactly the frames you ship; trailing frames bloat the file.
5. In Bodymovin settings: enable **Compress assets / .lottie** output for the zipped format; enable "Glyphs" if using text; toggle "Standalone"/"Demo" only as needed.
6. Replace embedded raster images with vectors where possible; if rasters are required, they inflate `.json` (consider `.lottie` which bundles them).
7. Test the exported file in the LottieFiles preview AND your target runtime before handoff — renderers differ.

### Unsupported / partially-supported AE features (avoid or rework)

- **Expressions** — not evaluated by runtimes. Bake expression-driven motion to keyframes (Bodymovin can pre-render some) or remove. Heavy-expression rigs are the #1 source of "looks wrong in product".
- **Effects** — most AE effects (blurs, glows, distort, particle systems, CC effects) are NOT supported. Only a small set (e.g. some Gaussian blur, drop shadow, tint, fill via supported attributes) survive, and inconsistently across platforms. Recreate looks with shape layers, gradients, and mattes.
- **3D layers / camera** — not supported; fake depth with 2D scaling/position.
- **Time remapping / nested time stretch** — flaky; pre-compose and bake.
- **Auto-Orient, certain merge-paths modes, some matte combinations** — test explicitly.
- **Audio** — not part of Lottie.
- **Adjustment layers, layer styles (bevel/emboss/inner shadow)** — largely unsupported; convert to shapes/gradients.
- **Track mattes** — alpha/luma mattes generally work but increase cost; flatten when possible.
- **Gradients on strokes / complex gradient feathering** — limited; verify.

Workarounds summary: bake expressions to keyframes, replace effects with native shape/gradient/matte equivalents, flatten precomps, drop rasters, and verify on every target runtime (web/iOS/Android render slightly differently). Keep layer/keyframe count low for performance and file size.

---
Export clean from After Effects and the dotLottie plays light everywhere. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=lottie-animation)** — the AI motion agent for editable, on-brand motion graphics.
