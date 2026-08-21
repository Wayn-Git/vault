# Particle Recipes

Complete, runnable systems for canvas and GPU particles.

## Canvas boilerplate

```js
const canvas = document.querySelector('canvas');
const ctx = canvas.getContext('2d');
let W, H, DPR = Math.min(devicePixelRatio, 2);
function resize() {
  W = canvas.width = innerWidth * DPR;
  H = canvas.height = innerHeight * DPR;
  canvas.style.width = innerWidth + 'px';
  canvas.style.height = innerHeight + 'px';
}
resize(); addEventListener('resize', resize);

let last = performance.now();
function loop(now) {
  const dt = Math.min((now - last) / 1000, 1 / 30);  // clamp dt
  last = now;
  update(dt); render();
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
```

## Confetti burst

```js
let confetti = [];
function fireConfetti(x, y, n = 150) {
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const s = (200 + Math.random() * 400) * DPR;
    confetti.push({
      x, y,
      vx: Math.cos(a) * s,
      vy: Math.sin(a) * s - 250 * DPR,               // initial upward bias
      w: (6 + Math.random() * 6) * DPR,
      h: (3 + Math.random() * 4) * DPR,
      rot: Math.random() * Math.PI * 2,
      vr: (Math.random() - 0.5) * 12,
      color: `hsl(${Math.random() * 360}, 90%, 60%)`,
      life: 1,
    });
  }
}
function updateConfetti(dt) {
  const G = 900 * DPR;
  for (const p of confetti) {
    p.vy += G * dt;
    p.vx *= 0.99; p.vy *= 0.99;                       // air drag
    p.x += p.vx * dt; p.y += p.vy * dt;
    p.rot += p.vr * dt;
    p.life -= dt * 0.35;
  }
  confetti = confetti.filter(p => p.life > 0 && p.y < H + 50);
}
function renderConfetti() {
  for (const p of confetti) {
    ctx.save();
    ctx.translate(p.x, p.y); ctx.rotate(p.rot);
    ctx.globalAlpha = Math.min(1, p.life * 2);
    ctx.fillStyle = p.color;
    ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h * Math.abs(Math.cos(p.rot))); // flutter
    ctx.restore();
  }
  ctx.globalAlpha = 1;
}
```
The `Math.abs(Math.cos(p.rot))` height squash simulates a flat sheet flipping edge-on — the detail that makes confetti read as paper, not squares.

## Snow

```js
const snow = Array.from({ length: 400 }, () => spawnFlake(true));
function spawnFlake(anywhere) {
  const depth = Math.random();                        // 0 far .. 1 near
  return {
    x: Math.random() * W,
    y: anywhere ? Math.random() * H : -10,
    r: (1 + depth * 3) * DPR,                          // near flakes bigger
    vy: (20 + depth * 50) * DPR,                       // and faster
    sway: Math.random() * Math.PI * 2,
    swaySpeed: 0.5 + Math.random(),
    swayAmp: (10 + depth * 30) * DPR,
    alpha: 0.4 + depth * 0.6,
  };
}
function updateSnow(dt, t) {
  for (const f of snow) {
    f.y += f.vy * dt;
    f.x += Math.cos(t * f.swaySpeed + f.sway) * f.swayAmp * dt;
    if (f.y > H + 10) Object.assign(f, spawnFlake(false));
  }
}
function renderSnow() {
  ctx.fillStyle = '#fff';
  for (const f of snow) {
    ctx.globalAlpha = f.alpha;
    ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, 6.28318); ctx.fill();
  }
  ctx.globalAlpha = 1;
}
```
Depth-varied size/speed/alpha creates a parallax illusion of a 3D snowfall from a 2D system.

## Smoke

