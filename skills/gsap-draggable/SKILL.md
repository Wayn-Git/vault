---
name: gsap-draggable
description: Use when implementing drag interactions, draggable elements, throwing with inertia, bounds enforcement, drag-based UI, or using Draggable and InertiaPlugin.
---

# GSAP Draggable

Draggable enables drag, throw, rotation, and inertia-based interactions on any DOM element. Perfect for sliders, puzzles, games, and interactive UI components.

## Installation

```bash
npm install gsap
```

```javascript
import { Draggable } from 'gsap/Draggable'
import { InertiaPlugin } from 'gsap/InertiaPlugin'

gsap.registerPlugin(Draggable, InertiaPlugin)
```

## Basic Drag

### X/Y Drag

```javascript
gsap.registerPlugin(Draggable)

// Enable drag on both axes
Draggable.create('.box', {
  type: 'x,y',
  bounds: '.container'
})
```

### X Only

```javascript
// Horizontal drag only
Draggable.create('.box', {
  type: 'x',
  bounds: '.container'
})
```

### Y Only

```javascript
// Vertical drag only
Draggable.create('.box', {
  type: 'y',
  bounds: '.container'
})
```

### Left/Top Drag

```javascript
// Use left/top instead of transform
Draggable.create('.box', {
  type: 'left,top',
  bounds: '.container'
})
```

## Bounds

### Container Bounds

```javascript
Draggable.create('.box', {
  type: 'x,y',
  bounds: '.container'  // Constrain to container
})
```

### Rectangle Bounds

```javascript
Draggable.create('.box', {
  type: 'x,y',
  bounds: {
    minX: 0,
    maxX: 500,
    minY: 0,
    maxY: 300
  }
})
```

### Partial Bounds

```javascript
// Only constrain X
Draggable.create('.box', {
  type: 'x,y',
  bounds: {
    minX: 100,
    maxX: 400
  }
})
```

### Relative Bounds

```javascript
// Relative to element's current position
Draggable.create('.box', {
  type: 'x,y',
  bounds: {
    minX: '-=100',  // 100px left of start
    maxX: '+=100',  // 100px right of start
    minY: '-=50',
    maxY: '+=50'
  }
})
```

### Rotation Bounds

```javascript
Draggable.create('.knob', {
  type: 'rotation',
  bounds: {
    minRotation: -135,
    maxRotation: 135
  }
})
```

## Inertia (Throw)

### Basic Inertia

```javascript
gsap.registerPlugin(Draggable, InertiaPlugin)

Draggable.create('.box', {
  type: 'x,y',
  inertia: true  // Enable throw
})
```

### Inertia Resistance

```javascript
Draggable.create('.box', {
  type: 'x,y',
  inertia: {
    resistance: 2000  // Higher = stops faster
  }
})
```

### Inertia Duration

```javascript
Draggable.create('.box', {
  type: 'x,y',
  inertia: {
    minDuration: 0.5,
    maxDuration: 2
  }
})
```

### Inertia Edge Resistance

```javascript
Draggable.create('.box', {
  type: 'x',
  inertia: {
    edgeResistance: 0.65  // Resistance at bounds (0-1)
  }
})
```

### Auto-scroll on Throw

```javascript
Draggable.create('.box', {
  type: 'x,y',
  inertia: true,
  edgeResistance: 0.8,
  bounds: '#container',
  autoScroll: 1  // Scroll container when hitting edge
})
```

## Rotation

### Basic Rotation

```javascript
Draggable.create('.dial', {
  type: 'rotation',
  bounds: {
    minRotation: 0,
    maxRotation: 360
  }
})
```

### Circular Rotation

```javascript
// Set transform origin for circular rotation
gsap.set('.dial', { transformOrigin: 'center center' })

Draggable.create('.dial', {
  type: 'rotation'
})
```

### Rotation with Snap

```javascript
Draggable.create('.dial', {
  type: 'rotation',
  liveSnap: {
    rotation: [0, 45, 90, 135, 180, 225, 270, 315, 360]
  },
  inertia: true
})
```

### Rotation Stages

```javascript
Draggable.create('.knob', {
  type: 'rotation',
  onDrag: function() {
    // Snap to stages
    const rotation = this.rotation
    const stage = Math.round(rotation / 45) * 45
    this.rotation = stage
  }
})
```

## Live Snap

### Snap to Grid

