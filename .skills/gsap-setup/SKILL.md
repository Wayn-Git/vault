---
name: gsap-setup
description: Use when setting up GSAP in a project, installing GSAP, registering plugins, configuring defaults, or implementing GSAP best practices and workflows.
---

# GSAP Setup and Best Practices

Proper GSAP setup ensures smooth development, optimal performance, and maintainable code. Learn installation, plugin registration, configuration, and industry best practices.

## Installation

### NPM Installation

```bash
# Core GSAP
npm install gsap

# React integration
npm install @gsap/react

# All plugins are included in gsap package
# No separate installation needed
```

### CDN Installation

```html
<!-- GSAP Core -->
<script src="https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js"></script>

<!-- ScrollTrigger -->
<script src="https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/ScrollTrigger.min.js"></script>

<!-- Other plugins as needed -->
<script src="https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/Draggable.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/Flip.min.js"></script>
```

### ES Modules (CDN)

```html
<script type="module">
  import gsap from 'https://cdn.jsdelivr.net/npm/gsap@3.13.0/index.js'
  import { ScrollTrigger } from 'https://cdn.jsdelivr.net/npm/gsap@3.13.0/ScrollTrigger.js'

  gsap.registerPlugin(ScrollTrigger)
</script>
```

## Project Setup

### Basic Setup

```javascript
// gsap.js - Central GSAP configuration
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Draggable } from 'gsap/Draggable'

// Register all plugins once
gsap.registerPlugin(ScrollTrigger, Draggable)

// Set global defaults
gsap.defaults({
  ease: 'power2.out',
  duration: 1
})

// Configure ScrollTrigger
ScrollTrigger.config({
  ignoreMobileResize: true,
  autoRefreshEvents: 'visibilitychange,DOMContentLoaded,load'
})

export { gsap }
```

### Advanced Setup

```javascript
// gsap.js
import gsap from 'gsap'

// Plugins (all shipped in the public `gsap` npm package; some were formerly members-only)
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Observer } from 'gsap/Observer'
import { Draggable } from 'gsap/Draggable'
import { Flip } from 'gsap/Flip'
import { ScrollToPlugin } from 'gsap/ScrollToPlugin'

// Formerly members-only / bonus plugins
import { SplitText } from 'gsap/SplitText'
import { MorphSVGPlugin } from 'gsap/MorphSVGPlugin'
import { MotionPathPlugin } from 'gsap/MotionPathPlugin'
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin'
import { CustomEase } from 'gsap/CustomEase'
import { MotionPathHelper } from 'gsap/MotionPathHelper'

// Register all plugins
gsap.registerPlugin(
  ScrollTrigger,
  Observer,
  Draggable,
  Flip,
  ScrollToPlugin,
  SplitText,
  MorphSVGPlugin,
  MotionPathPlugin,
  DrawSVGPlugin,
  ScrambleTextPlugin,
  CustomEase,
  MotionPathHelper
)

// Global configuration
gsap.defaults({
  ease: 'power2.out',
  duration: 1,
  overwrite: 'auto'
})

// Ticker configuration
gsap.ticker.lagSmoothing(1000, 16)

// Custom ease definitions
CustomEase.create('smooth', 'M0,0 C0.5,0 0.5,1 1,1')

// Export configured gsap instance
export default gsap
```

## Plugin Registration

### Register Plugins

```javascript
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Draggable } from 'gsap/Draggable'

// Register all plugins at once
gsap.registerPlugin(ScrollTrigger, Draggable)

// Or register individually
gsap.registerPlugin(ScrollTrigger)
gsap.registerPlugin(Draggable)
```

### Register with React Hook

```javascript
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

// Register hook and plugins
gsap.registerPlugin(useGSAP, ScrollTrigger)
```

### Conditional Registration

