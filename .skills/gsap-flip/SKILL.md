---
name: gsap-flip
description: Use when implementing layout animations, FLIP transitions, position/scale/rotation animations between states, reordering effects, or using Flip plugin.
---

# GSAP Flip - Layout Animations

Flip (First, Last, Invert, Play) creates smooth transitions between DOM states. Perfect for layout changes, reordering, size transitions, and responsive animations without jumps.

## Installation

```bash
npm install gsap
```

```javascript
import { Flip } from 'gsap/Flip'
gsap.registerPlugin(Flip)
```

## Basic FLIP Pattern

### Simple Flip

```javascript
gsap.registerPlugin(Flip)

// 1. Capture initial state
const state = Flip.getState('.box')

// 2. Make DOM changes
document.querySelector('.box').classList.add('moved')

// 3. Animate from old to new position
Flip.from(state, {
  duration: 1,
  ease: 'power2.out'
})
```

### Class Toggle

```javascript
const box = document.querySelector('.box')
const state = Flip.getState(box)

box.classList.toggle('active')

Flip.from(state, {
  duration: 0.8,
  ease: 'power2.inOut'
})
```

### Position Change

```javascript
// Capture state
const state = Flip.getState('.item')

// Move element
const item = document.querySelector('.item')
item.style.transform = 'translateX(200px)'

// Animate transition
Flip.from(state, {
  duration: 1
})
```

## Absolute Positioning

### Basic Absolute

```javascript
const state = Flip.getState('.box')

document.querySelector('.box').classList.add('new-position')

Flip.from(state, {
  duration: 1,
  absolute: true  // Apply position: absolute during animation
})
```

### Absolute with Selector

```javascript
const state = Flip.getState('.target')

// Change layout
document.querySelector('.container').classList.add('rearranged')

Flip.from(state, {
  duration: 1,
  absolute: '.target'  // Apply absolute to specific elements
})
```

### Absolute on Leave

```javascript
const state = Flip.getState('.item')

// Remove from DOM
document.querySelector('.item').remove()

Flip.from(state, {
  duration: 0.8,
  absoluteOnLeave: true  // Keep visible during exit animation
})
```

## Fade Effects

### Cross Fade

```javascript
// Add matching IDs to swapped elements
const items = document.querySelectorAll('.item')
items.forEach((item, i) => {
  item.setAttribute('data-flip-id', `item-${i}`)
})

const state = Flip.getState('.item')

// Swap elements
const container = document.querySelector('.container')
container.insertBefore(container.children[2], container.children[0])

Flip.from(state, {
  duration: 1,
  fade: true,  // Enable cross-fade
  ease: 'power2.inOut'
})
```

### Fade Only

```javascript
const state = Flip.getState('.box')

document.querySelector('.box').classList.add('hidden')

Flip.from(state, {
  duration: 0.5,
  fade: true,
  absolute: true
})
```

## Scale vs Width/Height

### Scale Animation

```javascript
const state = Flip.getState('.box')

document.querySelector('.box').classList.add('larger')

Flip.from(state, {
  duration: 1,
  scale: true,  // Use scale instead of width/height
  ease: 'power2.out'
})
```

### Width/Height Animation

```javascript
const state = Flip.getState('.box')

document.querySelector('.box').classList.add('larger')

Flip.from(state, {
  duration: 1,
  // Default: animates width/height
  ease: 'power2.out'
})
```

## Reordering

### Grid Reorder

```javascript
const container = document.querySelector('.grid')
const state = Flip.getState('.item')

// Move first item to end
container.appendChild(container.firstElementChild)

Flip.from(state, {
  duration: 1,
  absolute: true,
  ease: 'power2.inOut'
})
```

### Shuffle Animation

```javascript
const container = document.querySelector('.list')
const state = Flip.getState('.item')

// Shuffle items
const items = Array.from(container.children)
for (let i = items.length - 1; i > 0; i--) {
  const j = Math.floor(Math.random() * (i + 1))
  container.appendChild(items[Math.random() > 0.5 ? j : i])
}

Flip.from(state, {
  duration: 0.8,
  absolute: true,
  stagger: 0.1,
  ease: 'power2.out'
})
```

### Drag and Drop Reorder