```js
let smoke = [];
function emitSmoke(x, y) {
  smoke.push({
    x: x + (Math.random() - 0.5) * 20 * DPR, y,
    vx: (Math.random() - 0.5) * 20 * DPR,
    vy: -(30 + Math.random() * 30) * DPR,
    size: (10 + Math.random() * 10) * DPR,
    growth: (30 + Math.random() * 30) * DPR,
    life: 1, maxLife: 1 + Math.random(),
  });
}
function updateSmoke(dt) {
  for (const s of smoke) {
    s.vx *= 0.98; s.vy *= 0.99;
    s.x += s.vx * dt; s.y += s.vy * dt;
    s.size += s.growth * dt;                           // expand as it rises
    s.life -= dt / s.maxLife;
  }
  smoke = smoke.filter(s => s.life > 0);
}
function renderSmoke() {
  ctx.globalCompositeOperation = 'lighter';           // or 'source-over' for dark smoke
  for (const s of smoke) {
    const a = s.life * 0.15;
    const g = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, s.size);
    g.addColorStop(0, `rgba(200,200,200,${a})`);
    g.addColorStop(1, 'rgba(200,200,200,0)');
    ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(s.x, s.y, s.size, 0, 6.28318); ctx.fill();
  }
  ctx.globalCompositeOperation = 'source-over';
}
// emit a few per frame from a source: for (let i=0;i<3;i++) emitSmoke(W/2, H-20);
```
Soft radial gradients that grow + fade are the core of smoke/fog/dust. Emit several small puffs per frame rather than one big one.

## Mouse attraction / repulsion

```js
const mouse = { x: W / 2, y: H / 2, active: false };
addEventListener('pointermove', e => { mouse.x = e.clientX * DPR; mouse.y = e.clientY * DPR; mouse.active = true; });
function applyMouse(p, dt, strength = 1) {
  if (!mouse.active) return;
  const dx = mouse.x - p.x, dy = mouse.y - p.y;
  const d2 = dx*dx + dy*dy + 400;
  const f = strength * 40000 / d2;                    // negative strength = repel
  p.vx += (dx / Math.sqrt(d2)) * f * dt;
  p.vy += (dy / Math.sqrt(d2)) * f * dt;
}
```

## Flow field with simplex noise

```js
import { createNoise3D } from 'simplex-noise';        // npm i simplex-noise
const noise3D = createNoise3D();
const SCALE = 0.0015, SPEED = 90 * DPR;

const flow = Array.from({ length: 1500 }, () => ({
  x: Math.random() * W, y: Math.random() * H,
  px: 0, py: 0, hue: Math.random() * 60 + 180,
}));

function updateFlow(dt, t) {
  for (const p of flow) {
    p.px = p.x; p.py = p.y;
    const angle = noise3D(p.x * SCALE, p.y * SCALE, t * 0.1) * Math.PI * 2;
    p.x += Math.cos(angle) * SPEED * dt;
    p.y += Math.sin(angle) * SPEED * dt;
    if (p.x < 0 || p.x > W || p.y < 0 || p.y > H) {   // wrap/respawn
      p.x = Math.random() * W; p.y = Math.random() * H;
      p.px = p.x; p.py = p.y;
    }
  }
}
function renderFlow() {
  ctx.fillStyle = 'rgba(0,0,0,0.04)';                  // trail fade instead of clearRect
  ctx.fillRect(0, 0, W, H);
  ctx.lineWidth = 1.2 * DPR;
  for (const p of flow) {
    ctx.strokeStyle = `hsla(${p.hue}, 70%, 60%, 0.6)`;
    ctx.beginPath(); ctx.moveTo(p.px, p.py); ctx.lineTo(p.x, p.y); ctx.stroke();
  }
}
```
Drawing line segments from previous to current position (instead of dots) plus a translucent fill-over-clear leaves silky trails that reveal the field structure.

### Curl noise variant (divergence-free, fluid)

```js
const noise2D = createNoise3D();  // reuse with fixed z, or createNoise2D
function curlVel(x, y, t, eps = 1.0) {
  const n1 = noise2D(x * SCALE, (y + eps) * SCALE, t);
  const n2 = noise2D(x * SCALE, (y - eps) * SCALE, t);
  const n3 = noise2D((x + eps) * SCALE, y * SCALE, t);
  const n4 = noise2D((x - eps) * SCALE, y * SCALE, t);
  return [(n1 - n2) / (2 * eps), -(n3 - n4) / (2 * eps)];
}
// usage: const [cx, cy] = curlVel(p.x, p.y, t); p.x += cx * SPEED * dt; p.y += cy * SPEED * dt;
```
Curl fields have no sources or sinks, so particles never pile up — they swirl like smoke or water.

## Connected-dot constellation (full)

