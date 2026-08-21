# Three.js / R3F Resource Disposal — Detailed Recipes

GPU resources in Three.js live on the *GPU*, not in the JS heap. The garbage collector frees the JS objects but **cannot free the WebGL buffers/textures they uploaded**. Without explicit `.dispose()`, VRAM grows every mount until the context is lost (black canvas, `WebGL: CONTEXT_LOST_WEBGL`).

## What must be disposed (and what must not)

Dispose anything that allocates a GPU resource:

- **Geometries** — `geometry.dispose()` frees vertex/index buffers (VBOs).
- **Materials** — `material.dispose()` frees the compiled shader program. Materials also reference **textures**; disposing the material does **not** dispose its textures.
- **Textures** — `texture.dispose()` frees the uploaded image. Every map slot is separate: `map`, `normalMap`, `roughnessMap`, `metalnessMap`, `aoMap`, `emissiveMap`, `bumpMap`, `displacementMap`, `alphaMap`, `envMap`, `lightMap`, `clearcoatMap`, etc.
- **Render targets** — `renderTarget.dispose()` (used by post-processing, reflections, FBOs). These are large; leaking them is the fastest path to OOM.
- **The renderer** — `renderer.dispose()` and `renderer.forceContextLoss()` on final teardown.

What is **not** GPU-allocated and does **not** need disposal:

- `Object3D`, `Mesh`, `Group`, `Scene` themselves — removing them from the graph + dropping references lets GC reclaim them. They have no `.dispose()`.
- `Vector3`, `Matrix4`, `Color`, `Euler`, math objects — plain JS, GC handles them.
- Lights and cameras — no GPU buffers of their own (shadow map render targets are the exception; those *are* GPU resources, freed by `light.dispose()` on supporting lights / `light.shadow.map.dispose()`).

**Removing a mesh from the scene does NOT dispose its geometry/material/textures.** `scene.remove(mesh)` only detaches it from the graph; the GPU resources stay resident until explicitly disposed.

## Complete disposal utility

Handles geometry, single + array materials, every texture map, shader uniforms, render targets, environment maps, and skinned-mesh skeletons.

```js
import * as THREE from 'three';

const TEXTURE_KEYS = [
  'map', 'alphaMap', 'aoMap', 'bumpMap', 'displacementMap', 'emissiveMap',
  'envMap', 'lightMap', 'metalnessMap', 'normalMap', 'roughnessMap',
  'clearcoatMap', 'clearcoatNormalMap', 'clearcoatRoughnessMap',
  'sheenColorMap', 'sheenRoughnessMap', 'specularMap', 'specularColorMap',
  'specularIntensityMap', 'transmissionMap', 'thicknessMap', 'iridescenceMap',
  'iridescenceThicknessMap', 'gradientMap', 'matcap',
];

export function disposeTexturesOf(material) {
  // Named map slots
  for (const key of TEXTURE_KEYS) {
    const tex = material[key];
    if (tex && tex.isTexture) { tex.dispose(); material[key] = null; }
  }
  // Catch-all: any property that is a texture (covers custom/unknown slots)
  for (const key of Object.keys(material)) {
    const v = material[key];
    if (v && v.isTexture) v.dispose();
  }
  // Shader/node material uniforms
  if (material.uniforms) {
    for (const u of Object.values(material.uniforms)) {
      if (u && u.value && u.value.isTexture) u.value.dispose();
    }
  }
}

export function disposeMaterial(material) {
  disposeTexturesOf(material);
  material.dispose();
}

export function disposeObject(root) {
  root.traverse((obj) => {
    if (obj.geometry) obj.geometry.dispose();
    if (obj.material) {
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach(disposeMaterial);
    }
    // Skinned meshes hold a skeleton with a bone texture
    if (obj.skeleton && obj.skeleton.boneTexture) {
      obj.skeleton.boneTexture.dispose();
    }
  });
  root.parent?.remove(root);
}
```

This handles the three things teardown code usually forgets: **material arrays** (a multi-material mesh), **all map slots** (looping every property that `isTexture`), and **shader uniform textures**.

## Disposing render targets and EffectComposer

Render targets are the largest single GPU allocations; post-processing leaks them silently.

```js
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js';

function disposeComposer(composer) {
  composer.passes.forEach((pass) => {
    if (typeof pass.dispose === 'function') pass.dispose();
    if (pass.fsQuad && pass.fsQuad.dispose) pass.fsQuad.dispose();
  });
  // EffectComposer owns two internal render targets
  composer.renderTarget1?.dispose();
  composer.renderTarget2?.dispose();
}

// Manual render target
const rt = new THREE.WebGLRenderTarget(1024, 1024);
// ... use ...
rt.dispose();
```