```javascript
Draggable.create('.box', {
  type: 'x,y',
  liveSnap: {
    x: 20,  // Snap every 20px
    y: 20
  }
})
```

### Snap to Values

```javascript
Draggable.create('.box', {
  type: 'x',
  liveSnap: {
    x: [0, 100, 200, 300, 400]
  }
})
```

### Snap to Function

```javascript
Draggable.create('.box', {
  type: 'x',
  liveSnap: {
    x: value => {
      // Snap to nearest multiple of 50
      return Math.round(value / 50) * 50
    }
  }
})
```

### Snap with Radius

```javascript
Draggable.create('.box', {
  type: 'x,y',
  liveSnap: {
    x: {
      points: [0, 100, 200],
      radius: 10  // Within 10px of point
    }
  }
})
```

## Callbacks

### Basic Callbacks

```javascript
Draggable.create('.box', {
  type: 'x,y',

  // Lifecycle callbacks
  onDragStart: function() {
    console.log('Drag started')
  },

  onDrag: function() {
    console.log('Dragging...', this.x, this.y)
  },

  onDragEnd: function() {
    console.log('Drag ended')
  },

  onPress: function() {
    console.log('Pressed')
  },

  onRelease: function() {
    console.log('Released')
  },

  onClick: function() {
    console.log('Clicked')
  }
})
```

### Access Data

```javascript
Draggable.create('.box', {
  type: 'x,y',

  onDrag: function() {
    // Access drag data
    console.log(this.x)          // Current X position
    console.log(this.y)          // Current Y position
    console.log(this.deltaX)      // Change since start
    console.log(this.deltaY)      // Change since start
    console.log(this.startX)      // Starting X position
    console.log(this.startY)      // Starting Y position
    console.log(this.pointerX)    // Pointer X position
    console.log(this.pointerY)    // Pointer Y position
  }
})
```

### Get Velocity

```javascript
Draggable.create('.box', {
  type: 'x,y',
  inertia: true,

  onDragEnd: function() {
    const velocity = InertiaPlugin.getVelocity(this.target, 'x')
    console.log('Throw velocity:', velocity)
  }
})
```

### Throw Callbacks

```javascript
Draggable.create('.box', {
  type: 'x,y',
  inertia: true,

  onThrowUpdate: function() {
    console.log('Throwing...')
  },

  onThrowComplete: function() {
    console.log('Throw complete')
  }
})
```

## Multiple Draggables

### Array of Targets

```javascript
// Create multiple draggable elements
Draggable.create(['.box1', '.box2', '.box3'], {
  type: 'x,y',
  bounds: '.container'
})
```

### NodeList

```javascript
// Create from NodeList
const boxes = document.querySelectorAll('.box')
Draggable.create(boxes, {
  type: 'x,y',
  bounds: '.container'
})
```

### Individual Control

```javascript
const draggables = Draggable.create('.box', {
  type: 'x,y',
  bounds: '.container'
})

// Access individual instance
dragga
bles[0].disable()
dragga
bles[1].enable()
```

## Click Handling

### Minimum Movement

```javascript
Draggable.create('.box', {
  type: 'x,y',
  minimumMovement: 5,  // Minimum pixels to register drag
  onClick: function() {
    console.log('Clicked without drag')
  }
})
```

### Clickable Elements

```javascript
Draggable.create('.container', {
  type: 'x,y',
  dragClickables: false,  // Don't drag clickable elements
  bounds: '.container'
})
```

### Drag vs Click

```javascript
let isDragging = false

Draggable.create('.box', {
  type: 'x,y',

  onDragStart: function() {
    isDragging = true
  },

  onDragEnd: function() {
    isDragging = false
  },

  onClick: function() {
    if (!isDragging) {
      console.log('Pure click, no drag')
    }
  }
})
```

## Advanced Patterns

### Slider

```javascript
Draggable.create('.handle', {
  type: 'x',
  bounds: {
    minX: 0,
    maxX: trackWidth - handleWidth
  },
  onDrag: function() {
    const progress = this.x / (trackWidth - handleWidth)
    gsap.to('.content', { x: -progress * contentWidth })
  }
})
```

### Sortable List

```javascript
const items = document.querySelectorAll('.list-item')

Draggable.create(items, {
  type: 'y',
  bounds: '.list',

  onDragEnd: function() {
    // Get all items sorted by Y position
    const sortedItems = Array.from(items)
      .sort((a, b) => gsap.getProperty(a, 'y') - gsap.getProperty(b, 'y'))

    // Reorder DOM
    const list = document.querySelector('.list')
    sortedItems.forEach(item => list.appendChild(item))
  }
})
```

