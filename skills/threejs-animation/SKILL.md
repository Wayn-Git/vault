---
name: threejs-animation
description: This skill should be used when the user asks to "build a 3D hero section or WebGL background", "animate a Three.js scene", "play or crossfade GLTF animation clips", "move/lerp the camera or link it to scroll", "render thousands of objects with InstancedMesh", "set up React Three Fiber (R3F) motion", "add bloom/DOF post-processing", or "keep a Three.js/R3F animation smooth and leak-free (dispose geometries/materials/textures, free GPU memory on unmount)". Covers scenes, render loops, camera moves, GLTF AnimationMixer, instancing, scroll-linked 3D, R3F, and animation performance/disposal.
version: 0.1.0
---

# Three.js Motion (3D / WebGL)

Build real-time 3D motion for the web: animated scenes, camera moves, GLTF playback, instancing, scroll-linked 3D, and React Three Fiber. Optimize for smooth 60fps and clean disposal.

## When to use

- 3D hero sections, product viewers, interactive/scroll-linked 3D backgrounds.
- Playing and blending GLTF animation clips.
- Rendering many objects efficiently (particle fields, tiles, forests).
- Camera fly-throughs and scroll-driven camera moves.

## Minimal scene + render loop

```js
import * as THREE from 'three';
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 100);
camera.position.set(0, 0, 5);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(innerWidth, innerHeight);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));   // cap DPR — critical for retina perf
document.body.appendChild(renderer.domElement);

const mesh = new THREE.Mesh(
  new THREE.IcosahedronGeometry(1, 0),
  new THREE.MeshStandardMaterial({ color: 0x44aaff, flatShading: true })
);
scene.add(mesh, new THREE.DirectionalLight(0xffffff, 2).translateZ(5),
          new THREE.AmbientLight(0xffffff, 0.4));

const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  mesh.rotation.y += dt * 0.5;                            // frame-rate independent
  renderer.render(scene, camera);
});
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight);
});
```

Use `clock.getDelta()` to make motion frame-rate independent (multiply rates by `dt`), and `setAnimationLoop` (works with WebXR and pauses on tab blur) instead of raw `requestAnimationFrame`.

## GLTF animation clips

Load a model, play clips through an `AnimationMixer`, and **update the mixer with delta time** every frame.

```js
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
let mixer, actions = {};
new GLTFLoader().load('model.glb', (gltf) => {
  scene.add(gltf.scene);
  mixer = new THREE.AnimationMixer(gltf.scene);
  gltf.animations.forEach((clip) => { actions[clip.name] = mixer.clipAction(clip); });
  actions['Idle']?.play();
});
// In the loop: if (mixer) mixer.update(dt);
```

Crossfade between two clips smoothly:
```js
function crossfade(fromName, toName, dur = 0.4) {
  const from = actions[fromName], to = actions[toName];
  to.reset().setEffectiveWeight(1).play();
  from.crossFadeTo(to, dur, false);                       // warping=false: linear weight ramp
}
```
For one-shot clips (e.g. a jump), set `action.setLoop(THREE.LoopOnce); action.clampWhenFinished = true;` and listen for `mixer.addEventListener('finished', ...)`.

## Camera lerp and scroll-linked motion

Smooth camera follow uses exponential interpolation toward a target. Frame-rate-correct damping:
```js
const target = new THREE.Vector3(0, 0, 5);
function dampVec(current, goal, lambda, dt) {
  current.lerp(goal, 1 - Math.exp(-lambda * dt));         // lambda ~ 3..8
}
// loop: dampVec(camera.position, target, 5, dt); camera.lookAt(0, 0, 0);
```

Scroll-linked camera: map `scrollY / maxScroll` (0→1) to camera position along a path. Update the goal on scroll, let damping smooth it.
```js
addEventListener('scroll', () => {
  const p = scrollY / (document.body.scrollHeight - innerHeight);
  target.set(0, p * -10, 5 - p * 3);                      // move down and in
});
```
Use `THREE.CatmullRomCurve3` and `curve.getPointAt(p)` for curved fly-throughs.

## Instancing for many objects

