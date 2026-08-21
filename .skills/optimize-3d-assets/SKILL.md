---
name: optimize-3d-assets
description: Optimize and compress 3D assets for the web — shrink glTF/GLB models and textures using gltf-transform, gltfpack/meshopt, Draco, and KTX2/Basis, and optionally convert a model to an R3F component with gltfjsx. Use when a model is too heavy, loads slowly, or needs to be web-ready before adding it to a Three.js/R3F scene.
---

# Optimize 3D assets for the web

Make models small and fast without wrecking the look. Always keep the original; write optimized output to a new file; report before/after sizes.

## Step 0 — Inspect
```bash
npx @gltf-transform/cli inspect model.glb
```
Note: file size, mesh/primitive count, texture count + resolutions, draw call estimate, whether it already uses Draco/KTX2.

## Step 1 — One-shot optimize (start here)
```bash
npx @gltf-transform/cli optimize model.glb model.opt.glb \
  --compress draco \
  --texture-compress ktx2
```
This prunes unused data, dedups, welds, instances, Draco-compresses geometry, and KTX2-compresses textures.

## Step 2 — Targeted passes (if needed)
Resize oversized textures:
```bash
npx @gltf-transform/cli resize model.opt.glb model.opt.glb --width 2048 --height 2048
```
Aggressive meshopt alternative (often smaller than Draco for some models):
```bash
gltfpack -i model.glb -o model.pack.glb -cc
```
(`gltfpack` may need a separate install: `npm i -g gltfpack`.)

Other useful gltf-transform commands: `dedup`, `prune`, `weld`, `instance`, `draco`, `meshopt`, `etc1s`/`uastc` for KTX2 quality tiers.

## Step 3 — Convert to R3F component (optional)
```bash
npx gltfjsx model.opt.glb -t -T
```
- `-t` emits TypeScript, `-T` runs transform/compression. Produces `Model.tsx` with a typed `useGLTF` component and JSX scene graph — easy to edit per-mesh.

## Step 4 — Runtime decoders (R3F / drei)
Compressed assets need decoders at runtime. With drei `useGLTF`, Draco + meshopt + KTX2 are handled, but ensure decoder paths resolve:
```tsx
import { useGLTF } from '@react-three/drei'
// drei sets up DRACOLoader / KTX2Loader / MeshoptDecoder automatically.
useGLTF.preload('/models/model.opt.glb')
```
For vanilla Three.js, wire `DRACOLoader`, `KTX2Loader` (+ `renderer.detectSupport`), and `MeshoptDecoder` onto the `GLTFLoader`.

## Step 5 — Verify & report
- Compare sizes: `original X MB → optimized Y MB (−Z%)`.
- Confirm the model still loads and looks correct in the scene (scale, materials, maps present).
- If textures look washed out, raise KTX2 quality (`--texture-compress ktx2` with uastc) or skip compressing normal maps.

## Targets
- GLB ideally a few MB or less for hero assets; textures KTX2; geometry Draco/meshopt; under ~100 draw calls per scene.

Verify current gltf-transform / gltfpack flags against their docs if a command errors.