## Full renderer teardown (SPA route leaving the 3D view)

```js
function teardownRenderer(renderer, scene) {
  disposeObject(scene);              // geometries/materials/textures
  renderer.dispose();               // frees internal programs/state
  renderer.forceContextLoss();      // releases the WebGL context
  renderer.domElement = null;       // help GC release the canvas
}
```

## R3F: the automatic case and where it leaks

In React Three Fiber, resources created **declaratively in JSX are auto-disposed** on unmount:

```jsx
// Auto-disposed by R3F when this unmounts:
<mesh>
  <boxGeometry args={[1, 1, 1]} />
  <meshStandardMaterial color="red" />
</mesh>
```

R3F walks attached objects and calls `.dispose()` for you. **Leaks happen when resources are created imperatively** — `new THREE.X()` inside hooks, loaders, or refs — because R3F never attached them and cannot dispose them.

### The useMemo + cleanup-effect dispose pattern

For imperative resources, create with `useMemo` (stable identity) and dispose in a matching `useEffect` cleanup:

```jsx
import { useMemo, useEffect } from 'react';
import * as THREE from 'three';

function Particles({ count }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const positions = new Float32Array(count * 3);
    // ... fill positions ...
    g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return g;
  }, [count]);

  const material = useMemo(() => new THREE.PointsMaterial({ size: 0.05 }), []);

  // Dispose when geometry/material identity changes OR on unmount.
  useEffect(() => () => geometry.dispose(), [geometry]);
  useEffect(() => () => material.dispose(), [material]);

  return <points geometry={geometry} material={material} />;
}
```

The cleanup runs both on unmount **and** when the dependency changes (e.g. `count` changes -> old geometry disposed before the new one mounts). Disposing in the same effect that depends on the object is the key: stale closures otherwise dispose the wrong instance.

Set `dispose={null}` on a JSX object only when intentionally sharing it across mounts (see below); otherwise let R3F dispose it.

### Ref-created geometry/material

```jsx
function Thing() {
  const matRef = useRef();
  useEffect(() => {
    const mat = matRef.current;
    return () => mat?.dispose();   // dispose on unmount
  }, []);
  return (
    <mesh>
      <boxGeometry />
      <meshStandardMaterial ref={matRef} />
    </mesh>
  );
}
```

### Loaded texture not via useLoader

```jsx
function Textured({ url }) {
  const texture = useMemo(() => new THREE.TextureLoader().load(url), [url]);
  useEffect(() => () => texture.dispose(), [texture]);
  return <meshBasicMaterial map={texture} />;
}
```

### GLTF full cleanup

```jsx
import { useGLTF } from '@react-three/drei';

function Model({ url }) {
  const { scene } = useGLTF(url);
  useEffect(() => () => {
    disposeObject(scene);
    useGLTF.clear(url);   // drei's cache clear; or useLoader.clear(GLTFLoader, url)
  }, [scene, url]);
  return <primitive object={scene} />;
}
```

### A reusable `<DisposeOnUnmount>` helper

```jsx
import { useEffect } from 'react';

// Wrap any object3D you created imperatively; disposes its subtree on unmount.
export function DisposeOnUnmount({ object }) {
  useEffect(() => () => { if (object) disposeObject(object); }, [object]);
  return object ? <primitive object={object} /> : null;
}
```

## Loaders: clearing the cache

`useLoader` (and `THREE.Cache`) memoizes loaded assets so repeated loads are cheap — but that cache pins textures/geometries in memory. To actually free a GLTF/texture that will not be reused:

```js
import { useLoader } from '@react-three/fiber';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

// Drop the cached entry so the asset can be GC'd / disposed:
useLoader.clear(GLTFLoader, '/model.glb');
```

For GLTF specifically, also dispose the scene subtree with `disposeObject(gltf.scene)` — `useLoader.clear` only removes the cache reference; it does not call WebGL `dispose()` on already-uploaded resources.

## Reusing shared geometry/material (avoid the leak entirely)

The cheapest fix for repeated mounts is to **not allocate per instance**. Create one geometry/material module-level (or memoized at the app root) and share it. Then never dispose it on individual unmount — only at app shutdown.

```js
// shared.js — created once, reused everywhere
import * as THREE from 'three';
export const sharedBox = new THREE.BoxGeometry(1, 1, 1);
export const sharedMat = new THREE.MeshStandardMaterial({ color: 'white' });
```