```javascript
import gsap from 'gsap'

// Only register needed plugins
const useScrollTrigger = true
const useDraggable = false

if (useScrollTrigger) {
  import('gsap/ScrollTrigger').then(({ ScrollTrigger }) => {
    gsap.registerPlugin(ScrollTrigger)
  })
}

if (useDraggable) {
  import('gsap/Draggable').then(({ Draggable }) => {
    gsap.registerPlugin(Draggable)
  })
}
```

## Global Configuration

### Defaults

```javascript
// Set global defaults
gsap.defaults({
  ease: 'power2.out',
  duration: 1,
  delay: 0,
  overwrite: 'auto',
  lazy: true
})

// Override defaults in individual tweens
gsap.to('.box', {
  x: 200,
  duration: 2,  // Overrides default
  ease: 'back.out(1.7)'  // Overrides default
})
```

### Timeline Defaults

```javascript
const tl = gsap.timeline({
  defaults: {
    ease: 'power2.out',
    duration: 1
  },
  paused: true,
  repeat: -1,
  yoyo: true
})

// All tweens in timeline inherit defaults
tl.to('.box1', { x: 100 })  // Uses defaults
  .to('.box2', { x: 200, ease: 'back.out' })  // Overrides ease
```

### ScrollTrigger Config

```javascript
ScrollTrigger.config({
  // Ignore mobile resize events (improves performance)
  ignoreMobileResize: true,

  // Custom auto-refresh events
  autoRefreshEvents: 'visibilitychange,DOMContentLoaded,load',

  // Default markers (development only)
  defaultMarkers: false,

  // Normalize scroll
  normalizeScroll: true
})
```

## Development Setup

### Development Configuration

```javascript
// gsap.dev.js
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

// Enable markers in development
if (process.env.NODE_ENV === 'development') {
  ScrollTrigger.config({
    defaultMarkers: true
  })

  // Log all tweens
  gsap.registerEffect({
    name: 'debugTween',
    effect: (targets, config) => {
      return gsap.to(targets, config)
    },
    extendTimeline: true
  })
}

export { gsap }
```

### Production Configuration

```javascript
// gsap.prod.js
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

// Production optimizations
ScrollTrigger.config({
  ignoreMobileResize: true,
  autoRefreshEvents: 'visibilitychange,DOMContentLoaded,load'
})

// Disable markers
ScrollTrigger.config({
  defaultMarkers: false
})

export { gsap }
```

## Project Structure

### Feature-Based Structure

```
src/
├── gsap/
│   ├── gsap.js           # Central configuration
│   ├── animations.js     # Reusable animations
│   └── constants.js      # Eases, durations, etc.
├── components/
│   ├── Hero/
│   │   ├── Hero.jsx
│   │   └── heroAnimations.js
│   └── About/
│       ├── About.jsx
│       └── aboutAnimations.js
```

### Animation Modules

```javascript
// gsap/animations.js
import { gsap } from './gsap'

// Reusable entrance animation
export const entranceAnimation = (elements, options = {}) => {
  return gsap.from(elements, {
    opacity: 0,
    y: 30,
    stagger: 0.1,
    duration: 0.8,
    ease: 'power2.out',
    ...options
  })
}

// Reusable hover animation
export const hoverAnimation = (element, options = {}) => {
  const tl = gsap.timeline({ paused: true })

  tl.to(element, {
      scale: 1.1,
      duration: 0.3,
      ease: 'power2.out'
    })
    .to(element, {
      scale: 1,
      duration: 0.3,
      ease: 'power2.out'
    }, '+=0.5')

  return tl
}
```

## Environment Configuration

### Development vs Production

```javascript
// gsap/config.js
const isDevelopment = process.env.NODE_ENV === 'development'

export const config = {
  // Enable debug tools in development
  debug: isDevelopment,

  // Performance optimizations
  performance: !isDevelopment,

  // Animation speed multiplier (for testing)
  speedMultiplier: isDevelopment ? 0.5 : 1,

  // Easing presets
  eases: {
    ui: 'power2.out',
    entrance: 'back.out(1.7)',
    exit: 'power2.in',
    playful: 'elastic.out(1, 0.3)'
  },

  // Duration presets
  durations: {
    fast: 0.3,
    normal: 0.8,
    slow: 1.5
  }
}

export default config
```

