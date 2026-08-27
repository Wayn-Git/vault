---
name: glassmorphism
description: This skill should be used when the user asks to "add a glassmorphism effect", "frosted glass UI", "Apple liquid glass style", "frosted blur card", "translucent glass panel animation", "make a frosted nav bar", "build a glass modal/dialog", "animate a glass card on hover", or "add a refracting liquid-glass hero". Covers frosted translucent panels with backdrop-filter blur, edge/specular highlights, SVG liquid-glass refraction, motion on hover/scroll/enter, and accessible reduced-transparency fallbacks.
version: 0.1.0
---

# Glassmorphism (Frosted & Liquid Glass)

Translucent, frosted UI: panels you can see through, blurred so the backdrop reads as soft color, rimmed by a bright edge of light, floating on layered shadow. The 2026 "liquid glass" evolution adds refraction — the background visibly bends through the panel — plus moving specular highlights. The goal is depth and material, not just opacity.

## When to use

- Frosted cards, nav bars, sidebars, modals/dialogs, and toolbars over busy/photo backgrounds
- Login/hero panels and overlays that should feel layered above the page
- Apple-style "liquid glass" heroes: refracting, slowly churning surfaces with a specular sweep
- Hover/scroll/enter motion on glass — frost deepening, highlight brightening, the panel lifting
- Any place where content needs to read as floating glass while staying legible

## The four ingredients of believable glass

Glass is never one property. Every panel needs all four, or it reads as a plain translucent box:

1. **Frost** — `backdrop-filter: blur()` plus `saturate()` to keep backdrop color vivid through the blur.
2. **Translucency** — a `background` with alpha (~0.08–0.18), never fully opaque, never fully clear.
3. **Edge of glass** — a hairline border *brighter* than the fill, ideally a lit top-left → dim bottom-right highlight, so the rim catches light.
4. **Depth** — layered `box-shadow`: an ambient drop shadow to float it, plus an `inset` top highlight and bottom shade to round the surface.

```css
.glass {
  background: rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%); /* Safari needs the prefix */
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.25);
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.25),     /* float */
    inset 0 1px 0 rgba(255, 255, 255, 0.35), /* top highlight */
    inset 0 -1px 0 rgba(0, 0, 0, 0.12);      /* bottom shade */
}
```

Frost tiers: light UI chrome `blur(8–12px)` / alpha `0.08–0.14`; heavy modal/login `blur(24–40px)` / alpha `0.10–0.18`. Dark glass: fill `rgba(0,0,0,0.3)`, softer top highlight.

**`backdrop-filter` only blurs content that sits behind the element.** Over a flat background color it does nothing visible — glass needs a busy backdrop (image, gradient, video) to frost.

## Specular edge highlight and anti-banding grain

A flat border is dead. Draw a masked 1px ring with a lit corner via `::before`, and dither away gradient **banding** (stepped contour lines under heavy blur) with a faint `feTurbulence` noise overlay via `::after` at `opacity ≤ 0.06`. Full masked-border and inline-noise recipes are in `references/glass-recipes.md`.

## Motion: animate the glass, not the geometry

Animate the *qualities* of the glass — frost deepening, highlight brightening, the panel lifting — so it reads as the surface "leaning into the light."

```css
.glass {
  transition: backdrop-filter .4s ease, background .4s ease,
              box-shadow .4s ease, transform .4s cubic-bezier(.16,1,.3,1);
}
.glass:hover {
  backdrop-filter: blur(24px) saturate(180%);
  background: rgba(255,255,255,.18);
  transform: translateY(-4px);
  box-shadow: 0 16px 48px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.5);
}
```

- **Entrance** (frost resolving from clear): pair a `[data-enter]` transition with `@starting-style { backdrop-filter: blur(0); opacity: 0; transform: translateY(16px) }`.
- **Specular sweep**: a skewed white gradient animated across the surface on hover or as a slow ambient loop.
- **Caveat**: animating the blur *radius* is the most expensive thing here — the backdrop is re-blurred every frame. If hover janks, animate `transform`/`box-shadow`/`background` (cheap) and keep the blur delta small or snap it.

## Liquid glass — SVG refraction (the 2026 look)

