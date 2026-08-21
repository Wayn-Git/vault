---
name: particle-system
description: This skill should be used when the user asks to "build a particle system", "make confetti/snow/smoke/sparks", "create a connected-dot/constellation network background", "add a flow-field or curl-noise particle effect", "render thousands of GPU particles with Three.js Points", or "animate emitters with forces". Covers per-particle integration, forces, flow fields, burst/continuous emission, spatial-grid connected dots, and GPU points + shaders.
version: 0.1.0
---

# Particle System

Drive many small elements with simple per-particle rules to get emergent, organic motion. Use 2D canvas for hundreds, GPU `Points` for thousands.

## When to use

- Particle/constellation backgrounds and ambient motion.
- Celebratory bursts: confetti, sparks. Weather: snow, rain. Volumetric: smoke.
- Flow-field / curl-noise swirls and data-driven point clouds.
- Connected-dot networks (lines between nearby particles).

## Core loop: integrate per particle

Each particle holds state and is advanced every frame: accumulate forces into acceleration, integrate velocity and position, age it, respawn when dead. Scale by `dt` for frame-rate independence.

```js
class Particle {
  constructor() { this.reset(); }
  reset() {
    this.x = Math.random() * W; this.y = Math.random() * H;
    this.vx = 0; this.vy = 0;
    this.life = 1; this.size = 1 + Math.random() * 2;
  }
  step(dt, forces) {
    let ax = 0, ay = 0;
    for (const f of forces) { const [fx, fy] = f(this); ax += fx; ay += fy; }
    this.vx += ax * dt; this.vy += ay * dt;
    this.vx *= 0.99; this.vy *= 0.99;            // drag
    this.x += this.vx * dt; this.y += this.vy * dt;
    this.life -= dt * 0.2;
    if (this.life <= 0) this.reset();
  }
}
```
Prefer **semi-implicit Euler** (update velocity first, then position with the new velocity, as above) — it is stable for the spring/drag forces particles use. Use a fixed or clamped `dt` (`Math.min(dt, 1/30)`) so a stalled tab does not explode the simulation.

## Forces

A force is a function returning an acceleration `[fx, fy]`. Compose a list.
```js
const gravity = () => [0, 400];                  // constant downward
const drag = (p) => [-p.vx * 0.5, -p.vy * 0.5];  // proportional resistance
function attract(tx, ty, strength) {             // pull toward a point (e.g. mouse)
  return (p) => {
    const dx = tx - p.x, dy = ty - p.y;
    const d2 = dx*dx + dy*dy + 100;              // +100 softens the singularity
    const f = strength / d2;
    return [dx * f, dy * f];
  };
}
```
Repulsion is `attract` with negative strength. Springs toward a home position give "settle back" effects.

## Flow fields / curl noise (organic swirl)

Sample a noise field to derive a velocity direction per particle. Use the noise value as an angle:
```js
// `noise2D` from a library (e.g. simplex-noise's createNoise2D), range -1..1
function flowField(noise2D, scale = 0.002, speed = 60) {
  return (p) => {
    const angle = noise2D(p.x * scale, p.y * scale) * Math.PI * 2;
    return [Math.cos(angle) * speed - p.vx, Math.sin(angle) * speed - p.vy];
  };
}
```
True **curl noise** is divergence-free (no sources/sinks → fluid-like). Compute the curl of a potential by finite differences:
```js
function curl(noise2D, x, y, eps = 1e-2) {
  const n1 = noise2D(x, y + eps), n2 = noise2D(x, y - eps);
  const n3 = noise2D(x + eps, y), n4 = noise2D(x - eps, y);
  return [ (n1 - n2) / (2*eps), -(n3 - n4) / (2*eps) ];  // (dN/dy, -dN/dx)
}
```
Add time to the noise input (`noise2D(x*scale, y*scale + t)`) to make the field evolve.

## Emission: burst vs continuous

- **Burst** (confetti, sparks): spawn N particles at once at a point with randomized angle/speed within a cone, then let gravity + drag take over. No respawn — remove when dead.
- **Continuous** (snow, smoke): spawn a steady rate; respawn dead particles at the top/source.

Randomize within a range for natural spread: `angle = base + (Math.random()-0.5)*spread; speed = min + Math.random()*(max-min)`.

```js
function burst(x, y, n = 120) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const s = 200 + Math.random() * 400;
    out.push({ x, y, vx: Math.cos(a)*s, vy: Math.sin(a)*s - 200,  // upward bias
               life: 1, size: 4 + Math.random()*4,
               color: `hsl(${Math.random()*360},90%,60%)`,
               rot: Math.random()*6.28, vr: (Math.random()-0.5)*10 });
  }
  return out;
}
```
Confetti reads as confetti because of **rotation + flat rectangles + gravity + air drag**, not round dots. Snow reads as snow from slow fall + gentle horizontal sine sway + size-varied depth.

## Connected-dot network without O(n²)

Naively checking every pair is O(n²) and dies past ~300 particles. Use a **uniform spatial grid**: bin particles by cell, only compare against the 8 neighboring cells.
```js
function connect(ctx, parts, radius) {
  const cell = radius, cols = Math.ceil(W / cell);
  const grid = new Map();
  const key = (cx, cy) => cx + cy * cols;
  for (const p of parts) {
    const cx = (p.x / cell) | 0, cy = (p.y / cell) | 0;
    (grid.get(key(cx, cy)) ?? grid.set(key(cx, cy), []).get(key(cx, cy))).push(p);
  }
  for (const p of parts) {
    const cx = (p.x / cell) | 0, cy = (p.y / cell) | 0;
    for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) {
      const bucket = grid.get(key(cx+ox, cy+oy)); if (!bucket) continue;
      for (const q of bucket) {
        if (q === p) continue;
        const dx = p.x - q.x, dy = p.y - q.y, d = Math.hypot(dx, dy);
        if (d < radius) {
          ctx.globalAlpha = 1 - d / radius;     // fade line with distance
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
        }
      }
    }
  }
  ctx.globalAlpha = 1;
}
```
This is O(n) for evenly distributed particles. Each pair is found twice; halve work by only checking forward neighbors if needed.