One draw call for thousands of identical meshes. Set per-instance matrices (and optional colors).
```js
const count = 5000;
const geo = new THREE.BoxGeometry(0.1, 0.1, 0.1);
const mat = new THREE.MeshStandardMaterial();
const inst = new THREE.InstancedMesh(geo, mat, count);
const dummy = new THREE.Object3D();
for (let i = 0; i < count; i++) {
  dummy.position.set((Math.random()-0.5)*20, (Math.random()-0.5)*20, (Math.random()-0.5)*20);
  dummy.updateMatrix();
  inst.setMatrixAt(i, dummy.matrix);
}
inst.instanceMatrix.needsUpdate = true;
scene.add(inst);
// Animate: update dummy per instance, setMatrixAt, then needsUpdate = true each frame.
```
Set `inst.instanceMatrix.setUsage(THREE.DynamicDrawUsage)` if updating every frame. Per-instance color: `inst.setColorAt(i, color)` then `inst.instanceColor.needsUpdate = true`.

## React Three Fiber (R3F)

Drive animation with `useFrame`; it receives `state` and `delta`.
```jsx
import { Canvas, useFrame } from '@react-three/fiber';
import { useRef } from 'react';
function Spinner() {
  const ref = useRef();
  useFrame((state, delta) => {
    ref.current.rotation.y += delta * 0.5;
    ref.current.position.y = Math.sin(state.clock.elapsedTime) * 0.3;
  });
  return <mesh ref={ref}><icosahedronGeometry /><meshStandardMaterial /></mesh>;
}
export default () => (
  <Canvas dpr={[1, 2]} camera={{ position: [0, 0, 5] }}>
    <ambientLight intensity={0.4} /><directionalLight position={[5, 5, 5]} />
    <Spinner />
  </Canvas>
);
```
`dpr={[1, 2]}` caps pixel ratio. Load models with `useGLTF` (drei), animate clips with `useAnimations`. For springs use `@react-spring/three`; for scroll use drei `ScrollControls` + `useScroll`.

## Performance and cleanup (critical)

- Cap pixel ratio: `Math.min(devicePixelRatio, 2)`. This is the single biggest win on retina/mobile.
- Reuse geometries and materials; merge static geometry with `BufferGeometryUtils.mergeGeometries`.
- Prefer matcaps or baked lighting over many real-time lights; each shadow-casting light is expensive.
- Material/emissive motion (pulsing emissive, displacement) often reads better and is cheaper than moving lots of geometry.

## Cleanup & GPU memory (disposal)

GPU resources (geometries, materials, textures, render targets) live on the *GPU*, not the JS heap. The garbage collector frees the JS objects but **cannot free the WebGL buffers/textures they uploaded**. Without explicit `.dispose()`, VRAM grows on every mount until the context is lost (black canvas, `WebGL: CONTEXT_LOST_WEBGL`). This is why `renderer.info.memory` keeps rising across mount/unmount cycles.

**Dispose what allocates GPU memory; ignore what does not:**

- Dispose: `geometry.dispose()` (VBOs), `material.dispose()` (shader program — but NOT its textures), `texture.dispose()` (per map slot: `map`, `normalMap`, `roughnessMap`, `envMap`, …), `renderTarget.dispose()`, and on final teardown `renderer.dispose()` + `renderer.forceContextLoss()`.
- No disposal needed: `Mesh`/`Group`/`Scene` (GC reclaims after removal), `Vector3`/`Matrix4`/`Color` (plain JS), lights/cameras (except shadow map render targets).
- `scene.remove(mesh)` only detaches from the graph — it frees **nothing** on the GPU. Geometry/material/textures stay resident until explicitly disposed.

**Teardown traversal** — disposing a loaded model or whole scene must handle material *arrays* and *every* texture map per material:

```js
function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) {
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const m of mats) {
        for (const key in m) {                  // dispose any texture property
          const v = m[key];
          if (v && v.isTexture) v.dispose();
        }
        m.dispose();
      }
    }
  });
  root.parent?.remove(root);
}
// SPA route teardown: renderer.setAnimationLoop(null); disposeObject(scene);
//   renderer.dispose(); renderer.forceContextLoss?.();
```

**R3F unmount cleanup** — resources created **declaratively in JSX are auto-disposed** on unmount (R3F walks attached objects and calls `.dispose()`). **Leaks happen with imperative resources** (`new THREE.X()` in hooks/refs/loaders) that R3F never attached. Create them with `useMemo` and dispose in a matching `useEffect` cleanup:

```jsx
const geometry = useMemo(() => new THREE.BufferGeometry(/* … */), [count]);
useEffect(() => () => geometry.dispose(), [geometry]);  // disposes on unmount AND dep change
```

For shared resources reused across mounts, set `dispose={null}` on the JSX object and dispose only at app shutdown. Verify with `renderer.info.memory` (R3F: `useThree().gl.info.memory`): mount/unmount 10x; if `geometries`/`textures` does not return to baseline, something leaked.

