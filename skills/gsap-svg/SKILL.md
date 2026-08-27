---
name: gsap-svg
description: Use when implementing SVG animations, stroke drawing, path morphing, motion along paths, or using DrawSVGPlugin, MorphSVGPlugin, MotionPathPlugin.
---

# GSAP SVG Animations

GSAP provides powerful SVG animation tools through DrawSVGPlugin, MorphSVGPlugin, and MotionPathPlugin. Create stunning stroke animations, smooth shape transformations, and element movement along paths.

## Installation

### DrawSVGPlugin (formerly members-only; now included)

```bash
npm install gsap
```

```javascript
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'
gsap.registerPlugin(DrawSVGPlugin)
```

### MorphSVGPlugin (formerly members-only; now included)

```javascript
import { MorphSVGPlugin } from 'gsap/MorphSVGPlugin'
gsap.registerPlugin(MorphSVGPlugin)
```

### MotionPathPlugin (formerly members-only; now included)

```javascript
import { MotionPathPlugin } from 'gsap/MotionPathPlugin'
gsap.registerPlugin(MotionPathPlugin)
```

## DrawSVGPlugin

### Basic Draw

```javascript
gsap.registerPlugin(DrawSVGPlugin)

// Draw stroke from 0 to 100%
gsap.to('#path', {
  drawSVG: '0% 100%',
  duration: 2
})
```

### Draw from Start

```javascript
// Draw from start to end
gsap.to('#path', {
  drawSVG: true,
  duration: 2
})
```

### Draw with Delay

```javascript
// Start drawing from 30%, end at 100%
gsap.to('#path', {
  drawSVG: '30% 100%',
  duration: 2
})
```

### Draw Backwards

```javascript
// Draw from end to start
gsap.to('#path', {
  drawSVG: '100% 0%',
  duration: 2
})
```

### Multiple Paths

```javascript
// Draw all paths
gsap.to('path', {
  drawSVG: '0% 100%',
  stagger: 0.2,
  duration: 2
})
```

### Partial Draw

```javascript
// Draw middle section
gsap.to('#path', {
  drawSVG: '30% 70%',
  duration: 2
})
```

### Drawing Specific Elements

```javascript
// Draw line
gsap.to('line', {
  drawSVG: true,
  duration: 1
})

// Draw polyline
gsap.to('polyline', {
  drawSVG: true,
  duration: 1
})

// Draw polygon
gsap.to('polygon', {
  drawSVG: true,
  duration: 1
})

// Draw circle
gsap.to('circle', {
  drawSVG: true,
  duration: 1
})

// Draw rectangle
gsap.to('rect', {
  drawSVG: true,
  duration: 1
})
```

### Stroke Width Animation

```javascript
gsap.to('#path', {
  drawSVG: '0% 100%',
  strokeWidth: 10,
  duration: 2
})
```

### Draw with ScrollTrigger

```javascript
gsap.registerPlugin(ScrollTrigger, DrawSVGPlugin)

gsap.to('#path', {
  drawSVG: '0% 100%',
  scrollTrigger: {
    trigger: '#path',
    start: 'top center',
    end: 'bottom center',
    scrub: true
  }
})
```

### Draw Sequence

```javascript
const tl = gsap.timeline()

tl.to('#path1', { drawSVG: '0% 100%', duration: 1 })
  .to('#path2', { drawSVG: '0% 100%', duration: 1 })
  .to('#path3', { drawSVG: '0% 100%', duration: 1 })
```

### Erase and Redraw

```javascript
gsap.to('#path', {
  drawSVG: '100% 100%',
  duration: 1,
  onComplete: () => {
    gsap.to('#path', {
      drawSVG: '0% 100%',
      duration: 2
    })
  }
})
```

### Icon Animation

```javascript
// Draw icon paths
gsap.to('.icon path', {
  drawSVG: '0% 100%',
  stagger: 0.1,
  duration: 1.5,
  ease: 'power2.inOut'
})
```

## MorphSVGPlugin

### Basic Morph

```javascript
gsap.registerPlugin(MorphSVGPlugin)

// Morph shape1 into shape2
gsap.to('#shape1', {
  morphSVG: '#shape2',
  duration: 1
})
```

### Morph with Shape Index

```javascript
// Control point matching with shapeIndex
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    shapeIndex: 5
  },
  duration: 1
})
```

### Auto Shape Index

```javascript
// Let GSAP find best match
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    shapeIndex: 'auto'
  },
  duration: 1
})
```

### Rotational Morph

```javascript
// Use rotational matching
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    type: 'rotational'
  },
  duration: 1
})
```

### Smooth Morph

