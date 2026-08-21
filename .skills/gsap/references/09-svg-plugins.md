# GSAP SVG Plugins

## DrawSVGPlugin

Animate SVG stroke drawing/revealing.

**Note (2026-02):** DrawSVGPlugin is available in the public `gsap` npm package (GSAP 3.13+) under the GSAP Standard No-Charge License.

### Setup

```javascript
import gsap from 'gsap'
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin'

gsap.registerPlugin(DrawSVGPlugin)
```

### Basic Usage

```javascript
// Draw from nothing to full stroke
gsap.from('.path', { drawSVG: 0, duration: 2 })

// Draw from full to nothing
gsap.to('.path', { drawSVG: 0, duration: 2 })

// Animate to specific percentage
gsap.to('.path', { drawSVG: '50%', duration: 1 })
```

### Value Formats

```javascript
// Percentage
drawSVG: '0%'           // no stroke visible
drawSVG: '100%'         // full stroke
drawSVG: '50%'          // half stroke from start

// Range (start to end)
drawSVG: '0% 100%'      // full stroke
drawSVG: '20% 80%'      // middle 60%
drawSVG: '40% 60%'      // middle 20%

// From center
drawSVG: '50% 50%'      // nothing (start)
// animate to '0% 100%' for center-out reveal

// Pixels
drawSVG: '100px'        // first 100px
drawSVG: '50px 150px'   // from 50px to 150px

// Live recalculation (for responsive)
drawSVG: '20% 70% live'
```

### Common Patterns

```javascript
// Line draw (from nothing)
gsap.from('.line', { drawSVG: 0, duration: 1 })

// Erase line
gsap.to('.line', { drawSVG: 0, duration: 1 })

// Draw from center
gsap.fromTo('.line',
  { drawSVG: '50% 50%' },
  { drawSVG: '0% 100%', duration: 1 }
)

// Partial reveal
gsap.to('.line', { drawSVG: '20% 80%', duration: 1 })

// Moving segment
gsap.fromTo('.line',
  { drawSVG: '0% 10%' },
  { drawSVG: '90% 100%', duration: 2 }
)

// Staggered paths
gsap.from('.path', {
  drawSVG: 0,
  duration: 1,
  stagger: 0.1
})
```

### Utility Methods

```javascript
// Get stroke length
const length = DrawSVGPlugin.getLength(pathElement)

// Get current position
const [start, end] = DrawSVGPlugin.getPosition(pathElement)
```

### CSS Requirements

```css
/* Stroke must be defined */
.path {
  stroke: #000;
  stroke-width: 2px;
  fill: none;
}
```

---

## MorphSVGPlugin

Morph between SVG shapes.

**Note (2026-02):** MorphSVGPlugin is available in the public `gsap` npm package (GSAP 3.13+) under the GSAP Standard No-Charge License.

### Setup

```javascript
import gsap from 'gsap'
import { MorphSVGPlugin } from 'gsap/MorphSVGPlugin'

gsap.registerPlugin(MorphSVGPlugin)
```

### Basic Morphing

```javascript
// Morph to another path
gsap.to('#circle', {
  morphSVG: '#star',
  duration: 1
})

// Using path data string
gsap.to('#shape', {
  morphSVG: 'M10,50 Q50,10 90,50 Q50,90 10,50',
  duration: 1
})
```

### Configuration

```javascript
gsap.to('#shape1', {
  morphSVG: {
    shape: '#shape2',
    shapeIndex: 0,        // point mapping (0, 1, 2, ... or 'auto')
    map: 'complexity',    // or 'position', 'size'
    origin: '50% 50%',    // transform origin
    render: customFunc    // custom render function
  },
  duration: 2
})
```

### Shape Index

Controls how points map between shapes:

```javascript
// Auto-detect best mapping
gsap.to('#start', { morphSVG: { shape: '#end', shapeIndex: 'auto' } })

// Specific offset
gsap.to('#start', { morphSVG: { shape: '#end', shapeIndex: 3 } })

// Negative reverses direction
gsap.to('#start', { morphSVG: { shape: '#end', shapeIndex: -1 } })

// Find best index visually (dev tool)
MorphSVGPlugin.findShapeIndex('#start', '#end')
```

