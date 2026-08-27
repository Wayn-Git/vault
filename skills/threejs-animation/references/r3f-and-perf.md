# R3F, Animation, and Performance Reference

Detailed Three.js / React Three Fiber motion patterns, instancing, disposal, and post-processing.

## AnimationMixer: full lifecycle

```js
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

let mixer;
const actions = {};
let current;

new GLTFLoader().load('character.glb', (gltf) => {
  scene.add(gltf.scene);
  mixer = new THREE.AnimationMixer(gltf.scene);
  for (const clip of gltf.animations) {
    const action = mixer.clipAction(clip);
    actions[clip.name] = action;
  }
  current = actions['Idle'];
  current.play();
});

function play(name, dur = 0.4) {
  const next = actions[name];
  if (!next || next === current) return;
  next.reset().setEffectiveTimeScale(1).setEffectiveWeight(1).play();
  current.crossFadeTo(next, dur, false);   // warp=false → linear weight blend
  current = next;
}

// One-shot (non-looping) action, e.g. a jump that returns to idle:
function playOnce(name, returnTo = 'Idle') {
  const a = actions[name];
  a.setLoop(THREE.LoopOnce, 1);
  a.clampWhenFinished = true;
  a.reset().play();
  const onFinish = (e) => {
    if (e.action === a) { mixer.removeEventListener('finished', onFinish); play(returnTo); }
  };
  mixer.addEventListener('finished', onFinish);
}

// In the render loop:
const clock = new THREE.Clock();
renderer.setAnimationLoop(() => {
  const dt = clock.getDelta();
  if (mixer) mixer.update(dt);              // MUST pass delta, not elapsed
  renderer.render(scene, camera);
});
```
Common bug: passing elapsed time instead of delta to `mixer.update` makes clips race ahead. Always pass `clock.getDelta()`.

Partial-body blending: set `action.setEffectiveWeight(w)` and play multiple actions simultaneously; use `THREE.AnimationUtils.subclip` to extract a frame range.

## useFrame patterns (R3F)

```jsx
useFrame((state, delta) => {
  // state.clock.elapsedTime  – seconds since start
  // state.pointer            – normalized mouse (-1..1) in x/y
  // state.camera, state.scene, state.gl (renderer)
  ref.current.rotation.y += delta * 0.5;                       // frame-independent

  // Parallax toward pointer with damping:
  const tx = state.pointer.x * 0.5, ty = state.pointer.y * 0.5;
  ref.current.position.x += (tx - ref.current.position.x) * (1 - Math.exp(-6 * delta));
  ref.current.position.y += (ty - ref.current.position.y) * (1 - Math.exp(-6 * delta));
});
```
Pass a priority as the second arg (`useFrame(cb, 1)`) to control execution order or take over rendering. drei's `useAnimations(animations, group)` returns `{ actions }` for the mixer-based playback above without manual setup.

## Scroll-linked camera with drei ScrollControls

```jsx
import { Canvas } from '@react-three/fiber';
import { ScrollControls, useScroll, Scroll } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';

function Rig() {
  const scroll = useScroll();
  useFrame((state) => {
    const p = scroll.offset;                  // 0..1 scroll progress
    state.camera.position.y = -p * 10;
    state.camera.position.z = 5 - p * 3;
    state.camera.lookAt(0, -p * 10, 0);
  });
  return null;
}

export default () => (
  <Canvas dpr={[1, 2]}>
    <ScrollControls pages={3} damping={0.2}>
      <Rig />
      {/* 3D content here; <Scroll html> for DOM that scrolls with it */}
    </ScrollControls>
  </Canvas>
);
```
`scroll.offset` is the eased 0→1 progress; `scroll.range(start, distance)` returns 0→1 for a sub-section, and `scroll.curve(start, distance)` gives a smooth in/out bell — useful for fading elements in and out of viewport ranges.

Vanilla equivalent: read `window.scrollY / (scrollHeight - innerHeight)` on scroll, store as a goal, and damp the camera toward it in the loop. Pair with a `CatmullRomCurve3` and `curve.getPointAt(p)` for a smooth camera path.

## InstancedMesh: per-frame animation with color

