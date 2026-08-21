# GSAP Core API

## Tween Methods

### gsap.to()

Animates from current values TO specified values.

```javascript
// Basic
gsap.to('.box', { x: 200, duration: 1 })

// Multiple properties
gsap.to('.box', {
  x: 200,
  y: 100,
  rotation: 360,
  opacity: 0.5,
  duration: 2,
  ease: 'power2.inOut'
})

// Multiple targets
gsap.to(['.box1', '.box2', element], { x: 100 })
```

### gsap.from()

Animates FROM specified values to current values.

```javascript
// Fade in from below
gsap.from('.box', {
  opacity: 0,
  y: 50,
  duration: 1
})

// ⚠️ Renders immediately by default
// Set immediateRender: false if needed
gsap.from('.box', {
  y: -100,
  immediateRender: false
})
```

### gsap.fromTo()

Animates FROM specified values TO specified values.

```javascript
gsap.fromTo('.box',
  { opacity: 0, y: 50 },      // from
  { opacity: 1, y: 0, duration: 1 }  // to
)
```

### gsap.set()

Sets properties instantly (zero-duration tween).

```javascript
gsap.set('.box', { x: 100, opacity: 0 })

// Useful for initial states
gsap.set('.modal', { autoAlpha: 0 })
```

## Special Properties

### Timing

```javascript
gsap.to('.box', {
  x: 100,
  duration: 1,      // seconds (default: 0.5)
  delay: 0.5,       // delay before start
  repeat: 3,        // repeat count (-1 = infinite)
  repeatDelay: 0.5, // delay between repeats
  yoyo: true        // reverse on repeat
})
```

### Callbacks

```javascript
gsap.to('.box', {
  x: 100,
  onStart: () => console.log('Started'),
  onUpdate: () => console.log('Updated'),
  onComplete: () => console.log('Complete'),
  onRepeat: () => console.log('Repeated'),
  onReverseComplete: () => console.log('Reversed')
})

// With parameters
gsap.to('.box', {
  x: 100,
  onComplete: (msg) => console.log(msg),
  onCompleteParams: ['Animation done!']
})
```

### Control Options

```javascript
gsap.to('.box', {
  x: 100,
  paused: true,           // start paused
  reversed: true,         // start reversed
  overwrite: 'auto',      // kill conflicting tweens
  id: 'myTween',          // for gsap.getById()
  immediateRender: false  // don't render on creation
})
```

### CSS Properties

```javascript
gsap.to('.box', {
  // Transforms (GPU-accelerated)
  x: 100,           // translateX
  y: 50,            // translateY
  z: 0,             // translateZ (triggers 3D)
  xPercent: 50,     // translateX as percentage
  yPercent: -50,    // translateY as percentage
  rotation: 360,    // rotate in degrees
  rotationX: 45,    // 3D rotation
  rotationY: 45,
  scale: 1.5,
  scaleX: 2,
  scaleY: 0.5,
  skewX: 20,
  skewY: 10,
  transformOrigin: 'center center',

  // Standard CSS
  opacity: 0.5,
  width: 200,
  height: '50%',
  backgroundColor: '#ff0000',
  borderRadius: '50%',

  // Auto values
  autoAlpha: 0,     // opacity + visibility: hidden

  // Force 3D rendering
  force3D: true
})
```

### Relative Values

```javascript
gsap.to('.box', {
  x: '+=100',       // add 100 to current
  y: '-=50',        // subtract 50 from current
  rotation: '+=360' // add 360 degrees
})
```

### Function-Based Values

```javascript
gsap.to('.box', {
  x: (index, target, targets) => {
    return index * 100  // different value per target
  },
  duration: (i) => 0.5 + i * 0.1
})

// Random values
gsap.to('.box', {
  x: 'random(-200, 200)',
  y: 'random(-100, 100)',
  rotation: 'random(-180, 180)'
})

// Random from array
gsap.to('.box', {
  x: 'random([0, 100, 200, 300])'
})
```

## Tween Control Methods

```javascript
const tween = gsap.to('.box', { x: 100, duration: 2 })

// Playback
tween.play()
tween.pause()
tween.resume()
tween.reverse()
tween.restart()

// Position
tween.seek(1)           // jump to 1 second
tween.progress(0.5)     // jump to 50%
tween.time(0.5)         // set current time

// Speed
tween.timeScale(2)      // double speed
tween.timeScale(0.5)    // half speed

// State
tween.kill()            // destroy
tween.invalidate()      // clear recorded values
tween.revert()          // revert to pre-animation state

// Read state
console.log(tween.progress())   // 0-1
console.log(tween.isActive())   // boolean
console.log(tween.duration())   // total duration
```

## Global Methods

```javascript
// Kill tweens
gsap.killTweensOf('.box')
gsap.killTweensOf('.box', 'x,y')  // only x and y

// Get tweens
const tween = gsap.getById('myTween')
const tweens = gsap.getTweensOf('.box')

// Global pause/resume
gsap.globalTimeline.pause()
gsap.globalTimeline.resume()

// Defaults
gsap.defaults({
  ease: 'power2.out',
  duration: 1
})

// Configuration
gsap.config({
  autoSleep: 60,
  force3D: 'auto',
  nullTargetWarn: false
})
```

## Delayed Calls

```javascript
// Call function after delay
gsap.delayedCall(2, myFunction)
gsap.delayedCall(2, myFunction, [arg1, arg2])

// Kill delayed calls
gsap.killTweensOf(myFunction)
```