### Converting Shapes to Paths

```javascript
// Convert specific element
MorphSVGPlugin.convertToPath('#circle')
MorphSVGPlugin.convertToPath('#rect')

// Convert all convertible shapes
MorphSVGPlugin.convertToPath('circle, rect, ellipse, line, polygon, polyline')
```

### Morph Patterns

```javascript
// Simple morph
gsap.to('#circle', {
  morphSVG: '#square',
  duration: 1,
  ease: 'power2.inOut'
})

// Through multiple shapes
const tl = gsap.timeline({ repeat: -1 })
tl.to('#shape', { morphSVG: '#circle', duration: 1 })
  .to('#shape', { morphSVG: '#star', duration: 1 })
  .to('#shape', { morphSVG: '#heart', duration: 1 })
```

---

## MotionPathPlugin

Animate elements along SVG paths.

### Setup

```javascript
import gsap from 'gsap'
import { MotionPathPlugin } from 'gsap/MotionPathPlugin'

gsap.registerPlugin(MotionPathPlugin)
```

### Basic Usage

```javascript
// Follow SVG path
gsap.to('.element', {
  motionPath: '#path',
  duration: 5
})

// Using path data
gsap.to('.element', {
  motionPath: 'M0,0 C100,0 100,100 0,100',
  duration: 2
})
```

### Configuration

```javascript
gsap.to('.element', {
  motionPath: {
    path: '#path',
    align: '#path',           // align to path
    alignOrigin: [0.5, 0.5],  // center of element
    autoRotate: true,         // rotate to follow path
    start: 0,                 // start position (0-1)
    end: 1                    // end position (0-1)
  },
  duration: 5,
  ease: 'none'
})
```

### Auto Rotate

```javascript
// Follow path direction
autoRotate: true

// With offset (degrees)
autoRotate: 90              // 90° offset

// Advanced
autoRotate: [0, 0, 0]       // [positionX, positionY, angle]
```

### Partial Path

```javascript
gsap.to('.element', {
  motionPath: {
    path: '#path',
    start: 0.25,    // start 25% along path
    end: 0.75       // end at 75%
  },
  duration: 2
})
```

### Convert to Path

```javascript
// Convert coordinates to path
const path = MotionPathPlugin.convertToPath([
  { x: 0, y: 0 },
  { x: 100, y: 50 },
  { x: 200, y: 0 }
], { curviness: 1 })
```

### Get Position on Path

```javascript
// Get raw path data
const rawPath = MotionPathPlugin.getRawPath('#path')

// Get point at position
const point = MotionPathPlugin.getRelativePosition(
  rawPath,
  0,      // segment
  0.5     // progress (0-1)
)
```

### Motion Path Patterns

```javascript
// Orbit animation
gsap.to('.satellite', {
  motionPath: {
    path: '#orbit',
    align: '#orbit',
    alignOrigin: [0.5, 0.5],
    autoRotate: true
  },
  duration: 10,
  repeat: -1,
  ease: 'none'
})

// Car following road
gsap.to('.car', {
  motionPath: {
    path: '#road',
    align: '#road',
    autoRotate: 90,
    alignOrigin: [0.5, 0.5]
  },
  duration: 5,
  ease: 'power1.inOut'
})

// Bezier motion (without visible path)
gsap.to('.element', {
  motionPath: {
    path: [
      { x: 0, y: 0 },
      { x: 100, y: -100 },
      { x: 200, y: 0 },
      { x: 300, y: 100 }
    ],
    curviness: 1.5
  },
  duration: 2
})
```

---

## Combined SVG Animation

```javascript
// Logo animation combining all
const tl = gsap.timeline()

// Draw logo outline
tl.from('.logo-path', {
  drawSVG: 0,
  duration: 2,
  stagger: 0.2
})

// Morph icon
.to('.icon', {
  morphSVG: '#final-icon',
  duration: 1
}, '-=0.5')

// Animate element along path
.to('.dot', {
  motionPath: {
    path: '#logo-path',
    align: '#logo-path',
    alignOrigin: [0.5, 0.5]
  },
  duration: 3,
  ease: 'power1.inOut'
}, '-=1')
```