## Best Practices

### 1. Register Plugins Once

```javascript
// ✅ Register all plugins in one place
gsap.registerPlugin(ScrollTrigger, Draggable, Flip)

// ❌ Don't register multiple times
import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.registerPlugin(ScrollTrigger)  // In one file

import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.registerPlugin(ScrollTrigger)  // In another file - redundant!
```

### 2. Use Named Exports

```javascript
// ✅ Use named exports for tree-shaking
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

// ❌ Avoid default imports when possible
import gsap from 'gsap'  // Can't be tree-shaken as effectively
```

### 3. Centralize Configuration

```javascript
// ✅ Central GSAP configuration
// gsap.js
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)
gsap.defaults({ ease: 'power2.out', duration: 1 })

export default gsap

// Import configured gsap
import gsap from './gsap'

// ❌ Scattered configuration
import gsap from 'gsap'
gsap.defaults({ ease: 'power2.out' })  // In one file

import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.registerPlugin(ScrollTrigger)  // In another file
```

### 4. Set Global Defaults

```javascript
// ✅ Use defaults for consistency
gsap.defaults({
  ease: 'power2.out',
  duration: 1
})

// All tweens inherit these defaults
gsap.to('.box', { x: 200 })
gsap.from('.modal', { opacity: 0 })

// ❌ Repeating values
gsap.to('.box', { x: 200, ease: 'power2.out', duration: 1 })
gsap.from('.modal', { opacity: 0, ease: 'power2.out', duration: 1 })
```

### 5. Use Timelines for Sequences

```javascript
// ✅ Use timeline for sequences
const tl = gsap.timeline()
tl.to('.box1', { x: 100 })
  .to('.box2', { x: 100 })
  .to('.box3', { x: 100 })

// Easy to control
tl.play()
tl.reverse()
tl.kill()

// ❌ Separate tweens
gsap.to('.box1', { x: 100, delay: 0 })
gsap.to('.box2', { x: 100, delay: 1 })
gsap.to('.box3', { x: 100, delay: 2 })
```

### 6. Clean Up Animations

```javascript
// ✅ Clean up when component unmounts
function MyComponent() {
  useGSAP(() => {
    const tl = gsap.timeline()
    tl.to('.box', { x: 200 })

    // Automatically cleaned up
  })

  return <div className="box"></div>
}

// ❌ Memory leaks
function MyComponent() {
  useEffect(() => {
    const tl = gsap.timeline()
    tl.to('.box', { x: 200 })
    // Never cleaned up!
  }, [])

  return <div className="box"></div>
}
```

### 7. Test on Low-End Devices

```javascript
// ✅ Performance considerations
gsap.to('.many-boxes', {
  x: 100,
  duration: 1,
  ease: 'power2.out',  // Simpler ease, better performance
  stagger: 0.05,           // Distribute load
  onComplete: () => {
    // Clean up when done
    gsap.killTweensOf('.many-boxes')
  }
})

// ❌ Too complex for low-end devices
gsap.to('.many-boxes', {
  x: 100,
  duration: 1,
  ease: 'elastic.out(1, 0.3)',  // Complex, slow
  stagger: 0.01  // Too many tweens
})
```

### 8. Use Appropriate Eases

```javascript
// ✅ Match ease to use case
gsap.from('.modal', {
  opacity: 0,
  scale: 0.8,
  ease: 'back.out(1.7)',  // Attention-grabbing entrance
  duration: 0.5
})

// ❌ Wrong ease for context
gsap.from('.modal', {
  opacity: 0,
  scale: 0.8,
  ease: 'elastic.out(1, 0.3)',  // Too much for modal
  duration: 0.5
})
```

