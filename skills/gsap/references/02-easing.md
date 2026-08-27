# GSAP Easing

## Built-in Eases

### Power Eases (Most Common)

```javascript
// Power eases: 1-4 (higher = more pronounced)
gsap.to('.box', { x: 100, ease: 'power1.out' })  // subtle
gsap.to('.box', { x: 100, ease: 'power2.out' })  // moderate (good default)
gsap.to('.box', { x: 100, ease: 'power3.out' })  // strong
gsap.to('.box', { x: 100, ease: 'power4.out' })  // very strong

// Directions
ease: 'power2.in'    // slow start, fast end
ease: 'power2.out'   // fast start, slow end (default)
ease: 'power2.inOut' // slow start and end
```

### Specialty Eases

```javascript
// Elastic (spring-like overshoot)
ease: 'elastic.out(1, 0.3)'  // amplitude, period
ease: 'elastic.in'
ease: 'elastic.inOut'

// Bounce (bouncing ball effect)
ease: 'bounce.out'
ease: 'bounce.in'
ease: 'bounce.inOut'

// Back (overshoots then returns)
ease: 'back.out(1.7)'  // overshoot amount
ease: 'back.in(1.7)'
ease: 'back.inOut(1.7)'

// Expo (exponential - very dramatic)
ease: 'expo.out'
ease: 'expo.in'
ease: 'expo.inOut'

// Circ (circular motion)
ease: 'circ.out'
ease: 'circ.in'
ease: 'circ.inOut'

// Sine (gentle sinusoidal)
ease: 'sine.out'
ease: 'sine.in'
ease: 'sine.inOut'
```

### Linear and Steps

```javascript
// No easing (constant speed)
ease: 'none'
ease: 'linear'  // alias

// Steps (discrete jumps)
ease: 'steps(5)'           // 5 equal steps
ease: 'steps(12)'          // 12 steps (frame-by-frame feel)
```

## Ease Configuration

### Elastic Parameters

```javascript
// elastic(amplitude, period)
// amplitude: overshoot strength (default: 1)
// period: oscillation frequency (default: 0.3)

ease: 'elastic.out(1, 0.3)'    // default
ease: 'elastic.out(1.5, 0.5)'  // more bounce, slower
ease: 'elastic.out(0.5, 0.2)'  // less bounce, faster
```

### Back Parameters

```javascript
// back(overshoot)
// overshoot: how far past target (default: 1.7)

ease: 'back.out(1.7)'  // default
ease: 'back.out(3)'    // dramatic overshoot
ease: 'back.out(1)'    // subtle overshoot
```

## Custom Eases (EasePack Required)

### SlowMo

```javascript
import { SlowMo } from 'gsap/EasePack'
gsap.registerPlugin(SlowMo)

// Slow motion in the middle
gsap.to('.box', {
  x: 500,
  ease: 'slow(0.7, 0.7, false)'
  // linearRatio, power, yoyoMode
})
```

### RoughEase

```javascript
import { RoughEase } from 'gsap/EasePack'
gsap.registerPlugin(RoughEase)

// Jittery/shaky animation
gsap.to('.box', {
  x: 500,
  ease: 'rough({ strength: 1, points: 20, taper: "none" })'
})
```

### ExpoScaleEase

```javascript
import { ExpoScaleEase } from 'gsap/EasePack'
gsap.registerPlugin(ExpoScaleEase)

// Scale-aware exponential easing
gsap.to('.box', {
  x: 500,
  ease: 'expoScale(1, 10)'  // startScale, endScale
})
```

## CustomEase (Separate Plugin)

```javascript
import { CustomEase } from 'gsap/CustomEase'
gsap.registerPlugin(CustomEase)

// Create from SVG path data
CustomEase.create('myEase', 'M0,0 C0.126,0.382 0.282,1.674 0.44,1.674 0.778,1.674 0.824,0.048 1,0')

gsap.to('.box', { x: 500, ease: 'myEase' })

// Create from cubic-bezier (CSS-style)
CustomEase.create('cubic', '0.25, 0.1, 0.25, 1')
```

## CustomBounce

```javascript
import { CustomBounce, CustomEase } from 'gsap/CustomBounce'
gsap.registerPlugin(CustomEase, CustomBounce)

// Create custom bounce
CustomBounce.create('myBounce', {
  strength: 0.6,      // bounce height (0-1)
  squash: 3,          // squash amount (0 = none)
  squashID: 'myBounce-squash'
})

// Use bounce for position
gsap.from('.ball', { y: -200, ease: 'myBounce', duration: 2 })

// Use squash for scale (synchronized)
gsap.to('.ball', {
  scaleX: 1.4,
  scaleY: 0.6,
  ease: 'myBounce-squash',
  transformOrigin: 'center bottom',
  duration: 2
})
```

## CustomWiggle

```javascript
import { CustomWiggle, CustomEase } from 'gsap/CustomWiggle'
gsap.registerPlugin(CustomEase, CustomWiggle)

// Create wiggle ease
CustomWiggle.create('myWiggle', {
  wiggles: 6,           // number of oscillations
  type: 'easeOut'       // uniform, easeOut, easeInOut, anticipate, random
})

// Apply to rotation
gsap.to('.box', {
  rotation: 30,   // wiggles between -30 and +30
  ease: 'myWiggle',
  duration: 2
})
```

## Ease Aliases

```javascript
// Legacy aliases still work
ease: 'Linear.easeNone'   // = 'none'
ease: 'Quad.easeOut'      // = 'power1.out'
ease: 'Cubic.easeOut'     // = 'power2.out'
ease: 'Quart.easeOut'     // = 'power3.out'
ease: 'Quint.easeOut'     // = 'power4.out'
ease: 'Strong.easeOut'    // = 'power4.out'
```

## Setting Default Ease

```javascript
// Global default
gsap.defaults({ ease: 'power2.out' })

// Timeline default
const tl = gsap.timeline({
  defaults: { ease: 'power3.inOut' }
})

// Individual tween overrides
tl.to('.box', { x: 100 })                    // uses power3.inOut
tl.to('.box', { x: 200, ease: 'bounce.out' }) // uses bounce.out
```

## Common Use Cases

```javascript
// UI elements entering
ease: 'power2.out'    // smooth deceleration

// UI elements exiting
ease: 'power2.in'     // accelerate away

// Modal/dialog
ease: 'back.out(1.4)' // slight overshoot, playful

// Loading spinners
ease: 'none'          // constant rotation

// Attention-grabbing
ease: 'elastic.out(1, 0.3)'

// Scroll-linked (scrub)
ease: 'none'          // linear for smooth scrubbing

// Page transitions
ease: 'power3.inOut'  // dramatic entrance/exit

// Hover states
ease: 'power1.out'    // subtle, responsive
duration: 0.3
```
