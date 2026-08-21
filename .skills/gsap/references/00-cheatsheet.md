# GSAP Cheatsheet

Quick reference for common operations.

## Tween Methods

```javascript
// Animate TO values
gsap.to(target, { x: 100, duration: 1 })

// Animate FROM values
gsap.from(target, { opacity: 0 })

// Animate FROM/TO values
gsap.fromTo(target, { x: 0 }, { x: 100 })

// Set instantly (no animation)
gsap.set(target, { x: 100 })
```

## Timeline Creation

```javascript
// Basic
const tl = gsap.timeline()

// With options
const tl = gsap.timeline({
  defaults: { duration: 1, ease: 'power2.out' },
  paused: true,
  repeat: -1,
  yoyo: true,
  onComplete: () => {}
})

// Add tweens
tl.to('.a', { x: 100 })
  .to('.b', { y: 100 }, '-=0.5')  // 0.5s overlap
  .to('.c', { z: 100 }, '<')       // same start time
```

## Position Parameter

```javascript
// Absolute time
tl.to(el, {}, 0)           // at 0s
tl.to(el, {}, 2)           // at 2s

// Relative to timeline end
tl.to(el, {})              // sequential (default)
tl.to(el, {}, '+=0.5')     // 0.5s gap
tl.to(el, {}, '-=0.5')     // 0.5s overlap

// Relative to previous animation
tl.to(el, {}, '<')         // same START as prev
tl.to(el, {}, '>')         // same END as prev
tl.to(el, {}, '<0.5')      // 0.5s after prev START
tl.to(el, {}, '>-0.2')     // 0.2s before prev END

// Labels
tl.addLabel('intro')
tl.to(el, {}, 'intro')     // at label
tl.to(el, {}, 'intro+=1')  // 1s after label

// Percentage (v3.7+)
tl.to(el, {}, '-=25%')     // overlap by 25% of inserting tween
tl.to(el, {}, '<50%')      // 50% into previous tween
```

## Playback Control

```javascript
// Get reference
const tween = gsap.to(...)
const tl = gsap.timeline(...)

// Control
.play()
.pause()
.resume()
.reverse()
.restart()

// Position
.seek(1.5)          // go to 1.5s
.seek('label')      // go to label
.progress(0.5)      // go to 50%
.time(2)            // set time to 2s

// Speed
.timeScale(2)       // 2x speed
.timeScale(0.5)     // half speed

// State
.isActive()         // returns boolean
.progress()         // returns 0-1

// Kill
.kill()             // destroy
.revert()           // revert to pre-animation
```

## Special Properties

```javascript
gsap.to(target, {
  // Timing
  duration: 1,
  delay: 0.5,
  repeat: 2,          // -1 for infinite
  repeatDelay: 0.5,
  yoyo: true,

  // Easing
  ease: 'power2.out',

  // Stagger
  stagger: 0.1,
  stagger: { each: 0.1, from: 'center' },

  // Callbacks
  onStart: () => {},
  onUpdate: () => {},
  onComplete: () => {},
  onRepeat: () => {},
  onReverseComplete: () => {},

  // Advanced
  overwrite: 'auto',
  id: 'myTween',
  paused: true,
  immediateRender: false,
  lazy: false
})
```

## Transform Shortcuts

```javascript
gsap.to(el, {
  // Position (GPU accelerated)
  x: 100,           // translateX
  y: 100,           // translateY
  z: 100,           // translateZ
  xPercent: 50,     // translateX as %
  yPercent: -50,    // translateY as %

  // Scale
  scale: 2,
  scaleX: 2,
  scaleY: 0.5,

  // Rotation (degrees)
  rotation: 360,
  rotationX: 45,
  rotationY: 45,

  // Skew
  skewX: 20,
  skewY: 10,

  // Origin
  transformOrigin: 'center center',
  transformOrigin: '0% 100%',

  // Visibility
  opacity: 0.5,
  autoAlpha: 0,     // opacity + visibility

  // Performance
  force3D: true
})
```