```javascript
let state = Flip.getState('.draggable')

// Drag handler
function onDragStart(element) {
  state = Flip.getState('.draggable')
}

function onDragEnd(element) {
  // Reorder DOM based on drag position
  const container = element.parentNode
  const afterElement = getDragAfterElement(container, element.clientY)
  if (afterElement == null) {
    container.appendChild(element)
  } else {
    container.insertBefore(element, afterElement)
  }

  Flip.from(state, {
    duration: 0.5,
    absolute: true,
    ease: 'power2.out'
  })
}
```

## Responsive Layout

### Breakpoint Animation

```javascript
const mm = gsap.matchMedia()

mm.add('(min-width: 768px)', () => {
  const state = Flip.getState('.layout')
  document.querySelector('.layout').classList.add('desktop')
  Flip.from(state, { duration: 0.8 })
  return () => {
    const state = Flip.getState('.layout')
    document.querySelector('.layout').classList.remove('desktop')
    Flip.from(state, { duration: 0.8 })
  }
})
```

### Column Change

```javascript
const container = document.querySelector('.grid')
let state

function changeColumns(cols) {
  state = Flip.getState('.item')
  container.style.gridTemplateColumns = `repeat(${cols}, 1fr)`
  Flip.from(state, {
    duration: 1,
    absolute: true,
    ease: 'power2.out'
  })
}

// Change from 3 to 2 columns
changeColumns(2)
```

## Complex Transitions

### Accordion

```javascript
function toggleAccordion(header) {
  const content = header.nextElementSibling
  const isOpen = content.classList.contains('open')

  const state = Flip.getState('.accordion-content')

  document.querySelectorAll('.accordion-content').forEach(c => {
    c.classList.remove('open')
    c.style.height = '0'
  })

  if (!isOpen) {
    content.classList.add('open')
    content.style.height = content.scrollHeight + 'px'
  }

  Flip.from(state, {
    duration: 0.5,
    ease: 'power2.inOut'
  })
}
```

### Tab Switch

```javascript
function switchTab(tabId) {
  const state = Flip.getState('.tab-content')

  // Hide all tabs
  document.querySelectorAll('.tab-content').forEach(tab => {
    tab.classList.remove('active')
    tab.style.display = 'none'
  })

  // Show selected tab
  const activeTab = document.querySelector(tabId)
  activeTab.classList.add('active')
  activeTab.style.display = 'block'

  Flip.from(state, {
    duration: 0.6,
    fade: true,
    ease: 'power2.out'
  })
}
```

### Modal Animation

```javascript
function openModal(modal) {
  const state = Flip.getState('.modal-content')

  modal.classList.add('open')

  Flip.from(state, {
    duration: 0.5,
    scale: true,
    ease: 'back.out(1.7)'
  })
}

function closeModal(modal) {
  const state = Flip.getState('.modal-content')

  modal.classList.remove('open')

  Flip.from(state, {
    duration: 0.3,
    scale: true,
    ease: 'power2.in',
    onComplete: () => {
      modal.style.display = 'none'
    }
  })
}
```

## Enter/Leave Animations

### onEnter/onLeave

```javascript
const state = Flip.getState('.item')

// Add new item
const newItem = document.createElement('div')
newItem.className = 'item'
document.querySelector('.container').appendChild(newItem)

Flip.from(state, {
  duration: 0.6,
  absolute: true,
  onEnter: elements => gsap.from(elements, {
    opacity: 0,
    scale: 0.8,
    duration: 0.5
  }),
  onLeave: elements => gsap.to(elements, {
    opacity: 0,
    scale: 0.8,
    duration: 0.5
  })
})
```

### Enter Only

```javascript
const state = Flip.getState('.list')

// Add items dynamically
const newItem = document.createElement('div')
newItem.textContent = 'New Item'
document.querySelector('.list').appendChild(newItem)

Flip.from(state, {
  duration: 0.5,
  absolute: true,
  onEnter: elements => {
    gsap.from(elements[elements.length - 1], {
      opacity: 0,
      y: -20,
      duration: 0.4
    })
  }
})
```

## Nested Elements

### Parent + Child Flip

```javascript
// Capture both parent and child
const parentState = Flip.getState('.parent')
const childState = Flip.getState('.child')

// Make changes
document.querySelector('.parent').classList.add('moved')
document.querySelector('.child').classList.add('scaled')

// Animate both
Flip.from([parentState, childState], {
  duration: 1,
  ease: 'power2.out'
})
```