```javascript
// Add intermediate points for smoother transition
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    smooth: true
  },
  duration: 1
})
```

### Morph Primitives

```javascript
// Morph circle to square (auto converts to path)
gsap.to('#circle', {
  morphSVG: '#square',
  duration: 1
})

// Or convert explicitly
MorphSVGPlugin.convertToPath('#circle')
MorphSVGPlugin.convertToPath('circle')  // Convert all circles
```

### Multiple Shapes

```javascript
// Morph multiple shapes
gsap.to('.shape', {
  morphSVG: i => {
    const targets = ['.shape1', '.shape2', '.shape3']
    return targets[i % targets.length]
  },
  duration: 1
})
```

### Morph Sequence

```javascript
const tl = gsap.timeline()

tl.to('#shape', {
    morphSVG: '#shape2',
    duration: 1
  })
  .to('#shape', {
    morphSVG: '#shape3',
    duration: 1
  })
  .to('#shape', {
    morphSVG: '#shape1',
    duration: 1
  })
```

### Morph with ScrollTrigger

```javascript
gsap.registerPlugin(ScrollTrigger, MorphSVGPlugin)

gsap.to('#shape', {
  morphSVG: '#shape2',
  scrollTrigger: {
    trigger: '#shape',
    start: 'top center',
    end: 'bottom center',
    scrub: true
  }
})
```

### Hover Morph

```javascript
const hoverMorph = gsap.to('#icon', {
  morphSVG: '#icon-hover',
  duration: 0.3,
  ease: 'power2.out',
  paused: true
})

document.querySelector('#icon').addEventListener('mouseenter', () => hoverMorph.play())
document.querySelector('#icon').addEventListener('mouseleave', () => hoverMorph.reverse())
```

### Icon Morph

```javascript
// Morph between icon states
gsap.to('#icon', {
  morphSVG: '#icon-active',
  duration: 0.5,
  ease: 'elastic.out(1, 0.5)'
})
```

## MotionPathPlugin

### Basic Motion

```javascript
gsap.registerPlugin(MotionPathPlugin)

// Move element along path
gsap.to('#box', {
  motionPath: {
    path: '#path',
    align: '#path',
    alignOrigin: [0.5, 0.5]
  },
  duration: 3
})
```

### Auto Rotate

```javascript
// Rotate element to follow path direction
gsap.to('#box', {
  motionPath: {
    path: '#path',
    autoRotate: true
  },
  duration: 3
})
```

### Custom Start/End

```javascript
// Control start and end positions
gsap.to('#box', {
  motionPath: {
    path: '#path',
    start: 0.25,    // Start at 25% of path
    end: 0.75        // End at 75% of path
  },
  duration: 3
})
```

### Path String

```javascript
// Use path string directly
gsap.to('#box', {
  motionPath: {
    path: 'M10 10 L100 100 L200 50',
    autoRotate: true
  },
  duration: 3
})
```

### Array of Points

```javascript
// Use array of coordinates
gsap.to('#box', {
  motionPath: {
    path: [
      { x: 10, y: 10 },
      { x: 100, y: 100 },
      { x: 200, y: 50 }
    ],
    autoRotate: true
  },
  duration: 3
})
```

### Offset Path

```javascript
// Offset from path
gsap.to('#box', {
  motionPath: {
    path: '#path',
    offsetX: 20,
    offsetY: -20,
    autoRotate: true
  },
  duration: 3
})
```

### Curved Path

```javascript
// Curved path with bezier
gsap.to('#box', {
  motionPath: {
    path: 'M0 0 C100 100, 200 0, 300 100',
    autoRotate: true
  },
  duration: 3
})
```

### Motion with ScrollTrigger

```javascript
gsap.registerPlugin(ScrollTrigger, MotionPathPlugin)

gsap.to('#box', {
  motionPath: {
    path: '#path',
    autoRotate: true
  },
  scrollTrigger: {
    trigger: '#path',
    start: 'top center',
    end: 'bottom center',
    scrub: true
  }
})
```

### Trail Effect

```javascript
// Create trail following path
const trail = document.querySelectorAll('.trail-point')

gsap.to(trail, {
  motionPath: {
    path: '#path',
    align: '#path',
    alignOrigin: [0.5, 0.5]
  },
  stagger: 0.1,
  duration: 3,
  repeat: -1,
  yoyo: true
})
```

### Orbit Animation

```javascript
// Circular orbit
gsap.to('#planet', {
  motionPath: {
    path: 'M150 0 A150 150 0 1 1 150 0 A150 150 0 1 1 150 0',
    align: '#sun',
    autoRotate: true,
    start: 0,
    end: 1
  },
  duration: 5,
  repeat: -1,
  ease: 'none'
})
```

