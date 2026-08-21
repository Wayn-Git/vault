# Glassmorphism Recipes

Copy-paste recipes for frosted translucent panels, the "edge of glass" highlight, animated liquid-glass refraction, and the reduced-transparency fallback. All standalone CSS + optional inline SVG — no build step.

## 1. The base glass card

The four ingredients of believable glass: **blur** (frost), **translucency** (you see through it), **edge highlight** (light catches the rim), **layered shadow** (it floats). Plus a touch of `saturate()` so the backdrop reads vivid through the frost.

```css
.glass {
  /* translucency — never fully opaque, never fully clear */
  background: rgba(255, 255, 255, 0.12);
  /* frost: blur the backdrop, lift saturation so color survives the blur */
  backdrop-filter: blur(16px) saturate(160%);
  -webkit-backdrop-filter: blur(16px) saturate(160%); /* Safari still needs the prefix */
  border-radius: 20px;
  /* edge of glass: a hairline border slightly brighter than the fill */
  border: 1px solid rgba(255, 255, 255, 0.25);
  /* depth: ambient drop + a top inner highlight + a bottom inner shade */
  box-shadow:
    0 8px 32px rgba(0, 0, 0, 0.25),
    inset 0 1px 0 rgba(255, 255, 255, 0.35),
    inset 0 -1px 0 rgba(0, 0, 0, 0.12);
}
```

Tuning by tier:
- **Light frost** (UI chrome over content): `blur(8–12px)`, alpha `0.08–0.14`.
- **Heavy frost** (modal scrim, login card): `blur(24–40px)`, alpha `0.10–0.18`.
- Dark glass: swap the fill to `rgba(0,0,0,0.3)` and the top inner highlight to a softer white.

`backdrop-filter` only has anything to blur if there is content **behind** the element — it must overlap a busy background (image, gradient, video). On a flat color it looks like a plain translucent box.

## 2. The specular edge highlight (the rim of light)

A single border is flat. Real glass catches a bright sweep along the top-left edge and falls off. Layer a soft conic/linear highlight via a pseudo-element with a masked border.

```css
.glass {
  position: relative;
  isolation: isolate; /* keep the highlight blend local */
}
.glass::before {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  padding: 1px;                       /* border thickness */
  background: linear-gradient(
    135deg,
    rgba(255, 255, 255, 0.7),
    rgba(255, 255, 255, 0) 40%,
    rgba(255, 255, 255, 0) 60%,
    rgba(255, 255, 255, 0.25)
  );
  /* mask trick: show only the 1px ring, punch out the interior */
  -webkit-mask:
    linear-gradient(#000 0 0) content-box,
    linear-gradient(#000 0 0);
  -webkit-mask-composite: xor;
          mask-composite: exclude;
  pointer-events: none;
}
```

This gives the panel a lit top-left corner and a dim bottom-right, the cue the brain reads as "curved glass under a light."

## 3. Kill banding with grain

Heavy `blur()` over a smooth gradient produces visible color **banding** (stepped contour lines). A faint noise overlay dithers it away.

```css
.glass::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
  opacity: 0.04;                       /* barely there */
  mix-blend-mode: overlay;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
}
```

`feTurbulence` generates the noise tile inline — no asset file. Keep opacity ≤ 0.06 or it reads as texture, not dither.

## 4. Motion: animate the glass on hover / enter / scroll

Animate the *qualities* of the glass, not its geometry. Frost deepening and the highlight brightening on hover reads as the panel "leaning into the light."

```css
.glass {
  transition:
    backdrop-filter 0.4s ease,
    background 0.4s ease,
    box-shadow 0.4s ease,
    transform 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.glass:hover {
  backdrop-filter: blur(24px) saturate(180%);
  background: rgba(255, 255, 255, 0.18);
  transform: translateY(-4px);
  box-shadow:
    0 16px 48px rgba(0, 0, 0, 0.3),
    inset 0 1px 0 rgba(255, 255, 255, 0.5);
}
```

Caveat: animating `backdrop-filter` itself is the most expensive thing here — the backdrop is re-sampled and re-blurred every frame. If hover feels janky, animate only `transform` + `box-shadow` + `background` (cheaper) and snap the blur, or keep the blur change small.

**Entrance** (frost resolving in) reads beautifully with `@starting-style`:

```css
.glass[data-enter] {
  transition: opacity 0.5s ease, backdrop-filter 0.6s ease, transform 0.5s ease;
}
@starting-style {
  .glass[data-enter] {
    opacity: 0;
    backdrop-filter: blur(0px) saturate(100%);
    transform: translateY(16px) scale(0.98);
  }
}
```

**Specular sweep** — a moving glint across the surface on hover or as an ambient loop:

```css
.glass .sweep {
  position: absolute; inset: 0; border-radius: inherit; overflow: hidden; pointer-events: none;
}
.glass .sweep::before {
  content: ""; position: absolute; top: 0; left: -60%; width: 50%; height: 100%;
  background: linear-gradient(105deg, transparent, rgba(255,255,255,0.35), transparent);
  transform: skewX(-15deg);
  animation: sweep 4s ease-in-out infinite;
}
@keyframes sweep { 0%,100% { left: -60%; } 50% { left: 110%; } }
```

