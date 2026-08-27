# GSAP Flip Plugin

FLIP (First, Last, Invert, Play) technique for seamless layout animations.

## Setup

```javascript
import gsap from 'gsap'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(Flip)
```

## Basic Workflow

```javascript
// 1. Get the FIRST state
const state = Flip.getState('.box')

// 2. Make DOM/CSS changes (LAST state happens automatically)
container.appendChild(box)
box.classList.toggle('expanded')

// 3. Animate from first to last
Flip.from(state, { duration: 1 })
```

## Flip.getState()

Capture current state of elements:

```javascript
// Basic
const state = Flip.getState('.box')

// Multiple selectors
const state = Flip.getState('.box, .card, .item')

// With additional properties
const state = Flip.getState('.box', {
  props: 'backgroundColor, borderRadius',  // capture CSS props
  simple: true  // skip rotation/skew calculations
})
```

## Flip.from()

Animate from captured state to current state:

```javascript
Flip.from(state, {
  duration: 1,
  ease: 'power2.inOut',
  stagger: 0.1,
  absolute: true,      // use position: absolute during animation
  scale: true,         // animate scale changes
  nested: true,        // handle nested Flip elements
  onComplete: () => {},
  onEnter: elements => gsap.from(elements, { opacity: 0 }),
  onLeave: elements => gsap.to(elements, { opacity: 0 })
})
```

## Common Options

```javascript
Flip.from(state, {
  // Timing
  duration: 1,
  ease: 'power2.inOut',
  delay: 0,
  stagger: 0.05,

  // Behavior
  absolute: true,       // position: absolute during flip
  scale: true,          // animate width/height as scale
  nested: true,         // handle nested flip elements

  // Enter/Leave (for elements added/removed)
  onEnter: elements => {
    return gsap.from(elements, { opacity: 0, scale: 0 })
  },
  onLeave: elements => {
    return gsap.to(elements, { opacity: 0, scale: 0 })
  },

  // Targets (subset of state)
  targets: '.active',   // only flip these

  // Spin (rotation handling)
  spin: true,           // allow rotation animation

  // Callbacks
  onStart: () => {},
  onComplete: () => {},

  // Props to animate
  props: 'backgroundColor',  // CSS props beyond transforms
  propsFrom: { backgroundColor: 'red' }  // starting values for props
})
```

## Handling Enter/Leave

When elements are added or removed:

```javascript
// Initial state
const state = Flip.getState('.item')

// Add new items
container.innerHTML += '<div class="item new">New</div>'

// Remove items
document.querySelector('.item.remove').remove()

// Flip with enter/leave handlers
Flip.from(state, {
  duration: 0.5,
  onEnter: elements => {
    // New elements animate in
    return gsap.from(elements, {
      opacity: 0,
      scale: 0,
      duration: 0.5
    })
  },
  onLeave: elements => {
    // Removed elements animate out
    return gsap.to(elements, {
      opacity: 0,
      scale: 0,
      duration: 0.3
    })
  }
})
```

## Flip.to()

Alternative: animate TO a new state:

```javascript
// Get current state
const state = Flip.getState('.box')

// Animate TO new values (without making DOM changes)
Flip.to(state, {
  targets: '.box',
  scale: 1.5,
  x: 100,
  duration: 1
})
```

## Flip.fit()

Fit one element to another's size/position:

```javascript
// Fit box to target
Flip.fit('.box', '.target')

// With options
Flip.fit('.box', '.target', {
  scale: true,    // use scale instead of width/height
  duration: 1,    // animate the fit
  ease: 'power2'
})
```

## Flip.getByTarget()

Get Flip instance for an element:

```javascript
const flip = Flip.getByTarget('.box')
if (flip) {
  flip.kill()
}
```

## Flip.isFlipping()

Check if element is currently flipping:

```javascript
if (Flip.isFlipping('.box')) {
  // Animation in progress
}
```

## Common Patterns

### Toggle Layout

```javascript
button.addEventListener('click', () => {
  const state = Flip.getState('.items')
  container.classList.toggle('grid')
  Flip.from(state, { duration: 0.5, ease: 'power2.inOut' })
})
```

### Reorder List

```javascript
function moveToTop(item) {
  const state = Flip.getState('.list-item')
  list.prepend(item)
  Flip.from(state, { duration: 0.3, ease: 'power1.inOut' })
}
```

### Filter Gallery

```javascript
function filterItems(category) {
  const state = Flip.getState('.item')

  // Show/hide based on category
  items.forEach(item => {
    item.classList.toggle('hidden', !item.matches(category))
  })

  Flip.from(state, {
    duration: 0.5,
    scale: true,
    absolute: true,
    onEnter: elements => gsap.from(elements, { opacity: 0, scale: 0.8 }),
    onLeave: elements => gsap.to(elements, { opacity: 0, scale: 0.8 })
  })
}
```

### Card Expansion

```javascript
card.addEventListener('click', () => {
  const state = Flip.getState(card)

  // Move card to modal container
  modal.appendChild(card)
  card.classList.add('expanded')

  Flip.from(state, {
    duration: 0.5,
    ease: 'power2.inOut',
    absolute: true,
    onComplete: () => {
      // Enable modal interactions
    }
  })
})
```

### Shared Element Transition

```javascript
// Page A: capture state before navigation
const state = Flip.getState('.hero-image')
sessionStorage.setItem('flipState', JSON.stringify(state))

// Page B: restore and animate
const savedState = JSON.parse(sessionStorage.getItem('flipState'))
if (savedState) {
  Flip.from(savedState, {
    duration: 0.6,
    targets: '.hero-image'
  })
}
```

## React Integration

```javascript
import { useLayoutEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(Flip)

function FlipList({ items }) {
  const containerRef = useRef()

  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      const state = Flip.getState('.item')
      // Layout changes happen via React re-render
      Flip.from(state, { duration: 0.5 })
    }, containerRef)

    return () => ctx.revert()
  }, [items])

  return (
    <div ref={containerRef}>
      {items.map(item => (
        <div key={item.id} className="item">{item.name}</div>
      ))}
    </div>
  )
}
```

## Performance Tips

```javascript
// Use simple: true for many elements
Flip.getState('.item', { simple: true })

// Limit props captured
Flip.getState('.item', { props: '' })  // no extra props

// Use absolute for overlapping elements
Flip.from(state, { absolute: true })

// Kill previous flips before starting new
Flip.killFlipsOf('.item')
```