### Puzzle Piece

```javascript
Draggable.create('.puzzle-piece', {
  type: 'x,y',
  bounds: '.board',
  inertia: true,

  onPress: function() {
    gsap.to(this.target, { scale: 1.1, duration: 0.2 })
  },

  onRelease: function() {
    gsap.to(this.target, { scale: 1, duration: 0.2 })

    // Check if near correct position
    const correctX = 100
    const correctY = 50
    const dist = Math.sqrt(Math.pow(this.x - correctX, 2) + Math.pow(this.y - correctY, 2))

    if (dist < 30) {
      // Snap to correct position
      gsap.to(this.target, {
        x: correctX,
        y: correctY,
        duration: 0.3,
        ease: 'elastic.out(1, 0.5)'
      })
    }
  }
})
```

### Swiper

```javascript
const swiper = Draggable.create('.swiper', {
  type: 'x',
  bounds: {
    minX: -(slideWidth * (totalSlides - 1)),
    maxX: 0
  },
  inertia: true,
  edgeResistance: 0.8,

  onDragEnd: function() {
    const snapIndex = Math.round(this.x / -slideWidth)
    const snapX = snapIndex * -slideWidth

    gsap.to(this.target, {
      x: snapX,
      duration: 0.5,
      ease: 'power2.out'
    })
  }
})
```

## Performance Tips

### Use Transform Instead of Left/Top

```javascript
// ❌ Slower, causes layout thrashing
Draggable.create('.box', {
  type: 'left,top'
})

// ✅ Faster, GPU-accelerated
Draggable.create('.box', {
  type: 'x,y'
})
```

### Throttle Events

```javascript
Draggable.create('.box', {
  type: 'x,y',

  onDrag: gsap.utils.throttle(function() {
    console.log('Dragging...')
  }, 100)
})
```

### Batch Updates

```javascript
let pendingUpdate = false

Draggable.create('.box', {
  type: 'x,y',

  onDrag: function() {
    if (!pendingUpdate) {
      pendingUpdate = true
      requestAnimationFrame(() => {
        // Batch update
        console.log('Batched update')
        pendingUpdate = false
      })
    }
  }
})
```

## Common Mistakes

### 1. Forgetting to Register InertiaPlugin

```javascript
// ❌ Inertia won't work
gsap.registerPlugin(Draggable)
Draggable.create('.box', { inertia: true })

// ✅ Register both plugins
gsap.registerPlugin(Draggable, InertiaPlugin)
Draggable.create('.box', { inertia: true })
```

### 2. Wrong Transform Origin for Rotation

```javascript
// ❌ Rotates from wrong point
Draggable.create('.dial', { type: 'rotation' })

// ✅ Set transform origin
gsap.set('.dial', { transformOrigin: 'center center' })
Draggable.create('.dial', { type: 'rotation' })
```

### 3. Bounds Not Working

```javascript
// ❌ Container doesn't have position set
<div class="container">
  <div class="box"></div>
</div>
Draggable.create('.box', { bounds: '.container' })

// ✅ Set position on container
.container { position: relative; }
.box { position: absolute; }
```

## Best Practices

1. **Use x,y over left,top** - Better performance
2. **Set position on bounds container** - Required for bounds to work
3. **Use inertia wisely** - Great for natural feel, but adds complexity
4. **Implement liveSnap** - Better UX for constrained movements
5. **Handle click vs drag** - Distinguish between user actions
6. **Use transformOrigin** - Critical for rotation
7. **Test on mobile** - Touch events can behave differently
8. **Clean up instances** - Disable/kill when no longer needed

## Quick Reference

| Feature | Method |
|---------|--------|
| Basic drag | `Draggable.create(target, { type: 'x,y' })` |
| Bounds | `bounds: '.container'` |
| Inertia | `inertia: true` (needs InertiaPlugin) |
| Rotation | `type: 'rotation'` |
| Live snap | `liveSnap: { x: 20 }` |
| Callbacks | `onDrag`, `onDragEnd`, `onClick` |
| Get velocity | `InertiaPlugin.getVelocity(target, 'x')` |
| Minimum movement | `minimumMovement: 5` |
| Edge resistance | `edgeResistance: 0.8` |
| Auto scroll | `autoScroll: 1` |
