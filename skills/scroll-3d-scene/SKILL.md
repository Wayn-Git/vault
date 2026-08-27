---
name: scroll-3d-scene
description: Wire up scroll-driven 3D — smooth scrolling with Lenis, scroll-linked timelines and camera moves with GSAP ScrollTrigger, or in-canvas scrolling with drei ScrollControls. Use when the user wants the 3D scene to react to scrolling, a cinematic scroll story, scroll-pinned sections, or camera that moves as the user scrolls.
---

# Scroll-driven 3D scene

Two solid approaches — pick ONE source of truth for scroll so things don't fight.

- **Approach A — Lenis + GSAP ScrollTrigger**: normal DOM page scrolls; scroll drives 3D. Best for marketing/story pages mixing HTML and 3D.
- **Approach B — drei ScrollControls**: scroll lives inside the Canvas over a virtual track. Best for pure 3D experiences.

## Approach A — Lenis + GSAP ScrollTrigger

Install:
```bash
npm i gsap @studio-freight/lenis
```

Smooth scroll + sync to ScrollTrigger (run once at app root):
```tsx
import Lenis from '@studio-freight/lenis'
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useEffect } from 'react'

gsap.registerPlugin(ScrollTrigger)

export function useSmoothScroll() {
  useEffect(() => {
    const lenis = new Lenis({ lerp: 0.1, smoothWheel: true })
    lenis.on('scroll', ScrollTrigger.update)
    const raf = (time: number) => lenis.raf(time * 1000)
    gsap.ticker.add(raf)
    gsap.ticker.lagSmoothing(0)
    return () => { gsap.ticker.remove(raf); lenis.destroy() }
  }, [])
}
```

Drive the 3D camera from scroll. Share scroll progress via a store, then read it in `useFrame`:
```tsx
// store.ts
import { create } from 'zustand'
export const useScrollStore = create<{ progress: number }>(() => ({ progress: 0 }))

// in a component (outside Canvas) — map a section to progress 0..1
useEffect(() => {
  const st = ScrollTrigger.create({
    trigger: '#scene-section',
    start: 'top top',
    end: 'bottom bottom',
    scrub: 1,
    onUpdate: (self) => useScrollStore.setState({ progress: self.progress }),
  })
  return () => st.kill()
}, [])

// inside Canvas — move camera along a path
import { CatmullRomCurve3, Vector3 } from 'three'
const path = new CatmullRomCurve3([
  new Vector3(0, 1.5, 6), new Vector3(3, 2, 2), new Vector3(0, 4, -4),
])
useFrame(() => {
  const p = useScrollStore.getState().progress
  const pos = path.getPointAt(p)
  camera.position.lerp(pos, 0.1)
  camera.lookAt(0, 0, 0)
  invalidate() // if frameloop="demand"
})
```

## Approach B — drei ScrollControls
```tsx
import { ScrollControls, Scroll, useScroll } from '@react-three/drei'

<ScrollControls pages={3} damping={0.2}>
  <Experience />            {/* reads useScroll().offset in useFrame */}
  <Scroll html>            {/* HTML that scrolls with the track */}
    <section>…</section>
  </Scroll>
</ScrollControls>

// inside Experience:
const scroll = useScroll()
useFrame(() => {
  const o = scroll.offset            // 0..1
  group.current.rotation.y = o * Math.PI * 2
})
```

## Always include
- **Reduced motion**: if `matchMedia('(prefers-reduced-motion: reduce)')` matches, disable smooth scroll and jump-cut instead of scrubbing.
- **Cleanup**: kill ScrollTriggers / destroy Lenis on unmount.
- **Mobile**: test touch scroll; if Lenis feels off on mobile, consider `smoothTouch:false`.
- **Damping**: lerp camera/values for smoothness; tune `scrub` and `lerp`.

## Verify
- Scroll through the page and confirm the camera/objects move smoothly in sync, no jitter, correct cleanup on route change.
- For complex choreography, hand off to the **motion-choreographer** agent.
