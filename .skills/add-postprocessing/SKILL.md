---
name: add-postprocessing
description: Add a post-processing effect stack to a React Three Fiber scene — bloom, depth of field, vignette, chromatic aberration, noise/grain, tone mapping, SSAO, and custom effects via @react-three/postprocessing. Use when the user wants the render to look more cinematic, polished, or "premium," or asks for glow/bloom/DOF/film-grain style effects.
---

# Add post-processing to an R3F scene

Post-processing is what turns a flat render into a premium one — but every pass costs frame time. Add intentionally and keep a performance budget.

## Step 1 — Install
```bash
npm i @react-three/postprocessing postprocessing
```

## Step 2 — Add the EffectComposer

Inside `<Canvas>` (after the scene content), add:
```tsx
import {
  EffectComposer, Bloom, DepthOfField, Vignette,
  Noise, ChromaticAberration, ToneMapping, SMAA,
} from '@react-three/postprocessing'
import { BlendFunction, ToneMappingMode } from 'postprocessing'

function Effects() {
  return (
    <EffectComposer multisampling={0} disableNormalPass>
      <Bloom
        intensity={0.6}
        luminanceThreshold={0.85}
        luminanceSmoothing={0.2}
        mipmapBlur
      />
      <DepthOfField focusDistance={0.01} focalLength={0.08} bokehScale={3} />
      <ChromaticAberration offset={[0.0008, 0.0008]} />
      <Noise opacity={0.04} blendFunction={BlendFunction.OVERLAY} />
      <Vignette eskil={false} offset={0.2} darkness={0.9} />
      <ToneMapping mode={ToneMappingMode.ACES_FILMIC} />
      <SMAA />
    </EffectComposer>
  )
}
```

## Step 3 — Tune the look
- **Bloom**: raise `luminanceThreshold` so only bright areas glow; `mipmapBlur` gives a soft, cheap glow. Use emissive materials (or values > 1) to make things bloom.
- **DOF**: `focusDistance` is normalized (0–1); animate it for rack-focus. Expensive — drop on mobile.
- **Tone mapping**: prefer `ACES_FILMIC` for cinematic color; set `gl={{ toneMapping }}` consistently.
- **Grain/CA**: keep subtle — overdone reads as cheap.
- Expose values via `leva` while tuning, then hardcode.

## Step 4 — Performance budget
- Each pass is full-screen fill cost. On mid/low devices, conditionally render fewer effects (e.g. drop DOF + CA, keep Bloom + ToneMapping).
- Use `disableNormalPass` unless an effect needs normals (SSAO/SSR do).
- Consider half-resolution effects and `<PerformanceMonitor>` to scale dynamically.
- Re-check FPS after adding the stack (hand off to **webgl-perf-auditor** if it drops below target).

## Step 5 — Custom effects
For a bespoke look, write a custom effect (wrap a fragment shader with `Effect`/`wrapEffect` from postprocessing) — hand off to the **shader-artist** agent for the GLSL.

## Step 6 — Verify
- Confirm the scene still renders at the target FPS with effects on.
- Show before/after if possible; report which passes are active and their cost.
