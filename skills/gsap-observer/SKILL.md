---
name: gsap-observer
description: Use when implementing gesture detection, scroll/wheel/touch event handling, swipe detection, directional interactions, or using Observer plugin.
---

# GSAP Observer

Observer provides unified gesture detection across devices - wheel, touch, pointer, and scroll events. Perfect for sliders, swipers, scroll hijacking, and cross-device interactions.

## Installation

```bash
npm install gsap
```

```javascript
import { Observer } from 'gsap/Observer'
gsap.registerPlugin(Observer)
```

## Basic Observer

### Create Observer

```javascript
gsap.registerPlugin(Observer)

Observer.create({
  target: window,
  type: 'wheel,touch,pointer',

  onUp: () => console.log('Up'),
  onDown: () => console.log('Down'),
  onLeft: () => console.log('Left'),
  onRight: () => console.log('Right')
})
```

### Scroll Detection

```javascript
Observer.create({
  target: window,
  type: 'scroll',

  onUp: () => prevSlide(),
  onDown: () => nextSlide()
})
```

### Wheel Detection

```javascript
Observer.create({
  target: window,
  type: 'wheel',

  onWheel: (self) => {
    console.log('Wheel delta:', self.deltaY)
  }
})
```

## Event Types

### Type Combinations

```javascript
// Wheel and touch
Observer.create({
  type: 'wheel,touch',
  onDown: () => nextSlide()
})

// All types (default)
Observer.create({
  type: 'wheel,touch,pointer,scroll',
  onDown: () => nextSlide()
})

// Only pointer
Observer.create({
  type: 'pointer',
  onDrag: () => console.log('Dragging')
})
```

### Event Types Explained

- **wheel** - Mouse wheel, trackpad
- **touch** - Touch swipes (any device)
- **pointer** - Pointer/mouse drag when pressed
- **scroll** - Scrollbar dragging

## Callbacks

### Direction Callbacks

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',

  onUp: (self) => {
    console.log('Moving up', self.deltaY, self.velocityY)
  },

  onDown: (self) => {
    console.log('Moving down', self.deltaY, self.velocityY)
  },

  onLeft: (self) => {
    console.log('Moving left', self.deltaX, self.velocityX)
  },

  onRight: (self) => {
    console.log('Moving right', self.deltaX, self.velocityX)
  }
})
```

### Drag Callbacks

```javascript
Observer.create({
  target: window,
  type: 'pointer',

  onPress: (self) => {
    console.log('Pressed')
  },

  onDrag: (self) => {
    console.log('Dragging...', self.deltaX, self.deltaY)
  },

  onDragStart: (self) => {
    console.log('Drag started')
  },

  onDragEnd: (self) => {
    console.log('Drag ended')
  }
})
```

### Hover Callbacks

```javascript
Observer.create({
  target: '.element',
  type: 'pointer',

  onHover: (self) => {
    console.log('Hovering')
  },

  onHoverEnd: (self) => {
    console.log('Hover ended')
  }
})
```

### Change Callback

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',

  onChange: (self) => {
    console.log('Direction changed')
  }
})
```

## Configuration Options

### Tolerance

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',
  tolerance: 10,  // Minimum movement before triggering

  onUp: () => nextSlide(),
  onDown: () => prevSlide()
})
```

### Drag Minimum

```javascript
Observer.create({
  target: window,
  type: 'pointer',
  dragMinimum: 10,  // Minimum pixels for drag

  onDrag: (self) => {
    console.log('Dragging')
  }
})
```

### Wheel Speed

```javascript
Observer.create({
  target: window,
  type: 'wheel',
  wheelSpeed: 1.5,  // Multiplier for wheel events

  onWheel: (self) => {
    console.log('Wheel:', self.deltaY)
  }
})
```

### Prevent Default

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',
  preventDefault: true,  // Prevent default browser behavior

  onWheel: (self) => {
    console.log('Wheel handled')
  }
})
```

### Ignore Elements

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',

  // Ignore elements with this selector
  ignore: '.no-scroll, .modal',

  onWheel: (self) => {
    console.log('Wheel on scrollable area')
  }
})
```

### Debounce

```javascript
Observer.create({
  target: window,
  type: 'wheel',
  debounce: 100,  // Debounce events by 100ms

  onWheel: (self) => {
    console.log('Debounced wheel')
  }
})
```

## Accessing Data

### Delta and Velocity

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',

  onDown: (self) => {
    console.log('Delta Y:', self.deltaY)
    console.log('Delta X:', self.deltaX)
    console.log('Velocity Y:', self.velocityY)
    console.log('Velocity X:', self.velocityX)
    console.log('Wheel delta:', self.wheelDelta)
  }
})
```