## Relative Values

```javascript
x: '+=100'    // add 100
x: '-=50'     // subtract 50
x: '*=2'      // multiply by 2
rotation: '+=360'
```

## Random Values

```javascript
x: 'random(-100, 100)'           // random in range
x: 'random(-100, 100, 5)'        // snapped to 5
x: 'random([0, 100, 200])'       // random from array
```

## Function-Based Values

```javascript
gsap.to('.box', {
  x: (i, el, els) => i * 100,    // different per target
  duration: (i) => 0.5 + i * 0.1
})
```

## Keyframes

```javascript
gsap.to(el, {
  keyframes: [
    { x: 100, duration: 1 },
    { y: 100, duration: 0.5 },
    { opacity: 0, duration: 0.5 }
  ]
})

// With percentages (CSS keyframe style)
gsap.to(el, {
  keyframes: {
    '0%': { x: 0 },
    '50%': { x: 100, ease: 'power2.in' },
    '100%': { x: 50 }
  },
  duration: 2
})
```

## Eases

```javascript
// Core (each has .in, .out, .inOut)
'none'              // linear
'power1' - 'power4' // subtle to strong
'circ'              // circular
'expo'              // exponential
'sine'              // gentle

// Expressive
'elastic.out(1, 0.3)'  // amplitude, period
'back.out(1.7)'        // overshoot
'bounce.out'
'steps(5)'

// Custom
CustomEase.create('custom', 'M0,0...')
```

## Common Utility Methods

```javascript
// Convert to array
gsap.utils.toArray('.box')

// Scoped selector
const q = gsap.utils.selector(container)
q('.box')

// Clamp value
gsap.utils.clamp(0, 100, value)

// Map range
gsap.utils.mapRange(0, 100, 0, 500, value)

// Interpolate
gsap.utils.interpolate(0, 100, 0.5)  // 50
gsap.utils.interpolate('red', 'blue', 0.5)

// Snap
gsap.utils.snap(10, value)           // to nearest 10
gsap.utils.snap([0, 25, 50], value)  // to array values

// Wrap (for infinite loops)
gsap.utils.wrap(0, 100, 150)  // 50

// Random
gsap.utils.random(0, 100)
gsap.utils.random([a, b, c])

// Pipe (chain utilities)
const process = gsap.utils.pipe(
  gsap.utils.clamp(0, 100),
  gsap.utils.snap(10)
)
```

## Global Methods

```javascript
// Kill tweens
gsap.killTweensOf(target)
gsap.killTweensOf(target, 'x,y')

// Get tweens
gsap.getTweensOf(target)
gsap.getById('myTween')

// Check state
gsap.isTweening(target)

// Get property
gsap.getProperty(el, 'x')
gsap.getProperty(el, 'x', 'px')

// Defaults
gsap.defaults({ duration: 1, ease: 'power2' })

// Config
gsap.config({ nullTargetWarn: false })

// Match media
gsap.matchMedia().add('(min-width: 800px)', () => {})
```

## ScrollTrigger Quick Reference

```javascript
gsap.to(el, {
  scrollTrigger: {
    trigger: el,
    start: 'top 80%',
    end: 'bottom 20%',
    scrub: true,        // or number for smoothing
    pin: true,
    markers: true,
    toggleActions: 'play none none none',
    toggleClass: 'active',
    onEnter: () => {},
    onLeave: () => {},
    onUpdate: (self) => {}
  }
})

// Static methods
ScrollTrigger.refresh()
ScrollTrigger.getAll()
ScrollTrigger.killAll()
```

## Plugin Registration

```javascript
import { ScrollTrigger } from 'gsap/ScrollTrigger'
gsap.registerPlugin(ScrollTrigger)

// Register multiple
gsap.registerPlugin(ScrollTrigger, Flip, SplitText)
```