### Path Drawing + Motion

```javascript
gsap.registerPlugin(DrawSVGPlugin, MotionPathPlugin)

// Draw path and move element
const tl = gsap.timeline()

tl.to('#path', {
    drawSVG: '0% 100%',
    duration: 2
  })
  .to('#box', {
    motionPath: {
      path: '#path',
      autoRotate: true
    },
    duration: 2
  }, 0)
```

## Combined Effects

### Draw + Morph

```javascript
gsap.registerPlugin(DrawSVGPlugin, MorphSVGPlugin)

const tl = gsap.timeline()

tl.to('#shape1', {
    drawSVG: '0% 100%',
    duration: 1
  })
  .to('#shape1', {
    morphSVG: '#shape2',
    duration: 1
  })
```

### Morph + Motion

```javascript
gsap.registerPlugin(MorphSVGPlugin, MotionPathPlugin)

// Morph shape and move along path
gsap.to('#shape', {
  morphSVG: '#morph-target',
  motionPath: {
    path: '#path',
    autoRotate: true
  },
  duration: 3
})
```

### Complex Sequence

```javascript
const tl = gsap.timeline()

tl.to('#path1', {
    drawSVG: '0% 100%',
    duration: 1
  })
  .to('#icon', {
    morphSVG: '#icon2',
    duration: 0.5
  })
  .to('#icon', {
    motionPath: {
      path: '#path2',
      autoRotate: true
    },
    duration: 1.5
  })
  .to('#path2', {
    drawSVG: '0% 100%',
    duration: 1
  })
```

## Performance Tips

### Use Correct Elements

```javascript
// ❌ Trying to animate non-SVG elements
gsap.to('.div', { drawSVG: true })

// ✅ Only SVG elements
gsap.to('#path', { drawSVG: true })
```

### Optimize Paths

```javascript
// ❌ Too many points, slow performance
const complexPath = '<path d="M0 0 L1 1 L2 2 ... L1000 1000" />'

// ✅ Simplified paths
const simplePath = '<path d="M0 0 Q500 500 1000 0" />'
```

### Cache Morph Targets

```javascript
// Cache morph targets for reuse
const morphTargets = ['#shape1', '#shape2', '#shape3']

gsap.to('#current', {
  morphSVG: morphTargets[Math.floor(Math.random() * morphTargets.length)],
  duration: 1
})
```

## Common Mistakes

### 1. Missing Stroke

```javascript
// ❌ No stroke to draw
const path = '<path d="M0 0 L100 100" />'

// ✅ Add stroke
const path = '<path d="M0 0 L100 100" stroke="black" stroke-width="2" fill="none" />'
```

### 2. Wrong Shape Index

```javascript
// ❌ Morph looks wrong
gsap.to('#shape1', {
  morphSVG: '#shape2',
  duration: 1
})

// ✅ Find correct shapeIndex
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    shapeIndex: 3
  },
  duration: 1
})
```

### 3. Auto Rotate Issues

```javascript
// ❌ Wrong rotation direction
gsap.to('#box', {
  motionPath: {
    path: '#path',
    autoRotate: true
  }
})

// ✅ Adjust transform origin
gsap.set('#box', { transformOrigin: 'center center' })
gsap.to('#box', {
  motionPath: {
    path: '#path',
    autoRotate: true
  }
})
```

## Best Practices

1. **Add stroke for DrawSVG** - Fill alone won't work
2. **Test shapeIndex** - Find optimal matching for morphs
3. **Use autoRotate carefully** - Set transformOrigin correctly
4. **Optimize path complexity** - Fewer points = better performance
5. **Combine with ScrollTrigger** - Create scroll-driven SVG effects
6. **Use easing** - Add appropriate eases for natural motion
7. **Test in browsers** - SVG rendering can vary
8. **Use smooth morph** - For complex shape transitions

## Quick Reference

| Feature | Method |
|---------|--------|
| Draw stroke | `gsap.to(target, { drawSVG: '0% 100%' })` |
| Morph shape | `gsap.to(target, { morphSVG: '#target' })` |
| Motion along path | `gsap.to(target, { motionPath: { path: '#path' } })` |
| Auto rotate | `motionPath: { autoRotate: true }` |
| Shape index | `morphSVG: { shapeIndex: 5 }` |
| Rotational morph | `morphSVG: { type: 'rotational' }` |
| Convert to path | `MorphSVGPlugin.convertToPath(target)` |
| Path string | `motionPath: { path: 'M0 0 L100 100' }` |