See `references/resource-disposal.md` for the full disposal utility (all map slots, shader uniforms, render targets, skinned meshes), EffectComposer/render-target disposal, a `renderer.info` leak-test harness, R3F cleanup recipes (refs, textures, GLTF cache clearing, `<DisposeOnUnmount>`), and HMR safety.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

For a self-contained 3D scene (hero, WebGL background, micro-scene) the deliverable is **one HTML file that opens directly in a browser** — Three.js pulled from a CDN via an importmap, one render loop, no build step. A single file is the right tier for a scene; don't reach for a bundler when one file does the job.

**Output contract:**
- One `.html`: importmap pins `three` + `three/addons` to a CDN; your scene and the render loop in one inline `<script type="module">`.
- Drive ALL motion from one source of truth — `clock.getElapsedTime()` (and `mixer`/camera read from it). No `Date.now()`, no per-object wall-clock.
- Seed any randomness (instance placement, jitter) from a fixed seed so frames reproduce.

**Seek/freeze harness — render ONE frame at a fixed time for screenshots.** `?t=N` forces elapsed time to `N` seconds, advances the scene to that instant, renders once, and stops the loop — a deterministic still.

```html
<script type="module">
  // ... build scene, camera, renderer, clock, mixer ...
  const t = new URLSearchParams(location.search).get("t");
  function frame(elapsed) {            // pure: scene state is a function of elapsed
    mesh.rotation.y = elapsed * 0.5;
    if (mixer) { mixer.setTime(elapsed); }   // setTime is absolute, not delta
    renderer.render(scene, camera);
  }
  if (t !== null) {
    frame(parseFloat(t));             // one fixed frame, no loop
    window.__ready = true;
  } else {
    const clock = new THREE.Clock();
    renderer.setAnimationLoop(() => frame(clock.getElapsedTime()));
  }
</script>
```

**Verify loop — render → freeze → screenshot → check:** open the file at three instants — start, mid, end (`?t=0`, `?t=<mid>`, `?t=<end>` for an animated clip/loop) — screenshot each, and check both **fidelity** (matches the brief) and **artifacts**: a **black canvas = parse/init error** (check the console), clipped/off-frame geometry, NaN positions (objects vanish), missing model/texture (CDN 404). WebGL needs a GPU context; Playwright/Chromium supplies one (swiftshader) headless.

```bash
npx playwright screenshot --wait-for-timeout=600 "file://$PWD/scene.html?t=1.5" frame-mid.png
```

**Before you finish:**
1. Canvas actually renders — not blank, no console/WebGL errors, no CDN 404s.
2. `?t=N` freezes a reproducible frame (same N → same pixels; randomness seeded).
3. Screenshotted at start / mid / end — matches the brief, no clipping/NaN/black.
4. Disposed and leak-free if embedded in an SPA (`setAnimationLoop(null)` + dispose; see disposal section).
5. `prefers-reduced-motion` honored — slow/halt rotation or auto-play where relevant.

## Quick reference

| Goal | API |
|------|-----|
| Frame-independent motion | multiply by `clock.getDelta()` |
| Play GLTF clip | `mixer.clipAction(clip).play()` + `mixer.update(dt)` |
| Blend clips | `from.crossFadeTo(to, dur, false)` |
| Smooth camera | `lerp(goal, 1 - exp(-lambda*dt))` |
| Many objects | `InstancedMesh` + `setMatrixAt` |
| Scroll 3D | map scroll 0→1 to camera target |
| Cap DPR | `setPixelRatio(min(dpr, 2))` |

## Reference files

- `references/r3f-and-perf.md` — Full AnimationMixer crossfade and one-shot handling, useFrame patterns (clock, pointer, lerp), drei ScrollControls scroll-linked camera, InstancedMesh per-frame animation with color, pixel-ratio and adaptive resolution, complete dispose-on-unmount routine, and postprocessing (UnrealBloom, DepthOfField/bokeh) for both vanilla Three and R3F.
- `references/resource-disposal.md` — Complete GPU resource disposal: full disposal utility (all map slots, shader uniforms, render targets, env maps, skinned meshes), EffectComposer/render-target teardown, full renderer teardown, R3F leak cases and the useMemo+cleanup pattern, ref/texture/GLTF cleanup recipes, `<DisposeOnUnmount>` helper, shared-resource and InstancedMesh strategies, `renderer.info` leak-test harness, and HMR safety.