```js
const count = 4000;
const inst = new THREE.InstancedMesh(
  new THREE.SphereGeometry(0.05, 8, 8),
  new THREE.MeshStandardMaterial(),
  count
);
inst.instanceMatrix.setUsage(THREE.DynamicDrawUsage);  // hint: updated each frame
scene.add(inst);

const dummy = new THREE.Object3D();
const color = new THREE.Color();
const seeds = Array.from({ length: count }, () => Math.random() * 10);

renderer.setAnimationLoop(() => {
  const t = clock.getElapsedTime();
  for (let i = 0; i < count; i++) {
    const a = i * 0.01 + t;
    dummy.position.set(Math.cos(a) * 3, Math.sin(seeds[i] + t) * 2, Math.sin(a) * 3);
    dummy.rotation.set(t, t * 0.5, 0);
    dummy.updateMatrix();
    inst.setMatrixAt(i, dummy.matrix);
    color.setHSL((i / count + t * 0.05) % 1, 0.6, 0.5);
    inst.setColorAt(i, color);
  }
  inst.instanceMatrix.needsUpdate = true;
  if (inst.instanceColor) inst.instanceColor.needsUpdate = true;
  renderer.render(scene, camera);
});
```
For static instances, set matrices once and never touch `needsUpdate` again. Call `inst.computeBoundingSphere()` after setting matrices so frustum culling works. R3F: `<instancedMesh args={[geo, mat, count]} />` and a ref; same `setMatrixAt` API in `useFrame`.

## Pixel ratio and adaptive resolution

```js
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));  // never render at 3x on phones
```
For heavy scenes, lower internal resolution and let CSS upscale, or use drei `<PerformanceMonitor>` (R3F) to drop `dpr` when fps falls:
```jsx
import { PerformanceMonitor } from '@react-three/drei';
const [dpr, setDpr] = useState(1.5);
<Canvas dpr={dpr}>
  <PerformanceMonitor onIncline={() => setDpr(2)} onDecline={() => setDpr(1)} />
</Canvas>
```

## Dispose on unmount (vanilla)

R3F disposes automatically. For vanilla Three, clean up to avoid GPU leaks:
```js
function disposeScene(obj) {
  obj.traverse((node) => {
    if (node.geometry) node.geometry.dispose();
    if (node.material) {
      const mats = Array.isArray(node.material) ? node.material : [node.material];
      for (const m of mats) {
        for (const key in m) {                       // dispose any texture properties
          const v = m[key];
          if (v && v.isTexture) v.dispose();
        }
        m.dispose();
      }
    }
  });
}
function teardown() {
  renderer.setAnimationLoop(null);
  disposeScene(scene);
  renderer.dispose();
  renderer.forceContextLoss?.();
  renderer.domElement.remove();
}
```

## Post-processing: bloom and depth of field

### Vanilla (EffectComposer)
```js
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { BokehPass } from 'three/addons/postprocessing/BokehPass.js';

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(
  new THREE.Vector2(innerWidth, innerHeight),
  0.8,   // strength
  0.4,   // radius
  0.85   // threshold (only pixels brighter than this bloom)
);
composer.addPass(bloom);
composer.addPass(new BokehPass(scene, camera, { focus: 5.0, aperture: 0.0002, maxblur: 0.01 }));

renderer.setAnimationLoop(() => composer.render());   // render composer, not renderer
addEventListener('resize', () => composer.setSize(innerWidth, innerHeight));
```
For bloom to show, give emissive materials `emissiveIntensity > 1` or use HDR colors; only values above `threshold` bloom. Composer adds passes — keep DPR capped, post-processing is fill-rate heavy.

### R3F (@react-three/postprocessing)
```jsx
import { EffectComposer, Bloom, DepthOfField } from '@react-three/postprocessing';
<Canvas dpr={[1, 2]}>
  {/* scene */}
  <EffectComposer>
    <Bloom intensity={0.8} luminanceThreshold={0.85} mipmapBlur />
    <DepthOfField focusDistance={0.02} focalLength={0.05} bokehScale={3} />
  </EffectComposer>
</Canvas>
```
`mipmapBlur` on Bloom is faster and softer than the legacy blur. DepthOfField is expensive on mobile — gate it behind a capability check or disable below a DPR/fps threshold.
