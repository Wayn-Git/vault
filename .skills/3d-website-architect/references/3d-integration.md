# 3D Integration Reference

Complete reference for integrating Three.js and React Three Fiber into modern web experiences.
Consult this when implementing Step 7 of the Immersive Design Process.

## Table of Contents

1. [Canvas Setup](#canvas-setup)
2. [Lighting Systems](#lighting-systems)
3. [Common Scene Recipes](#common-scene-recipes)
4. [Geometry Patterns](#geometry-patterns)
5. [Shader Materials](#shader-materials)
6. [Post-Processing](#post-processing)
7. [Mouse & Scroll Interaction](#mouse--scroll-interaction)
8. [Performance Optimization](#performance-optimization)
9. [Responsive 3D](#responsive-3d)
10. [Loading & Error Handling](#loading--error-handling)
11. [Model Loading](#model-loading)

---

## Canvas Setup

### Basic R3F Canvas Configuration

```tsx
import { Canvas } from '@react-three/fiber';
import { Suspense } from 'react';

function Scene3D() {
  return (
    <div className="absolute inset-0 -z-10">
      <Canvas
        camera={{ position: [0, 0, 5], fov: 45 }}
        dpr={[1, 2]}  // Pixel ratio: min 1, max 2 (no need for 3x)
        gl={{
          antialias: true,
          alpha: true,  // Transparent background — lets CSS bg show
          powerPreference: 'high-performance',
        }}
        style={{ pointerEvents: 'none' }}  // Pass clicks through to UI
      >
        <Suspense fallback={null}>
          <HeroScene />
        </Suspense>
      </Canvas>
    </div>
  );
}
```

### Canvas as Background Layer

The most common pattern for 3D websites is using the canvas as a background behind HTML content:

```tsx
// Layout: Canvas behind content
<div className="relative min-h-screen">
  {/* 3D Background Layer */}
  <div className="absolute inset-0 -z-10">
    <Canvas gl={{ alpha: true }} style={{ pointerEvents: 'none' }}>
      <BackgroundScene />
    </Canvas>
  </div>

  {/* HTML Content Layer */}
  <div className="relative z-10">
    <HeroContent />
  </div>
</div>
```

### Canvas for Interactive Sections

When the 3D scene is the main content (product viewer, interactive demo):

```tsx
<div className="w-full h-[600px] rounded-2xl overflow-hidden border border-white/10">
  <Canvas camera={{ position: [0, 0, 4], fov: 50 }}>
    <Suspense fallback={<LoadingFallback />}>
      <ProductViewer modelUrl="/models/product.glb" />
      <OrbitControls enableZoom={false} autoRotate autoRotateSpeed={1} />
      <Environment preset="city" />
    </Suspense>
  </Canvas>
</div>
```

### Performance Mode Canvas

For sections where 3D is ambient (not always visible):

```tsx
<Canvas
  frameloop="demand"  // Only render when something changes
  performance={{ min: 0.5 }}  // Adaptive resolution
>
```

---

## Lighting Systems

### Standard Three-Point Lighting

```tsx
function StandardLighting() {
  return (
    <>
      {/* Ambient — base illumination */}
      <ambientLight intensity={0.4} color="#ffffff" />

      {/* Key light — main directional light */}
      <directionalLight
        position={[5, 5, 5]}
        intensity={1}
        color="#ffffff"
        castShadow
      />

      {/* Fill light — soften shadows */}
      <pointLight position={[-5, 0, -5]} intensity={0.3} color="#6366f1" />

      {/* Rim light — edge definition */}
      <pointLight position={[0, 5, -5]} intensity={0.5} color="#8b5cf6" />
    </>
  );
}
```

### Accent-Colored Lighting for Product Niches

```tsx
// AI / SaaS — cool blue-purple
<pointLight position={[5, 3, 5]} intensity={0.8} color="#6366f1" />
<pointLight position={[-5, -2, 3]} intensity={0.4} color="#8b5cf6" />

// Cybersecurity — cyan alerts
<pointLight position={[5, 3, 5]} intensity={0.8} color="#22d3ee" />
<pointLight position={[-5, -2, 3]} intensity={0.3} color="#06b6d4" />

// Creative — warm copper
<pointLight position={[5, 3, 5]} intensity={0.7} color="#d4956a" />
<pointLight position={[-5, -2, 3]} intensity={0.3} color="#e8c49a" />
```

### Environment Maps

```tsx
import { Environment } from '@react-three/drei';

// Preset environments (no file needed)
<Environment preset="night" />    // Dark, moody — best for dark themes
<Environment preset="city" />     // Neutral reflections — product viewers
<Environment preset="studio" />   // Clean lighting — presentations
<Environment preset="sunset" />   // Warm, atmospheric — creative

// Custom HDR environment
<Environment files="/textures/custom-env.hdr" />
```

---

## Common Scene Recipes

### Floating Geometric Background

The classic "premium startup" 3D background — floating shapes with subtle motion:

```tsx
import { Float, MeshDistortMaterial } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';

function FloatingShapes() {
  return (
    <group>
      {/* Main focal shape */}
      <Float speed={2} rotationIntensity={0.5} floatIntensity={1}>
        <mesh position={[0, 0, 0]}>
          <icosahedronGeometry args={[1.5, 1]} />
          <MeshDistortMaterial
            color="#1e1b4b"
            emissive="#6366f1"
            emissiveIntensity={0.4}
            roughness={0.3}
            metalness={0.7}
            distort={0.2}
            speed={2}
          />
        </mesh>
      </Float>

      {/* Orbiting smaller shapes */}
      {[...Array(6)].map((_, i) => (
        <Float key={i} speed={1.5 + i * 0.3} floatIntensity={0.5}>
          <mesh
            position={[
              Math.cos((i / 6) * Math.PI * 2) * 3,
              Math.sin((i / 6) * Math.PI * 2) * 2,
              -2 + Math.random() * 2,
            ]}
            scale={0.2 + Math.random() * 0.3}
          >
            <octahedronGeometry args={[1, 0]} />
            <meshStandardMaterial
              color="#0f0f23"
              emissive="#8b5cf6"
              emissiveIntensity={0.3}
              wireframe={i % 2 === 0}
              transparent
              opacity={0.6}
            />
          </mesh>
        </Float>
      ))}
    </group>
  );
}
```

### Globe / Sphere Visualization

For AI, SaaS, and network products — a globe with connection arcs:

```tsx
import { Sphere, Line } from '@react-three/drei';
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

function Globe() {
  const globeRef = useRef<THREE.Mesh>(null);

  useFrame((_, delta) => {
    if (globeRef.current) {
      globeRef.current.rotation.y += delta * 0.1;
    }
  });

  return (
    <group>
      {/* Main globe */}
      <mesh ref={globeRef}>
        <sphereGeometry args={[2, 64, 64]} />
        <meshStandardMaterial
          color="#0a0a1a"
          emissive="#6366f1"
          emissiveIntensity={0.1}
          roughness={0.8}
          metalness={0.2}
          wireframe
          transparent
          opacity={0.3}
        />
      </mesh>

      {/* Solid inner sphere for depth */}
      <mesh>
        <sphereGeometry args={[1.95, 32, 32]} />
        <meshStandardMaterial
          color="#050510"
          roughness={1}
          metalness={0}
        />
      </mesh>

      {/* Glowing dots on surface */}
      {generateGlobePoints(50).map((pos, i) => (
        <mesh key={i} position={pos} scale={0.03}>
          <sphereGeometry args={[1, 8, 8]} />
          <meshBasicMaterial color="#6366f1" />
        </mesh>
      ))}
    </group>
  );
}

function generateGlobePoints(count: number): [number, number, number][] {
  const points: [number, number, number][] = [];
  for (let i = 0; i < count; i++) {
    const phi = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * Math.PI * 2;
    const r = 2.01;
    points.push([
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.sin(phi) * Math.sin(theta),
      r * Math.cos(phi),
    ]);
  }
  return points;
}
```

### Particle Field

Ambient particle system for hero backgrounds:

```tsx
import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

function ParticleField({ count = 500 }) {
  const points = useRef<THREE.Points>(null);

  const particles = useMemo(() => {
    const positions = new Float32Array(count * 3);
    const sizes = new Float32Array(count);

    for (let i = 0; i < count; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 20;
      sizes[i] = Math.random() * 2;
    }

    return { positions, sizes };
  }, [count]);

  useFrame((_, delta) => {
    if (points.current) {
      points.current.rotation.y += delta * 0.02;
      points.current.rotation.x += delta * 0.01;
    }
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          args={[particles.positions, 3]}
        />
        <bufferAttribute
          attach="attributes-size"
          args={[particles.sizes, 1]}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.02}
        color="#6366f1"
        transparent
        opacity={0.6}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}
```

### Morphing Blob

Abstract organic shape using noise-based distortion:

```tsx
import { MeshDistortMaterial, Sphere } from '@react-three/drei';

function MorphingBlob() {
  return (
    <Sphere args={[1.5, 64, 64]}>
      <MeshDistortMaterial
        color="#1e1b4b"
        emissive="#6366f1"
        emissiveIntensity={0.5}
        roughness={0.2}
        metalness={0.8}
        distort={0.4}
        speed={2}
      />
    </Sphere>
  );
}
```

---

## Geometry Patterns

### Low-Poly Hero Elements

Keep geometry count low for performance:

| Geometry | Triangles | Best For |
|----------|-----------|----------|
| `icosahedronGeometry(1, 0)` | 20 | Low-poly accent shapes |
| `icosahedronGeometry(1, 1)` | 80 | Stylized spheres |
| `octahedronGeometry(1, 0)` | 8 | Diamond/crystal shapes |
| `torusKnotGeometry(1, 0.3, 64, 8)` | ~1k | Organic knot shapes |
| `dodecahedronGeometry(1, 0)` | 36 | Geometric accent |
| `sphereGeometry(1, 32, 32)` | ~2k | Smooth sphere |
| `sphereGeometry(1, 64, 64)` | ~8k | High-quality globe |

### Custom Geometry with Curves

```tsx
import * as THREE from 'three';

function RibbonGeometry() {
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(-3, 0, 0),
    new THREE.Vector3(-1, 1, 1),
    new THREE.Vector3(1, -1, -1),
    new THREE.Vector3(3, 0, 0),
  ]);

  return (
    <mesh>
      <tubeGeometry args={[curve, 64, 0.05, 8, false]} />
      <meshStandardMaterial
        color="#6366f1"
        emissive="#6366f1"
        emissiveIntensity={0.5}
      />
    </mesh>
  );
}
```

---

## Shader Materials

### Gradient Sphere Shader

A glowing gradient sphere — perfect for AI product hero sections:

```tsx
const vertexShader = `
  varying vec2 vUv;
  varying vec3 vNormal;
  void main() {
    vUv = uv;
    vNormal = normalize(normalMatrix * normal);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const fragmentShader = `
  uniform float uTime;
  uniform vec3 uColor1;
  uniform vec3 uColor2;
  varying vec2 vUv;
  varying vec3 vNormal;

  void main() {
    float fresnel = pow(1.0 - dot(vNormal, vec3(0.0, 0.0, 1.0)), 2.0);
    vec3 color = mix(uColor1, uColor2, vUv.y + sin(uTime * 0.5) * 0.1);
    float alpha = fresnel * 0.8 + 0.1;
    gl_FragColor = vec4(color, alpha);
  }
`;

function GradientSphere() {
  const materialRef = useRef<THREE.ShaderMaterial>(null);

  useFrame(({ clock }) => {
    if (materialRef.current) {
      materialRef.current.uniforms.uTime.value = clock.getElapsedTime();
    }
  });

  return (
    <mesh>
      <sphereGeometry args={[2, 64, 64]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent
        uniforms={{
          uTime: { value: 0 },
          uColor1: { value: new THREE.Color('#6366f1') },
          uColor2: { value: new THREE.Color('#a855f7') },
        }}
      />
    </mesh>
  );
}
```

### Animated Wireframe Noise

```tsx
const noiseVertexShader = `
  uniform float uTime;
  varying vec2 vUv;

  // Simplex noise function
  vec3 mod289(vec3 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
  vec4 mod289(vec4 x) { return x - floor(x * (1.0/289.0)) * 289.0; }
  vec4 permute(vec4 x) { return mod289(((x*34.0)+1.0)*x); }
  // ... (include full simplex noise or import via glslify)

  void main() {
    vUv = uv;
    vec3 pos = position;
    float displacement = sin(pos.x * 3.0 + uTime) * sin(pos.y * 3.0 + uTime) * 0.15;
    pos += normal * displacement;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(pos, 1.0);
  }
`;
```

---

## Post-Processing

### Common Effect Combinations

```tsx
import { EffectComposer, Bloom, ChromaticAberration, Vignette } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';

function PostEffects() {
  return (
    <EffectComposer>
      {/* Bloom — glow on bright/emissive surfaces */}
      <Bloom
        luminanceThreshold={0.6}
        luminanceSmoothing={0.9}
        intensity={0.5}
        mipmapBlur
      />

      {/* Chromatic Aberration — subtle RGB split for cinematic feel */}
      <ChromaticAberration
        offset={[0.0005, 0.0005]}
        blendFunction={BlendFunction.NORMAL}
      />

      {/* Vignette — darkened edges for focus */}
      <Vignette
        offset={0.3}
        darkness={0.7}
        blendFunction={BlendFunction.NORMAL}
      />
    </EffectComposer>
  );
}
```

### Post-Processing Performance Rules

- Bloom is the most useful effect — adds cinematic glow to emissive materials
- Chromatic aberration: keep offset below 0.001 — subtlety is key
- Avoid stacking more than 3 effects — each adds a full-screen render pass
- On mobile: disable post-processing entirely or use only Bloom at low intensity
- Use `mipmapBlur` on Bloom for better quality at lower performance cost

---

## Mouse & Scroll Interaction

### Mouse-Follow Camera

```tsx
import { useFrame, useThree } from '@react-three/fiber';

function MouseFollowCamera() {
  const { camera } = useThree();

  useFrame(({ pointer }) => {
    // Smooth follow with damping
    camera.position.x += (pointer.x * 0.5 - camera.position.x) * 0.05;
    camera.position.y += (pointer.y * 0.3 - camera.position.y) * 0.05;
    camera.lookAt(0, 0, 0);
  });

  return null;
}
```

### Mouse-Reactive Particles

```tsx
function ReactiveParticles() {
  const points = useRef<THREE.Points>(null);

  useFrame(({ pointer }) => {
    if (points.current) {
      // Tilt particle field based on mouse position
      points.current.rotation.x = pointer.y * 0.1;
      points.current.rotation.y = pointer.x * 0.1;
    }
  });

  return <points ref={points}>{/* ... geometry & material */}</points>;
}
```

### Scroll-Driven 3D Scene

Using Framer Motion's `useScroll` to drive Three.js animations:

```tsx
import { useScroll } from 'framer-motion';
import { useFrame } from '@react-three/fiber';
import { useRef, useEffect, useState } from 'react';

function ScrollScene() {
  const [scrollProgress, setScrollProgress] = useState(0);

  // In the HTML component wrapping the Canvas:
  // const { scrollYProgress } = useScroll();
  // useMotionValueEvent(scrollYProgress, 'change', setScrollProgress);

  // Pass scrollProgress as a prop or via context to the 3D component

  const groupRef = useRef<THREE.Group>(null);

  useFrame(() => {
    if (groupRef.current) {
      groupRef.current.rotation.y = scrollProgress * Math.PI * 2;
      groupRef.current.position.y = scrollProgress * -5;
    }
  });

  return <group ref={groupRef}>{/* ... scene content */}</group>;
}
```

### GSAP ScrollTrigger + Three.js

```tsx
import { useEffect, useRef } from 'react';
import { useThree } from '@react-three/fiber';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

function ScrollTriggered3D() {
  const { camera } = useThree();

  useEffect(() => {
    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: '#features-section',
        start: 'top center',
        end: 'bottom center',
        scrub: 1,
      },
    });

    tl.to(camera.position, { z: 3, y: 2, duration: 1 });
    tl.to(camera.rotation, { x: -0.3, duration: 1 }, '<');

    return () => { tl.kill(); };
  }, [camera]);

  return null;
}
```

---

## Performance Optimization

### Geometry & Material Optimization

```tsx
// GOOD: Share geometries and materials across instances
const sharedGeometry = new THREE.IcosahedronGeometry(1, 1);
const sharedMaterial = new THREE.MeshStandardMaterial({ color: '#6366f1' });

function OptimizedShapes() {
  return (
    <>
      {positions.map((pos, i) => (
        <mesh key={i} position={pos} geometry={sharedGeometry} material={sharedMaterial} />
      ))}
    </>
  );
}

// EVEN BETTER: Use InstancedMesh for many identical objects
function InstancedShapes({ count = 100 }) {
  const meshRef = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);

  useEffect(() => {
    for (let i = 0; i < count; i++) {
      dummy.position.set(
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10,
      );
      dummy.updateMatrix();
      meshRef.current?.setMatrixAt(i, dummy.matrix);
    }
    meshRef.current!.instanceMatrix.needsUpdate = true;
  }, [count, dummy]);

  return (
    <instancedMesh ref={meshRef} args={[sharedGeometry, sharedMaterial, count]} />
  );
}
```

### Dynamic Import for 3D Components

```tsx
import dynamic from 'next/dynamic';

const HeroScene = dynamic(() => import('@/components/three/HeroScene'), {
  ssr: false,  // Three.js requires browser APIs
  loading: () => <div className="h-screen bg-[#050510]" />,
});
```

### Performance Monitoring

```tsx
import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';

function PerformanceMonitor() {
  const frameCount = useRef(0);
  const lastTime = useRef(performance.now());

  useFrame(() => {
    frameCount.current++;
    const now = performance.now();
    if (now - lastTime.current >= 1000) {
      const fps = frameCount.current;
      if (fps < 30) {
        console.warn(`Low FPS: ${fps} — consider reducing scene complexity`);
      }
      frameCount.current = 0;
      lastTime.current = now;
    }
  });

  return null;
}
```

### Performance Checklist

| Optimization | Impact | How |
|-------------|--------|-----|
| `dpr={[1, 2]}` on Canvas | High | Limits pixel ratio to 2x max |
| `frameloop="demand"` | High | Only render when needed |
| InstancedMesh | High | For many identical objects |
| Shared geometry/materials | Medium | Reduce GPU memory |
| Low-poly geometry | Medium | < 10k triangles per mesh |
| Draco compression for models | Medium | 80-90% smaller file size |
| `dispose()` on unmount | Medium | Prevent memory leaks |
| Texture compression (WebP, basis) | Medium | Smaller download, faster load |
| Frustum culling (default on) | Low | Skip off-screen objects |

---

## Responsive 3D

### Device Detection

```tsx
import { useEffect, useState } from 'react';

function useDeviceCapability() {
  const [capability, setCapability] = useState<'high' | 'medium' | 'low'>('high');

  useEffect(() => {
    const cores = navigator.hardwareConcurrency || 2;
    const isMobile = /Android|iPhone|iPad/.test(navigator.userAgent);
    const hasWebGL2 = !!document.createElement('canvas')
      .getContext('webgl2');

    if (isMobile || cores <= 2 || !hasWebGL2) {
      setCapability('low');
    } else if (cores <= 4) {
      setCapability('medium');
    } else {
      setCapability('high');
    }
  }, []);

  return capability;
}
```

### Adaptive Scene Complexity

```tsx
function AdaptiveScene() {
  const capability = useDeviceCapability();

  return (
    <Canvas
      dpr={capability === 'low' ? [1, 1] : [1, 2]}
      frameloop={capability === 'low' ? 'demand' : 'always'}
    >
      <Suspense fallback={null}>
        {capability === 'high' && (
          <>
            <ParticleField count={1000} />
            <PostEffects />
          </>
        )}
        {capability === 'medium' && (
          <ParticleField count={300} />
        )}
        {capability === 'low' && (
          <SimpleRotatingShape />
        )}
        <HeroGeometry detail={capability === 'high' ? 2 : 0} />
      </Suspense>
    </Canvas>
  );
}
```

---

## Loading & Error Handling

### Canvas Suspense Pattern

```tsx
function Scene3D() {
  return (
    <div className="relative h-screen">
      {/* Loading skeleton shown during 3D init */}
      <div className="absolute inset-0 bg-[#050510] animate-pulse" />

      <Canvas>
        <Suspense fallback={<LoadingIndicator />}>
          <SceneContent />
        </Suspense>
      </Canvas>
    </div>
  );
}

function LoadingIndicator() {
  // This renders inside the Canvas as 3D content
  return (
    <mesh>
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshBasicMaterial color="#6366f1" wireframe />
    </mesh>
  );
}
```

### WebGL Error Boundary

```tsx
import { Component, ReactNode } from 'react';

class WebGLErrorBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error) {
    console.error('WebGL Error:', error);
  }

  render() {
    if (this.state.hasError) {
      return this.props.fallback;
    }
    return this.props.children;
  }
}

// Usage
<WebGLErrorBoundary fallback={<CSSAnimatedBackground />}>
  <Canvas>
    <Scene />
  </Canvas>
</WebGLErrorBoundary>
```

### WebGL Feature Detection

```tsx
function useWebGLSupport() {
  const [supported, setSupported] = useState(true);

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
      setSupported(!!gl);
    } catch {
      setSupported(false);
    }
  }, []);

  return supported;
}
```

---

## Model Loading

### Loading glTF/GLB Models

```tsx
import { useGLTF } from '@react-three/drei';

function ProductModel({ url }: { url: string }) {
  const { scene } = useGLTF(url);

  return <primitive object={scene} scale={1} position={[0, 0, 0]} />;
}

// Preload to start downloading immediately
useGLTF.preload('/models/product.glb');
```

### Model with Animation

```tsx
import { useGLTF, useAnimations } from '@react-three/drei';
import { useEffect } from 'react';

function AnimatedModel({ url }: { url: string }) {
  const { scene, animations } = useGLTF(url);
  const { actions } = useAnimations(animations, scene);

  useEffect(() => {
    actions['idle']?.play();
  }, [actions]);

  return <primitive object={scene} />;
}
```

### Model Optimization Checklist

| Step | Tool | Impact |
|------|------|--------|
| Export as GLB (binary glTF) | Blender / any 3D tool | Smaller file, single file |
| Apply Draco compression | `gltf-pipeline` CLI | 80–90% size reduction |
| Reduce polygon count | Blender decimate modifier | Faster rendering |
| Bake textures to single atlas | Blender | Fewer draw calls |
| Use power-of-2 textures | Image editor | GPU-optimal |
| Max texture size: 2048×2048 | Image editor | Balance quality/performance |

```bash
# Draco compress a GLB file
npx gltf-pipeline -i model.glb -o model-compressed.glb --draco.compressionLevel 7
```
