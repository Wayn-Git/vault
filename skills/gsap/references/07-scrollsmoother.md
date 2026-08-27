# GSAP ScrollSmoother

ScrollSmoother adds smooth scrolling while maintaining native scroll functionality.

**Note (2026-02):** ScrollSmoother is available in the public `gsap` npm package (GSAP 3.13+) under the GSAP Standard No-Charge License.

## Setup

### HTML Structure (Required)

```html
<body>
  <div id="smooth-wrapper">
    <div id="smooth-content">
      <!-- ALL YOUR CONTENT HERE -->
    </div>
  </div>
</body>
```

### JavaScript Setup

```javascript
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { ScrollSmoother } from 'gsap/ScrollSmoother'

gsap.registerPlugin(ScrollTrigger, ScrollSmoother)

// Create smoother
const smoother = ScrollSmoother.create({
  smooth: 1,        // smoothing duration (seconds)
  effects: true     // enable data-speed/data-lag attributes
})
```

## Configuration Options

```javascript
ScrollSmoother.create({
  // Core options
  smooth: 1,              // smoothing time (seconds)
  smoothTouch: false,     // enable for touch devices (0.1 recommended)

  // Effects
  effects: true,          // enable data-speed/data-lag

  // Advanced
  ease: 'expo',           // easing function
  normalizeScroll: true,  // fixes mobile address bar issues
  ignoreMobileResize: true,

  // Speed multiplier
  speed: 1,               // overall scroll speed (1 = normal)

  // Container selectors (if not using default IDs)
  wrapper: '#smooth-wrapper',
  content: '#smooth-content'
})
```

## Speed Effects (Parallax)

Use `data-speed` attribute for parallax:

```html
<!-- Slower than scroll (background parallax) -->
<div data-speed="0.5">Moves at half speed</div>

<!-- Faster than scroll (foreground parallax) -->
<div data-speed="1.5">Moves 1.5x faster</div>

<!-- Double speed -->
<div data-speed="2">Moves twice as fast</div>

<!-- Auto-calculated (centers element in viewport) -->
<div data-speed="auto">Auto-centered parallax</div>

<!-- Clamped (prevents going past natural bounds) -->
<div data-speed="clamp(0.5)">Clamped parallax</div>
```

## Lag Effects

Use `data-lag` for delayed movement:

```html
<!-- Element lags behind scroll -->
<div data-lag="0.5">0.5s lag</div>
<div data-lag="0.8">0.8s lag</div>
<div data-lag="1">1s lag</div>

<!-- Combine with speed -->
<div data-speed="0.8" data-lag="0.3">Speed + lag</div>
```

## JavaScript Effects API

Apply effects programmatically:

```javascript
const smoother = ScrollSmoother.create({ effects: true })

// Apply to elements
smoother.effects('.parallax-bg', { speed: 0.5 })
smoother.effects('.parallax-fg', { speed: 1.5, lag: 0.2 })

// With options
smoother.effects('.box', {
  speed: 0.8,
  lag: 0.1,
  effectsPadding: 100  // extend effect zone
})

// Get existing effects
const effects = smoother.effects()  // returns array
```

## Methods

### scrollTo()

```javascript
const smoother = ScrollSmoother.get()

// Scroll to position
smoother.scrollTo(500)

// Scroll to element
smoother.scrollTo('.section')
smoother.scrollTo(element)

// With options
smoother.scrollTo('.section', true)   // instant (no smooth)
smoother.scrollTo('.section', true, 'center center')  // position

// Offset
smoother.scrollTo('.section', false, 'top top', -100)  // offset by -100px
```

### scrollTop()

```javascript
// Get current scroll position
const pos = smoother.scrollTop()

// Set scroll position (instant)
smoother.scrollTop(500)
```

### paused()

```javascript
// Check if paused
const isPaused = smoother.paused()

// Pause scrolling
smoother.paused(true)

// Resume
smoother.paused(false)
```

### Other Methods

```javascript
// Get velocity
const velocity = smoother.getVelocity()

// Kill instance
smoother.kill()

// Get instance (singleton)
const smoother = ScrollSmoother.get()

// Refresh after content changes
smoother.refresh()
```

## Important Caveats

### Position Fixed Elements

```html
<!-- ❌ Fixed elements INSIDE wrapper won't work -->
<div id="smooth-wrapper">
  <div id="smooth-content">
    <header style="position: fixed;">Won't work!</header>
  </div>
</div>

<!-- ✅ Fixed elements OUTSIDE wrapper -->
<header style="position: fixed;">Works!</header>
<div id="smooth-wrapper">
  <div id="smooth-content">
    <!-- content -->
  </div>
</div>
```

### CSS Requirements

```css
/* Wrapper needs these styles */
#smooth-wrapper {
  overflow: hidden;
  position: fixed;
  height: 100%;
  width: 100%;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
}

/* Content will be transformed */
#smooth-content {
  overflow: visible;
  width: 100%;
}
```

## Integration with ScrollTrigger

```javascript
// ScrollSmoother and ScrollTrigger work together
ScrollSmoother.create({ smooth: 1, effects: true })

// ScrollTrigger animations work normally
gsap.to('.box', {
  x: 500,
  scrollTrigger: {
    trigger: '.box',
    start: 'top center',
    scrub: true
  }
})

// Pin works
gsap.to('.panel', {
  x: -500,
  scrollTrigger: {
    trigger: '.container',
    pin: true,
    scrub: true
  }
})
```

## Common Patterns

### Basic Smooth Scroll

```javascript
ScrollSmoother.create({
  smooth: 1.5,
  effects: true,
  smoothTouch: 0.1
})
```

### Parallax Hero

```html
<section class="hero">
  <div class="hero-bg" data-speed="0.5"></div>
  <h1 data-speed="0.8">Hero Title</h1>
  <p data-speed="0.9" data-lag="0.1">Subtitle</p>
</section>
```

### Staggered Lag

```html
<div class="cards">
  <div class="card" data-lag="0.1">Card 1</div>
  <div class="card" data-lag="0.2">Card 2</div>
  <div class="card" data-lag="0.3">Card 3</div>
</div>
```

### Scroll to Section

```javascript
const smoother = ScrollSmoother.create({ smooth: 1 })

document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', (e) => {
    e.preventDefault()
    const target = document.querySelector(link.getAttribute('href'))
    smoother.scrollTo(target, true, 'top top')
  })
})
```

### Disable on Mobile

```javascript
const mm = gsap.matchMedia()

mm.add('(min-width: 768px)', () => {
  return ScrollSmoother.create({
    smooth: 1,
    effects: true
  })
})
```

### With Normalize Scroll

```javascript
// Fixes issues with mobile browser address bars
ScrollSmoother.create({
  smooth: 1,
  normalizeScroll: true,
  ignoreMobileResize: true
})
```

## Performance Tips

```javascript
// Limit effect elements
ScrollSmoother.create({
  effects: '.parallax',  // only these elements, not all
  effectsPadding: 50     // reduce padding for better perf
})

// Use will-change in CSS for parallax elements
.parallax {
  will-change: transform;
}

// Reduce smooth value for lower-end devices
const smooth = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 1
ScrollSmoother.create({ smooth })
```