```jsx
import { sharedBox, sharedMat } from './shared';
// dispose={null} tells R3F not to dispose the shared resource on unmount
<mesh geometry={sharedBox} material={sharedMat} dispose={null} />
```

For many identical objects, prefer `InstancedMesh` — one geometry + one material + one draw call for thousands of instances, which sidesteps per-object disposal entirely:

```js
const mesh = new THREE.InstancedMesh(geometry, material, 10000);
const m = new THREE.Matrix4();
for (let i = 0; i < 10000; i++) {
  m.setPosition(Math.random() * 100, 0, Math.random() * 100);
  mesh.setMatrixAt(i, m);
}
mesh.instanceMatrix.needsUpdate = true;
// Teardown: mesh.geometry.dispose(); mesh.material.dispose(); mesh.dispose();
```

## Detecting leaks with renderer.info

`renderer.info.memory` is the ground truth. Log it before and after a mount/unmount cycle; if `geometries` or `textures` does not return to baseline, something leaked.

```js
console.log(renderer.info.memory);   // { geometries, textures }
console.log(renderer.info.render);   // { calls, triangles, points, lines }
// renderer.info.programs -> array of compiled shader programs (material leaks)
```

In R3F: `const { gl } = useThree();` then read `gl.info.memory`. Mount and unmount the suspect component 10x; a healthy component returns `geometries`/`textures` to the same number each cycle. A steady climb pinpoints the leak.

### Leak-test harness

Mount/unmount a factory repeatedly and assert that memory returns to baseline.

```js
import * as THREE from 'three';

function leakTest(makeObject, renderer, scene, camera, cycles = 10) {
  const baseline = { ...renderer.info.memory };
  for (let i = 0; i < cycles; i++) {
    const obj = makeObject();
    scene.add(obj);
    renderer.render(scene, camera);   // force upload to GPU
    scene.remove(obj);
    disposeObject(obj);               // the thing under test
    renderer.render(scene, camera);
  }
  const after = renderer.info.memory;
  console.table({
    geometries: [baseline.geometries, after.geometries],
    textures:   [baseline.textures, after.textures],
  });
  if (after.geometries !== baseline.geometries || after.textures !== baseline.textures) {
    console.error('LEAK: memory did not return to baseline');
  } else {
    console.log('OK: no leak detected');
  }
}
```

In R3F, read the same numbers from the live renderer:

```jsx
import { useThree, useFrame } from '@react-three/fiber';
function MemoryProbe() {
  const { gl } = useThree();
  useFrame(() => {
    // throttle in real use
    // console.log(gl.info.memory.geometries, gl.info.memory.textures);
  });
  return null;
}
```

## Quick reference

| Resource | Free with | Notes |
|---|---|---|
| BufferGeometry | `.dispose()` | Frees VBOs |
| Material | `.dispose()` | Does NOT free its textures |
| Texture | `.dispose()` | Per map slot; one per map/normalMap/etc. |
| WebGLRenderTarget | `.dispose()` | Post-processing/FBO; large, leak fast |
| Renderer | `.dispose()` + `forceContextLoss()` | Final teardown only |
| Mesh/Group/Scene | (nothing) | GC reclaims after removal |
| Vector/Matrix/Color | (nothing) | Plain JS |
| Shadow map | `light.shadow.map.dispose()` | GPU render target |

## Gotchas

- `scene.remove(mesh)` frees nothing on the GPU — must still dispose geometry/material/textures.
- Disposing a material does not dispose its textures; loop every `isTexture` property.
- A multi-material mesh has `mesh.material` as an **array** — disposing `mesh.material` once misses the rest.
- `ShaderMaterial`/node-material textures live in `uniforms`, not in named map slots; iterate uniforms too.
- `useLoader.clear(Loader, url)` clears the cache but does not call WebGL dispose on already-mounted assets; do both.
- Sharing geometry/material across components and disposing on one unmount corrupts the others still using it — use `dispose={null}` for shared resources, dispose only at shutdown.
- `EffectComposer`/post-processing passes own render targets; dispose the composer/passes or VRAM balloons.
- HMR/Fast Refresh re-runs module code; module-level `new THREE.X()` can accumulate across reloads in dev. Guard it:

```js
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    sharedBox.dispose();
    sharedMat.dispose();
  });
}
```

---
Crossfade clips and dispose GPU resources and a Three.js scene runs leak-free. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=webgl-animation-skills&utm_content=skill_footer&utm_term=threejs-animation)** — the AI motion agent for editable, on-brand motion graphics.