## 5. Liquid glass — SVG refraction (the 2026 look)

Apple-style "liquid glass" bends the background as if seen through a thick, wobbling lens. Drive a `feDisplacementMap` from animated `feTurbulence` and apply it via `filter` (note: `filter`, not `backdrop-filter` — it distorts the element's own rendered content; layer it over a `backdrop-filter` frost for the full effect).

```html
<svg width="0" height="0" style="position:absolute">
  <filter id="liquid-glass">
    <feTurbulence type="fractalNoise" baseFrequency="0.008 0.012"
                  numOctaves="2" seed="3" result="noise">
      <!-- animate the field so the refraction slowly churns -->
      <animate attributeName="baseFrequency"
               dur="18s" values="0.008 0.012; 0.012 0.008; 0.008 0.012"
               repeatCount="indefinite"/>
    </feTurbulence>
    <feDisplacementMap in="SourceGraphic" in2="noise"
                       scale="22" xChannelSelector="R" yChannelSelector="G"/>
  </filter>
</svg>
```

```css
.liquid {
  backdrop-filter: blur(6px) saturate(150%); /* light frost under the refraction */
  filter: url(#liquid-glass);                 /* the lens distortion */
}
```

Knobs:
- `scale` on `feDisplacementMap` = refraction strength. 8–14 = subtle ripple; 20–30 = pronounced lens; >40 = molten.
- Lower `baseFrequency` = larger, slower waves (more "liquid"); higher = tight, busy ripples.
- Animate `baseFrequency` (above) or `scale` for a living surface. Keep `dur` long (12–20s) so it breathes rather than shimmers.

Cost warning: SVG displacement filters are heavy and force off-GPU paths in some browsers. Use on **one** hero element, not a grid of cards. Test on a mid-range laptop; drop to plain `backdrop-filter` if frames stutter.

## 6. Performance — backdrop-filter is expensive

- Each `backdrop-filter` element re-samples and blurs everything behind it. **Limit the count** — a dozen glass cards on screen will tank scroll FPS.
- Promote heavy glass to its own compositor layer: `transform: translateZ(0)` or `will-change: transform` (remove `will-change` after the animation; leaving it on wastes memory).
- Avoid stacking `backdrop-filter` elements over each other (nested blur re-blurs the blur — quadratic cost).
- Prefer animating `transform`/`opacity`/`box-shadow` over animating the blur radius. If you must animate blur, keep the radius delta small.
- Big blur radii (>40px) over large areas are the single worst case; cap the radius and the panel size.

## 7. Accessibility — non-negotiable

Glass is decorative; the content on it must stay legible and the effect must be defeatable.

**Honor reduced transparency and reduced motion** — fall back to a solid, opaque panel:

```css
@media (prefers-reduced-transparency: reduce) {
  .glass {
    background: #1a1a2e;            /* solid, accessible panel */
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    border-color: rgba(255, 255, 255, 0.15);
  }
  .glass::after { display: none; }  /* drop grain/noise */
}

@media (prefers-reduced-motion: reduce) {
  .glass, .glass .sweep::before { transition: none; animation: none; }
  .liquid { filter: none; }         /* stop the churning refraction */
}
```

**Contrast over busy backgrounds.** Translucent panels over photos can drop text below WCAG contrast. Defenses:
- Put a contrast floor *under* the text: a semi-opaque scrim or a darkening gradient inside the panel.
- Add `text-shadow: 0 1px 2px rgba(0,0,0,0.4)` to body text on glass.
- Target ≥ 4.5:1 for body text, ≥ 3:1 for large text — and verify against the *brightest* region of the backdrop, not the average.

**Feature fallback** for browsers without `backdrop-filter`:

```css
@supports not (backdrop-filter: blur(1px)) {
  .glass { background: rgba(30, 30, 50, 0.85); } /* opaque-enough fallback */
}
```

## 8. Standalone freeze harness

Glass demos verify by *state* (rest / hover / enter) and *time* (the sweep/refraction loop). Wire both so a screenshot lands deterministically:

```html
<script>
  const p = new URLSearchParams(location.search);
  const state = p.get("state");           // ?state=hover → force the hover look
  if (state) document.documentElement.dataset.state = state;
  const t = p.get("t");                    // ?t=2 → freeze CSS animations at 2s
  if (t !== null) {
    document.getAnimations().forEach(a => { a.currentTime = parseFloat(t) * 1000; a.pause(); });
    // SVG SMIL (the <animate>): pin the refraction frame too
    document.querySelector("svg")?.pauseAnimations?.();
    document.querySelector("svg")?.setCurrentTime?.(parseFloat(t));
  }
  window.__ready = true;
</script>
```

CSS drives the forced state: `:root[data-state="hover"] .glass { /* hover values */ }`.

---
Frosted glass that reads as glass — blur, edge light, and refraction, with a clean fallback. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=glassmorphism)** — the AI motion agent for editable, on-brand motion graphics.