## Quick Setters & Quick To

For performance-critical scenarios:

### gsap.quickSetter()

Creates an optimized setter function for rapid property updates.

```javascript
// Create optimized setter
const setX = gsap.quickSetter('.box', 'x', 'px')
const setRotation = gsap.quickSetter('.box', 'rotation')

// Use in animation loop
gsap.ticker.add(() => {
  setX(mouseX)
  setRotation(angle)
})
```

### gsap.quickTo()

Creates a function that animates to a value with built-in tweening. Best for cursor-following animations.

```javascript
// Create quickTo functions
const xTo = gsap.quickTo('.cursor', 'x', { duration: 0.4, ease: 'power3' })
const yTo = gsap.quickTo('.cursor', 'y', { duration: 0.4, ease: 'power3' })

// Call on mouse move - smooth interpolation
document.addEventListener('mousemove', (e) => {
  xTo(e.clientX)
  yTo(e.clientY)
})
```

**quickSetter vs quickTo:**
- `quickSetter`: Instant updates, no tweening (for RAF loops)
- `quickTo`: Smooth tweened interpolation (for cursor following)

## Keyframes

Animate through multiple states in a single tween.

### Array Syntax

```javascript
gsap.to('.box', {
  keyframes: [
    { x: 100, duration: 1 },
    { y: 100, duration: 0.5 },
    { rotation: 360, duration: 1, ease: 'elastic' }
  ]
})
```

### Percentage Syntax (CSS-style)

```javascript
gsap.to('.box', {
  keyframes: {
    '0%': { x: 0, y: 0 },
    '50%': { x: 100, y: 0, ease: 'power2.in' },
    '100%': { x: 100, y: 100 }
  },
  duration: 2
})
```

### Shared Properties

```javascript
gsap.to('.box', {
  keyframes: {
    x: [0, 100, 100],
    y: [0, 0, 100],
    ease: 'power2.inOut'  // applies to all keyframes
  },
  duration: 2
})
```

## Ticker

GSAP's internal timing engine. Use for custom render loops.

```javascript
// Add function to tick
const update = () => console.log('tick')
gsap.ticker.add(update)

// Remove function
gsap.ticker.remove(update)

// Set FPS (default: 60)
gsap.ticker.fps(30)

// Lag smoothing - threshold, adjustedLag
// Prevents huge jumps after tab becomes visible again
gsap.ticker.lagSmoothing(500, 33)  // if lag > 500ms, act as if 33ms

// Disable lag smoothing (not recommended)
gsap.ticker.lagSmoothing(0)

// Delta ratio (useful for physics)
gsap.ticker.add(() => {
  velocity *= gsap.ticker.deltaRatio()  // adjust for frame rate
})
```

## Register Effect

Create reusable animation effects.

```javascript
// Define effect
gsap.registerEffect({
  name: 'fade',
  effect: (targets, config) => {
    return gsap.to(targets, {
      duration: config.duration,
      opacity: 0,
      y: config.y,
      ease: 'power2.out'
    })
  },
  defaults: { duration: 1, y: 0 },
  extendTimeline: true  // enable tl.fade()
})

// Use effect
gsap.effects.fade('.box')
gsap.effects.fade('.box', { duration: 2, y: -50 })

// Use in timeline (if extendTimeline: true)
const tl = gsap.timeline()
tl.fade('.box', { y: 20 })
  .fade('.box2', {}, '<')
```

## Get Property

Read current property values.

```javascript
// Get current value
const x = gsap.getProperty('.box', 'x')
const rotation = gsap.getProperty('.box', 'rotation')

// With unit
const xPx = gsap.getProperty('.box', 'x', 'px')
const widthPercent = gsap.getProperty('.box', 'width', '%')

// From element reference
const element = document.querySelector('.box')
const opacity = gsap.getProperty(element, 'opacity')
```

## Advanced Repeat Options

### repeatRefresh

Re-records start/end values on each repeat. Useful with random values.

```javascript
gsap.to('.box', {
  x: 'random(-200, 200)',
  y: 'random(-100, 100)',
  rotation: 'random(-180, 180)',
  repeat: -1,
  repeatRefresh: true,  // new random values each repeat!
  duration: 1
})
```

### invalidate()

Clears recorded start/end values. Call before next play to use current values.

```javascript
const tween = gsap.to('.box', { x: 100, paused: true })

// Later, after box position changed:
tween.invalidate()
tween.restart()  // now animates from new current position
```

## Match Media

Responsive animations:

```javascript
const mm = gsap.matchMedia()

mm.add('(min-width: 800px)', () => {
  // Desktop animations
  gsap.to('.box', { x: 500 })

  return () => {
    // Cleanup when condition no longer matches
  }
})

mm.add('(max-width: 799px)', () => {
  // Mobile animations
  gsap.to('.box', { x: 100 })
})

// Multiple conditions
mm.add({
  isDesktop: '(min-width: 800px)',
  isMobile: '(max-width: 799px)',
  reduceMotion: '(prefers-reduced-motion: reduce)'
}, (context) => {
  const { isDesktop, reduceMotion } = context.conditions

  if (reduceMotion) {
    gsap.set('.box', { x: 500 })
  } else if (isDesktop) {
    gsap.to('.box', { x: 500 })
  }
})
```