### Container Flip

```javascript
const state = Flip.getState('.container')

// Animate container and children
Flip.from(state, {
  targets: '.container, .item',
  duration: 0.8,
  stagger: 0.1,
  ease: 'power2.out'
})
```

## ScrollTrigger Integration

### Scroll-driven Layout

```javascript
gsap.registerPlugin(ScrollTrigger, Flip)

gsap.to('.container', {
  scrollTrigger: {
    trigger: '.container',
    start: 'top 80%',
    end: 'bottom 20%',
    scrub: true,
    onUpdate: self => {
      const state = Flip.getState('.item')
      // Apply layout changes based on scroll progress
      const scale = 1 + self.progress * 0.5
      document.querySelector('.item').style.transform = `scale(${scale})`
      Flip.from(state, { duration: 0.1, scale: true })
    }
  }
})
```

### Pin + Flip

```javascript
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: '.section',
    start: 'top top',
    end: '+=500',
    pin: true,
    scrub: true
  }
})

tl.add(() => {
  const state = Flip.getState('.item')
  document.querySelector('.item').classList.add('moved')
  Flip.from(state, { duration: 0.5 })
}, 0)
```

## Performance Tips

### Use Absolute Wisely

```javascript
// ❌ Always using absolute
Flip.from(state, { absolute: true })

// ✅ Use only when needed
Flip.from(state, {
  absolute: '.moving-items',  // Only specific items
  duration: 1
})
```

### Batch DOM Changes

```javascript
// ❌ Multiple Flip animations
const state1 = Flip.getState('.item1')
document.querySelector('.item1').classList.add('moved')
Flip.from(state1, { duration: 0.5 })

const state2 = Flip.getState('.item2')
document.querySelector('.item2').classList.add('moved')
Flip.from(state2, { duration: 0.5 })

// ✅ Batch changes
const state = Flip.getState('.item')
document.querySelector('.item1').classList.add('moved')
document.querySelector('.item2').classList.add('moved')
Flip.from(state, { duration: 0.5, stagger: 0.1 })
```

## Common Mistakes

### 1. Forgetting Absolute in Flex/Grid

```javascript
// ❌ Elements jump during animation
const state = Flip.getState('.item')
document.querySelector('.flex-container').classList.add('rearranged')
Flip.from(state, { duration: 1 })

// ✅ Use absolute for flex/grid
Flip.from(state, {
  duration: 1,
  absolute: true
})
```

### 2. Not Capturing State First

```javascript
// ❌ Changing DOM before capturing state
document.querySelector('.item').classList.add('moved')
const state = Flip.getState('.item')
Flip.from(state, { duration: 1 })

// ✅ Capture state first
const state = Flip.getState('.item')
document.querySelector('.item').classList.add('moved')
Flip.from(state, { duration: 1 })
```

### 3. Missing data-flip-id

```javascript
// ❌ Cross-fade not working
Flip.from(state, { fade: true })

// ✅ Add matching IDs
document.querySelectorAll('.swappable').forEach((item, i) => {
  item.setAttribute('data-flip-id', `swap-${i}`)
})
Flip.from(state, { fade: true })
```

## Best Practices

1. **Capture state before changes** - Always capture, then modify DOM
2. **Use absolute in flex/grid** - Prevents layout shifts during animation
3. **Add data-flip-id for fades** - Enable cross-fade for swapped elements
4. **Batch DOM changes** - One Flip animation for multiple changes
5. **Consider scale vs dimensions** - Scale is more performant for size changes
6. **Use onEnter/onLeave** - Animate elements entering/leaving DOM
7. **Combine with ScrollTrigger** - Create scroll-driven layout effects
8. **Test on mobile** - Layout animations can behave differently

## Quick Reference

| Feature | Method |
|---------|--------|
| Get state | `Flip.getState(targets)` |
| Animate flip | `Flip.from(state, { duration })` |
| Absolute positioning | `absolute: true` |
| Cross-fade | `fade: true` |
| Scale animation | `scale: true` |
| Enter animation | `onEnter: elements => ...` |
| Leave animation | `onLeave: elements => ...` |
| Absolute on leave | `absoluteOnLeave: true` |