Bend the background through the panel like a thick lens: drive `feDisplacementMap` from animated `feTurbulence`, applied via `filter` (it distorts the element's own pixels) layered over a `backdrop-filter` frost.

```html
<svg width="0" height="0" style="position:absolute"><filter id="liquid-glass">
  <feTurbulence type="fractalNoise" baseFrequency="0.008 0.012" numOctaves="2" seed="3" result="n">
    <animate attributeName="baseFrequency" dur="18s"
             values="0.008 0.012;0.012 0.008;0.008 0.012" repeatCount="indefinite"/>
  </feTurbulence>
  <feDisplacementMap in="SourceGraphic" in2="n" scale="22" xChannelSelector="R" yChannelSelector="G"/>
</filter></svg>
```

`scale` = refraction strength (8–14 subtle, 20–30 pronounced, >40 molten). Lower `baseFrequency` = larger, slower waves (more liquid). Keep the `animate` `dur` long (12–20s) so it breathes. These filters are heavy — use on **one** hero element, not a grid.

## Performance — backdrop-filter is expensive

- Each glass element re-samples and blurs everything behind it. **Limit the count**; a dozen on screen tanks scroll FPS.
- Promote heavy glass to its own layer (`transform: translateZ(0)` or `will-change: transform`), and remove `will-change` after the animation.
- Don't stack `backdrop-filter` elements over each other — nested blur re-blurs the blur (quadratic cost).
- Big radii (>40px) over large areas are the worst case; cap radius and panel size.

## Accessibility — non-negotiable

Glass is decoration; content must stay legible and the effect must be defeatable.

```css
@media (prefers-reduced-transparency: reduce) {
  .glass { background: #1a1a2e; backdrop-filter: none; -webkit-backdrop-filter: none; }
  .glass::after { display: none; }            /* drop grain */
}
@media (prefers-reduced-motion: reduce) {
  .glass { transition: none; }
  .liquid { filter: none; }                   /* stop the refraction churn */
}
@supports not (backdrop-filter: blur(1px)) {
  .glass { background: rgba(30,30,50,.85); }  /* opaque-enough fallback */
}
```

**Contrast over busy backgrounds**: translucent panels over photos can drop text below WCAG. Add a semi-opaque scrim or darkening gradient *under* the text, optionally `text-shadow: 0 1px 2px rgba(0,0,0,.4)`, and verify ≥ 4.5:1 body / ≥ 3:1 large against the *brightest* region of the backdrop.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained glass demo (card, nav, modal, liquid-glass hero) the deliverable is **one HTML file that opens directly in a browser** — markup, CSS, and (if liquid) one inline SVG filter, no build step. A single file is the right tier for a glass surface; don't reach for a bundler. The panel **must overlap a real backdrop** (drop in a photo or gradient) or there is nothing to frost and the demo lies.

**Output contract:**
- One `.html` file: a busy backdrop, your glass markup, the CSS (frost + edge highlight + grain + shadows), and any inline SVG `feDisplacementMap` filter.
- A way to land on the **resolved state** *and* a **frozen frame** of any loop — glass verifies by both state (rest/hover/enter) and time (the sweep/refraction).
- Include the freeze harness below so any moment can be pinned for inspection.

**Seek harness — pin a deterministic state + frame.** `?state=hover` forces the hover look; `?t=N` freezes CSS animations and the SVG refraction at `N` seconds, so a screenshot lands on a still, deterministic frame:

```html
<script>
  const p = new URLSearchParams(location.search);
  const state = p.get("state");
  if (state) document.documentElement.dataset.state = state;   // CSS keys off :root[data-state="hover"]
  const t = p.get("t");
  if (t !== null) {
    document.getAnimations().forEach(a => { a.currentTime = parseFloat(t)*1000; a.pause(); }); // freeze CSS sweep
    const svg = document.querySelector("svg");
    svg?.pauseAnimations?.(); svg?.setCurrentTime?.(parseFloat(t));                            // freeze refraction
  }
  window.__ready = true;
</script>
```

**Verify loop — render → set state/freeze → screenshot → check:** open each meaningful state (`?state=rest`, `?state=hover`) and a frozen loop frame (`?t=2`), screenshot, and confirm the glass **reads as glass** — blur and edge highlight visibly present, no color banding, text contrast holds over the backdrop — plus check **artifacts** (flat box because the backdrop is plain color, missing `-webkit-` prefix in Safari, refraction too strong/molten, jank from animating blur). Then load `prefers-reduced-transparency` and confirm the **solid fallback renders** legibly. Any headless tool works:

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/glass.html?state=hover" hover.png
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/glass.html?t=2"          loop.png
```

To check the fallback headlessly, emulate the media feature (e.g. Playwright `--color-scheme`-style flags, or a `?reduced=1` query that toggles a class mirroring the media query) and screenshot that the panel is solid and readable.

**Before you finish:**
1. Opens standalone — no console errors; the glass overlaps a real busy backdrop, not a flat color.
2. Reads as glass — blur + bright edge highlight both visible, layered shadow floats it, no banding (grain present).
3. Text contrast holds over the brightest part of the backdrop (≥ 4.5:1 body).
4. `?state=` / `?t=N` freeze lands a deterministic, settled frame.
5. `prefers-reduced-transparency` → solid opaque panel; `prefers-reduced-motion` → refraction/sweep stopped; `@supports` fallback for no `backdrop-filter`.
6. Performance sane — glass count limited, blur not animated on a janky path, liquid refraction on one element only.

## Quick reference

| Need | Approach |
|------|----------|
| Base frost | `backdrop-filter: blur(16px) saturate(160%)` + alpha bg |
| Edge of glass | brighter `border` + masked `::before` lit-corner ring |
| Float / depth | `box-shadow` drop + `inset` top highlight & bottom shade |
| Kill banding | `feTurbulence` noise `::after`, `opacity ≤ .06` |
| Hover motion | transition `transform`/`box-shadow`/`background`, small blur delta |
| Entrance | `@starting-style { backdrop-filter: blur(0); opacity:0 }` |
| Liquid refraction | `feDisplacementMap` ← animated `feTurbulence`, via `filter` |
| Specular sweep | skewed white gradient animated across surface |
| Safari | always pair `-webkit-backdrop-filter` |
| Reduced transparency | solid opaque panel, drop grain |
| No backdrop-filter | `@supports not (...)` opaque-enough fallback |

## Reference files

- `references/glass-recipes.md` — full copy-paste recipes: base glass card with tiers, the masked specular edge ring, anti-banding grain, hover/enter/scroll motion, the specular sweep, the SVG `feDisplacementMap`/`feTurbulence` liquid-glass filter with tuning knobs, performance rules, the reduced-transparency/reduced-motion/`@supports` fallbacks, contrast defenses, and the standalone freeze harness.