## GPU particles: Three.js Points + shader

For thousands+, push all positions into a `BufferGeometry` and render as `Points`. Animate in the vertex shader for true GPU scale.
```js
const N = 50000;
const pos = new Float32Array(N * 3);
for (let i = 0; i < N * 3; i++) pos[i] = (Math.random() - 0.5) * 20;
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
const mat = new THREE.ShaderMaterial({
  uniforms: { u_time: { value: 0 }, u_size: { value: 6 } },
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `
    uniform float u_time, u_size;
    void main(){
      vec3 p = position;
      p.y += sin(u_time + position.x) * 0.5;          // animate on GPU
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = u_size * (10.0 / -mv.z);          // perspective size
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    void main(){
      float d = length(gl_PointCoord - 0.5);
      if (d > 0.5) discard;                            // round, soft points
      gl_FragColor = vec4(1.0, 0.8, 0.4, smoothstep(0.5, 0.0, d));
    }`,
});
scene.add(new THREE.Points(geo, mat));
// loop: mat.uniforms.u_time.value = clock.getElapsedTime();
```
`AdditiveBlending` + `depthWrite: false` gives the glowing-particle look. `discard` on `gl_PointCoord` distance makes square points round. For per-particle data (life, seed), add custom attributes and read them in the shader.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained particle effect (constellation background, confetti burst, flow field, GPU points) the deliverable is **one HTML file that opens directly in a browser** — canvas 2D inline, or Three.js from a CDN via an importmap for GPU `Points`, one render loop, no build step. A single file is the right tier; don't reach for a bundler when one file does the job.

**Output contract:**
- One `.html`: for canvas, the simulation + 2D draw loop in one inline `<script>`; for GPU points, importmap pins `three` to a CDN with the `Points` setup inline.
- Drive the sim from one accumulated `time` (sum of clamped `dt`, or `clock.getElapsedTime()` / `u_time` for GPU). No `Date.now()` scattered per particle.
- **Seed the RNG** — replace bare `Math.random()` with a seeded PRNG (e.g. mulberry32) so spawn positions, angles, and bursts reproduce frame-for-frame.

**Seek/freeze harness — advance to a fixed time, render ONE frame for screenshots.** `?t=N` re-seeds, steps the sim deterministically to `N` seconds with a fixed timestep, renders once, and stops the loop.

```html
<script>
  let rng = mulberry32(1234);                 // fixed seed → reproducible
  const particles = spawn(() => rng());
  function render() { /* draw particles to canvas / renderer.render(...) */ }
  const t = new URLSearchParams(location.search).get("t");
  if (t !== null) {
    const step = 1 / 60, end = parseFloat(t);
    for (let s = 0; s < end; s += step) update(step);  // fixed-step to t
    render();                                  // one frozen frame
    window.__ready = true;
  } else {
    let prev = performance.now();
    (function loop(now){ update(Math.min((now-prev)/1000, 1/30)); prev = now;
      render(); requestAnimationFrame(loop); })(prev);
  }
</script>
```

**Verify loop — render → freeze → screenshot → check:** open at three instants — start, mid, settle (`?t=0`, `?t=<mid>`, `?t=<end>`; for a burst, t≈0 spawn / t≈0.5 spread / t≈1.5 settle) — screenshot each, and check both **fidelity** (matches the brief) and **artifacts**: a **blank canvas = parse/init error** (check the console), particles escaping the frame (clamp/wrap missing), NaN positions (everything vanishes), all particles bunched at the origin (RNG not wired). For GPU points, WebGL needs a GPU context; Playwright/Chromium supplies one (swiftshader) headless.

```bash
npx playwright screenshot --wait-for-timeout=600 "file://$PWD/particles.html?t=1.0" frame-mid.png
```

**Before you finish:**
1. Canvas renders particles — not blank, no console/WebGL errors, no CDN 404s.
2. `?t=N` freezes a reproducible frame (seeded RNG + fixed timestep → same N → same pixels).
3. Screenshotted at start / mid / settle — matches the brief, no escaped/NaN/origin-bunched particles.
4. Disposed and leak-free if embedded in an SPA (cancel the rAF loop; for GPU, dispose geometry/material/renderer).
5. `prefers-reduced-motion` honored — fewer particles or a static field where motion is decorative.

## Quick reference

| Effect | Recipe |
|--------|--------|
| Confetti | burst + gravity + drag + rotating rects |
| Snow | continuous top spawn + slow fall + sine sway |
| Smoke | continuous + upward + grow size + fade alpha |
| Sparks | short-life burst + additive + fast fade |
| Flow field | noise angle → velocity, evolve with time |
| Curl noise | curl of noise potential (divergence-free) |
| Constellation | spatial grid, link within radius, fade by distance |
| 1000s+ | Three.js `Points` + ShaderMaterial, animate in vertex shader |

## Reference files

- `references/particle-recipes.md` — Complete canvas confetti, snow, and smoke systems; mouse attraction/repulsion; full simplex flow-field and curl-noise field with a rendered streaming look; the spatial-grid connected-dot background end to end; and a GPU `Points` system with per-particle life/seed attributes, additive glow, and respawn in the shader.