```js
const NODES = 120;
const nodes = Array.from({ length: NODES }, () => ({
  x: Math.random() * W, y: Math.random() * H,
  vx: (Math.random() - 0.5) * 30 * DPR,
  vy: (Math.random() - 0.5) * 30 * DPR,
}));
const LINK = 140 * DPR;

function updateNodes(dt) {
  for (const n of nodes) {
    n.x += n.vx * dt; n.y += n.vy * dt;
    if (n.x < 0 || n.x > W) n.vx *= -1;
    if (n.y < 0 || n.y > H) n.vy *= -1;
  }
}
function renderNodes() {
  ctx.clearRect(0, 0, W, H);
  // spatial grid to avoid O(n^2)
  const cell = LINK, cols = Math.max(1, Math.ceil(W / cell));
  const grid = new Map();
  const key = (cx, cy) => cx + cy * cols;
  for (const n of nodes) {
    const cx = (n.x / cell) | 0, cy = (n.y / cell) | 0, k = key(cx, cy);
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(n);
  }
  ctx.strokeStyle = '#6cf'; ctx.lineWidth = 1 * DPR;
  for (const n of nodes) {
    const cx = (n.x / cell) | 0, cy = (n.y / cell) | 0;
    for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) {
      const bucket = grid.get(key(cx + ox, cy + oy)); if (!bucket) continue;
      for (const m of bucket) {
        if (m === n) continue;
        const dx = n.x - m.x, dy = n.y - m.y, d = Math.hypot(dx, dy);
        if (d < LINK) {
          ctx.globalAlpha = (1 - d / LINK) * 0.5;
          ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(m.x, m.y); ctx.stroke();
        }
      }
    }
  }
  ctx.globalAlpha = 1; ctx.fillStyle = '#9df';
  for (const n of nodes) { ctx.beginPath(); ctx.arc(n.x, n.y, 2 * DPR, 0, 6.28318); ctx.fill(); }
}
```
The grid keeps this O(n) so it scales to hundreds of nodes. `LINK` equals the cell size, so all possible neighbors fall within the 3×3 block.

## GPU Points with per-particle life and respawn

```js
import * as THREE from 'three';
const N = 80000;
const positions = new Float32Array(N * 3);
const seeds = new Float32Array(N);
const speeds = new Float32Array(N);
for (let i = 0; i < N; i++) {
  positions[i*3] = (Math.random()-0.5)*10;
  positions[i*3+1] = Math.random()*10;
  positions[i*3+2] = (Math.random()-0.5)*10;
  seeds[i] = Math.random();
  speeds[i] = 0.5 + Math.random();
}
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
geo.setAttribute('aSeed', new THREE.BufferAttribute(seeds, 1));
geo.setAttribute('aSpeed', new THREE.BufferAttribute(speeds, 1));

const mat = new THREE.ShaderMaterial({
  uniforms: { u_time: { value: 0 }, u_size: { value: 8 } },
  transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  vertexShader: `
    uniform float u_time, u_size;
    attribute float aSeed, aSpeed;
    varying float vAlpha;
    void main(){
      // life cycles 0..1; particle falls then respawns at top
      float life = fract(aSeed + u_time * 0.15 * aSpeed);
      vec3 p = position;
      p.y = 10.0 - life * 12.0;                         // fall down
      p.x += sin(u_time * aSpeed + aSeed * 6.28) * 0.3; // sway
      vAlpha = sin(life * 3.14159);                     // fade in/out over life
      vec4 mv = modelViewMatrix * vec4(p, 1.0);
      gl_PointSize = u_size * (8.0 / -mv.z);
      gl_Position = projectionMatrix * mv;
    }`,
  fragmentShader: `
    varying float vAlpha;
    void main(){
      float d = length(gl_PointCoord - 0.5);
      if (d > 0.5) discard;
      float soft = smoothstep(0.5, 0.0, d);
      gl_FragColor = vec4(0.7, 0.85, 1.0, soft * vAlpha);
    }`,
});
scene.add(new THREE.Points(geo, mat));
// loop: mat.uniforms.u_time.value = clock.getElapsedTime();
```
The whole simulation runs in the vertex shader using `fract()` for a looping per-particle life — no CPU updates, so 80k+ particles stay at 60fps. For interactive/colliding particles needing CPU readback, use a GPGPU ping-pong (`THREE.GPUComputationRenderer`) instead.

---
Compose forces over a tight integration loop and particles behave believably. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=webgl-animation-skills&utm_content=skill_footer&utm_term=particle-system)** — the AI motion agent for editable, on-brand motion graphics.