### 9. Implement Responsive Animations

```javascript
// ✅ Responsive with matchMedia
const mm = gsap.matchMedia()

mm.add('(min-width: 768px)', () => {
  gsap.to('.box', { x: 200, duration: 1 })
})

mm.add('(max-width: 767px)', () => {
  gsap.to('.box', { x: 100, duration: 1 })
})

// ❌ Not responsive
gsap.to('.box', { x: 200, duration: 1 })  // Same for all screens
```

### 10. Use Selectors Wisely

```javascript
// ✅ Scoped selectors
const q = gsap.utils.selector('.container')
gsap.to(q('.box'), { x: 200 })

// Or in React
useGSAP(() => {
  gsap.to('.box', { x: 200 })
}, { scope: container })

// ❌ Global selectors
gsap.to('.box', { x: 200 })  // Affects ALL .box elements
```

## Common Mistakes

### 1. Not Registering Plugins

```javascript
// ❌ Plugin won't work
import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.to('.box', {
  scrollTrigger: { trigger: '.box' }
})

// ✅ Register plugin first
import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.registerPlugin(ScrollTrigger)
gsap.to('.box', {
  scrollTrigger: { trigger: '.box' }
})
```

### 2. Using Wrong Import Style

```javascript
// ❌ Can't be tree-shaken
import gsap from 'gsap'

// ✅ Use named imports
import { gsap } from 'gsap'
```

### 3. Conflicting Tweens

```javascript
// ❌ Two tweens fighting
gsap.to('.box', { x: 100, duration: 2 })
gsap.to('.box', { x: 200, duration: 1 })

// ✅ Use overwrite or kill first
gsap.to('.box', { x: 100, duration: 2, overwrite: true })
// Or
gsap.killTweensOf('.box', 'x')
gsap.to('.box', { x: 200, duration: 1 })
```

### 4. Forgetting Cleanup

```javascript
// ❌ Memory leaks
useEffect(() => {
  gsap.to('.box', { x: 200 })
}, [])

// ✅ Use useGSAP in React
useGSAP(() => {
  gsap.to('.box', { x: 200 })
}, { scope: container })
```

### 5. Not Testing Performance

```javascript
// ❌ Works on dev machine, slow on others
gsap.to('.many-complex-elements', {
  filter: 'blur(10px)',
  duration: 1
})

// ✅ Test and optimize
gsap.to('.many-complex-elements', {
  opacity: 0.8,  // Simpler property
  duration: 1
})
```

## Performance Checklist

- [ ] Register plugins once at app entry
- [ ] Use named exports for tree-shaking
- [ ] Set global defaults for consistency
- [ ] Use timelines for sequences
- [ ] Clean up animations when done
- [ ] Test on low-end devices
- [ ] Use appropriate eases
- [ ] Implement responsive animations
- [ ] Scope selectors to prevent conflicts
- [ ] Use transform properties over layout properties
- [ ] Stagger animations to distribute load
- [ ] Avoid filters on many elements
- [ ] Kill tweens before creating new ones
- [ ] Use ScrollTrigger toggleActions over scrub when possible
- [ ] Refresh ScrollTrigger after DOM changes

## Quick Reference

| Task | Solution |
|------|----------|
| Install GSAP | `npm install gsap` |
| Import core | `import { gsap } from 'gsap'` |
| Import plugin | `import { ScrollTrigger } from 'gsap/ScrollTrigger'` |
| Register plugins | `gsap.registerPlugin(ScrollTrigger)` |
| Set defaults | `gsap.defaults({ ease, duration })` |
| CDN script | `<script src="https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js">` |
| React integration | `npm install @gsap/react` |
| React hook | `import { useGSAP } from '@gsap/react'` |
| Formerly members-only plugin | Install from `gsap` (v3.13+) and follow https://gsap.com/community/standard-license/ |
| Tree-shaking | Use named exports |
| Cleanup | `useGSAP` or manual `kill()` |