### Event Details

```javascript
Observer.create({
  target: window,
  type: 'pointer',

  onPress: (self) => {
    console.log('Start X:', self.startX)
    console.log('Start Y:', self.startY)
  },

  onDrag: (self) => {
    console.log('Current X:', self.x)
    console.log('Current Y:', self.y)
    console.log('Event:', self.event)
  }
})
```

### Check Active State

```javascript
Observer.create({
  target: window,
  type: 'pointer',

  onDrag: (self) => {
    if (self.isDragging) {
      console.log('Currently dragging')
    }
  }
})
```

## Patterns

### Simple Slider

```javascript
let currentSlide = 0
const slides = document.querySelectorAll('.slide')
const totalSlides = slides.length

const observer = Observer.create({
  target: window,
  type: 'wheel,touch',
  tolerance: 50,

  onUp: () => {
    currentSlide = (currentSlide - 1 + totalSlides) % totalSlides
    goToSlide(currentSlide)
  },

  onDown: () => {
    currentSlide = (currentSlide + 1) % totalSlides
    goToSlide(currentSlide)
  }
})

function goToSlide(index) {
  gsap.to('.slides-container', {
    x: -index * 100 + '%',
    duration: 0.6,
    ease: 'power2.out'
  })
}
```

### Swiper with Momentum

```javascript
let currentSlide = 0
const slides = document.querySelectorAll('.slide')
const totalSlides = slides.length

Observer.create({
  target: '.swiper',
  type: 'wheel,touch,pointer',
  dragMinimum: 50,

  onDragStart: (self) => {
    gsap.killTweensOf('.slides-container')
  },

  onDrag: (self) => {
    gsap.set('.slides-container', {
      x: currentSlide * -100 + self.deltaX + '%'
    })
  },

  onDragEnd: (self) => {
    if (self.deltaX < -50) {
      currentSlide = (currentSlide + 1) % totalSlides
    } else if (self.deltaX > 50) {
      currentSlide = (currentSlide - 1 + totalSlides) % totalSlides
    }

    gsap.to('.slides-container', {
      x: currentSlide * -100 + '%',
      duration: 0.6,
      ease: 'power2.out'
    })
  }
})
```

### Scroll Hijacking

```javascript
let currentSection = 0
const sections = document.querySelectorAll('.section')
const totalSections = sections.length
let isScrolling = false

Observer.create({
  target: window,
  type: 'scroll',
  tolerance: 50,

  onUp: () => {
    if (isScrolling) return
    isScrolling = true

    currentSection = Math.max(0, currentSection - 1)
    scrollToSection(currentSection)

    setTimeout(() => { isScrolling = false }, 1000)
  },

  onDown: () => {
    if (isScrolling) return
    isScrolling = true

    currentSection = Math.min(totalSections - 1, currentSection + 1)
    scrollToSection(currentSection)

    setTimeout(() => { isScrolling = false }, 1000)
  }
})

function scrollToSection(index) {
  gsap.to(window, {
    scrollTo: { y: index * window.innerHeight },
    duration: 1,
    ease: 'power2.inOut'
  })
}
```

### Interactive Map

```javascript
Observer.create({
  target: '.map-container',
  type: 'pointer',

  onDragStart: (self) => {
    gsap.set('.map-content', { clearProps: 'x,y' })
  },

  onDrag: (self) => {
    gsap.set('.map-content', {
      x: self.deltaX,
      y: self.deltaY
    })
  },

  onDragEnd: (self) => {
    // Add momentum
    gsap.to('.map-content', {
      x: self.x + self.velocityX * 20,
      y: self.y + self.velocityY * 20,
      duration: 0.5,
      ease: 'power2.out'
    })
  }
})
```

### Gallery Navigation

```javascript
const gallery = document.querySelector('.gallery')
const observer = Observer.create({
  target: gallery,
  type: 'wheel,touch',
  tolerance: 30,

  onUp: () => navigateGallery(-1),
  onDown: () => navigateGallery(1)
})

function navigateGallery(direction) {
  const current = gallery.querySelector('.active')
  const items = gallery.querySelectorAll('.gallery-item')
  const currentIndex = Array.from(items).indexOf(current)
  const nextIndex = (currentIndex + direction + items.length) % items.length

  items.forEach(item => item.classList.remove('active'))
  items[nextIndex].classList.add('active')

  gsap.to(gallery, {
    x: -nextIndex * 100 + '%',
    duration: 0.5,
    ease: 'power2.out'
  })
}
```

## Velocity-Based Actions

### Threshold Detection

