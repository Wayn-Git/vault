---
name: scaffold-3d-site
description: Scaffold a new 3D/WebGL website project from scratch with a modern, production-ready stack (Vite + React + TypeScript + React Three Fiber + drei + postprocessing, or Next.js variant). Use when the user wants to START a new 3D web project, set up a Three.js/R3F boilerplate, or create a fresh 3D site skeleton.
---

# Scaffold a 3D website

Set up a clean, performant starting point for a 3D web project. Confirm the two choices below from the user's request (or pick the default and state it), then execute.

## Choices
1. **Renderer app**: Vite SPA (default — fastest for pure 3D experiences) OR Next.js (when SEO/SSR/marketing pages matter, 3D as islands).
2. **Quality preset**: `lite` (core 3D only) or `full` (adds motion + postprocessing + physics). Default `full`.

## Step 1 — Create the app

Vite + React + TS (default):
```bash
npm create vite@latest my-3d-site -- --template react-ts
cd my-3d-site
```

Next.js (alternative):
```bash
npx create-next-app@latest my-3d-site --ts --app --eslint
cd my-3d-site
```

## Step 2 — Install the 3D stack

Core (always):
```bash
npm i three @react-three/fiber @react-three/drei
npm i -D @types/three
```

Full preset (add):
```bash
npm i @react-three/postprocessing postprocessing
npm i @react-three/rapier
npm i gsap @studio-freight/lenis
npm i zustand leva maath
```

Asset tooling (dev):
```bash
npm i -D @gltf-transform/cli
```

## Step 3 — Create the scene skeleton

Make this structure (adapt to Vite `src/` or Next `app/`):
```
src/
  components/
    Experience.tsx     # the 3D scene graph
    Scene.tsx          # <Canvas> wrapper + lights + environment
  hooks/
  shaders/
  lib/
  assets/models/
  assets/textures/
```

`Scene.tsx` (Vite/React example):
```tsx
import { Canvas } from '@react-three/fiber'
import { Environment, OrbitControls, Loader } from '@react-three/drei'
import { Suspense } from 'react'
import { Experience } from './Experience'

export default function Scene() {
  return (
    <>
      <Canvas
        shadows
        dpr={[1, 2]}
        camera={{ position: [0, 1.5, 6], fov: 45 }}
        gl={{ antialias: true, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#0a0a0f']} />
        <Suspense fallback={null}>
          <Experience />
          <Environment preset="city" />
        </Suspense>
        <OrbitControls enableDamping makeDefault />
      </Canvas>
      <Loader />
    </>
  )
}
```

`Experience.tsx`:
```tsx
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Mesh } from 'three'

export function Experience() {
  const mesh = useRef<Mesh>(null!)
  useFrame((_, delta) => { mesh.current.rotation.y += delta * 0.3 })
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 5, 5]} intensity={2} castShadow />
      <mesh ref={mesh} castShadow>
        <icosahedronGeometry args={[1, 0]} />
        <meshStandardMaterial color="#5b8cff" roughness={0.2} metalness={0.6} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position-y={-1.5} receiveShadow>
        <planeGeometry args={[50, 50]} />
        <meshStandardMaterial color="#111118" />
      </mesh>
    </>
  )
}
```

Mount `<Scene />` full-screen (set `html, body, #root { height: 100%; margin: 0 }` and the canvas container to 100vw/100vh).

## Step 4 — Verify
- Run `npm run dev` and confirm the scene renders with a rotating, lit mesh and orbit controls.
- Report the dev URL and that it builds.

## Step 5 — Hand off
Tell the user which custom agents drive the next steps:
- **threejs-architect** — refine architecture/budgets
- **r3f-engineer** — build out the real scene
- **shader-artist** — custom materials/effects
- **motion-choreographer** — scroll & camera motion
- **asset-pipeline-engineer** — load & optimize real models
- **webgl-perf-auditor** — keep it at 60fps

Keep dependency versions current; if a package API changed, check its docs before scaffolding.