```javascript
Observer.create({
  target: window,
  type: 'wheel,touch',

  onDragEnd: (self) => {
    if (self.velocityY < -2) {
      console.log('Fast swipe up')
    } else if (self.velocityY > 2) {
      console.log('Fast swipe down')
    }
  }
})
```

### Momentum Scrolling

```javascript
let momentum = { x: 0, y: 0 }

Observer.create({
  target: '.scroll-container',
  type: 'pointer',

  onDrag: (self) => {
    momentum.x = self.velocityX
    momentum.y = self.velocityY

    gsap.set('.content', {
      x: self.deltaX,
      y: self.deltaY
    })
  },

  onDragEnd: (self) => {
    // Continue with momentum
    gsap.to('.content', {
      x: self.x + momentum.x * 50,
      y: self.y + momentum.y * 50,
      duration: 1,
      ease: 'power2.out'
    })
  }
})
```

## Instance Methods

```javascript
const observer = Observer.create({
  target: window,
  type: 'wheel',

  onWheel: () => console.log('Wheel')
})

// Enable/disable
observer.enable()
observer.disable()

// Kill observer
observer.kill()

// Update configuration
observer.update({
  tolerance: 20
})
```

## Static Methods

```javascript
// Get all observers
const observers = Observer.getAll()

// Kill all observers
Observer.getAll().forEach(obs => obs.kill())

// Create global config
Observer.defaults = {
  type: 'wheel,touch',
  tolerance: 50
}
```

## Performance Tips

### Debounce Heavy Callbacks

```javascript
Observer.create({
  target: window,
  type: 'wheel',
  debounce: 100,  // Debounce by 100ms

  onWheel: gsap.utils.throttle(() => {
    // Heavy operation
    updateLayout()
  }, 100)
})
```

### Use Right Event Type

```javascript
// ❌ Using all types when only need one
Observer.create({
  type: 'wheel,touch,pointer,scroll',
  onWheel: () => console.log('Wheel')
})

// ✅ Use only needed type
Observer.create({
  type: 'wheel',
  onWheel: () => console.log('Wheel')
})
```

### Prevent Default Carefully

```javascript
// ❌ Always preventing default
Observer.create({
  preventDefault: true,
  onWheel: () => console.log('Wheel')
})

// ✅ Conditional prevent default
Observer.create({
  onWheel: (self) => {
    if (shouldPreventDefault(self)) {
      self.event.preventDefault()
    }
  }
})
```

## Common Mistakes

### 1. Not Ignoring Scrollable Areas

```javascript
// ❌ Observer blocks scrolling on all elements
Observer.create({
  preventDefault: true,
  onWheel: () => console.log('Wheel')
})

// ✅ Ignore scrollable elements
Observer.create({
  ignore: '.scrollable-content, textarea',
  onWheel: (self) => {
    self.event.preventDefault()
    console.log('Wheel')
  }
})
```

### 2. Wrong Target

```javascript
// ❌ Observer on wrong element
Observer.create({
  target: '.child',
  type: 'wheel',
  onWheel: () => console.log('Wheel')
})

// ✅ Observer on container/window
Observer.create({
  target: '.container',
  type: 'wheel',
  onWheel: () => console.log('Wheel')
})
```

### 3. Not Debouncing

```javascript
// ❌ Fires on every scroll tick
Observer.create({
  type: 'scroll',
  onUp: () => updateLayout()  // Expensive!
})

// ✅ Debounce expensive operations
Observer.create({
  type: 'scroll',
  debounce: 100,
  onUp: () => updateLayout()
})
```

## Best Practices

1. **Choose right event types** - Only use what you need
2. **Set appropriate tolerance** - Prevent accidental triggers
3. **Use ignore for scrollable areas** - Don't block necessary scrolling
4. **Debounce expensive callbacks** - Performance critical
5. **Leverage velocity** - Create momentum-based interactions
6. **Test on multiple devices** - Touch vs wheel behavior differs
7. **Clean up observers** - Kill when no longer needed
8. **Consider accessibility** - Provide alternatives for scroll hijacking

## Quick Reference

| Feature | Method |
|---------|--------|
| Create observer | `Observer.create({ target, type, onUp })` |
| Event types | `'wheel'`, `'touch'`, `'pointer'`, `'scroll'` |
| Direction callbacks | `onUp`, `onDown`, `onLeft`, `onRight` |
| Drag callbacks | `onDrag`, `onDragStart`, `onDragEnd` |
| Access velocity | `self.velocityY`, `self.velocityX` |
| Access delta | `self.deltaY`, `self.deltaX` |
| Tolerance | `tolerance: 50` |
| Prevent default | `preventDefault: true` |
| Ignore elements | `ignore: '.selector'` |
| Enable/disable | `observer.enable()`, `observer.disable()` |
