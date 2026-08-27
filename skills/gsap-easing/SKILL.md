---
name: gsap-easing
description: Use when implementing animation easing functions, custom easing, elastic effects, bounce animations, or controlling animation velocity curves.
---

# GSAP Easing

Easing functions control how animations progress over time. GSAP provides extensive built-in eases plus plugins for custom curves, elastic effects, and bounce animations.

## Basic Eases

### Power Eases

```javascript
// Power0 - Linear (no easing)
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'none'  // Same as 'power0'
})

// Power1 - Default
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power1.out'  // GSAP default
})

// Power2
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power2.out'
})

// Power3
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power3.out'
})

// Power4 - Strongest curve
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power4.out'
})
```

### Ease Modifiers

```javascript
// In - Slow start, fast end
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power2.in'
})

// Out - Fast start, slow end
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power2.out'
})

// InOut - Slow both ends, fast middle
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'power2.inOut'
})
```

### Back Ease

```javascript
// Back.out - Overshoots target then settles
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'back.out(1.7)  // 1.7 is overshoot amount
})

// Back.in - Pulls back first
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'back.in(1.7)'
})

// Back.inOut - Both directions
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'back.inOut(1.7)'
})
```

### Elastic Ease

```javascript
// Elastic.out - Springy overshoot
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'elastic.out(1, 0.3)'
  // First param: amplitude (1 = no overshoot)
  // Second param: period (lower = more wiggles)
})

// Elastic.in - Elastic start
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'elastic.in(1, 0.3)'
})

// Elastic.inOut - Both directions
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'elastic.inOut(1, 0.3)'
})
```

### Bounce Ease

```javascript
// Bounce.out - Ball-like bounce at end
gsap.to('.box', {
  y: -200,
  duration: 1,
  ease: 'bounce.out'
})

// Bounce.in - Bounce at start
gsap.to('.box', {
  y: -200,
  duration: 1,
  ease: 'bounce.in'
})

// Bounce.inOut - Bounce both ends
gsap.to('.box', {
  y: -200,
  duration: 1,
  ease: 'bounce.inOut'
})
```

### Expo Ease

```javascript
// Expo.out - Very strong ease out
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'expo.out'
})

// Expo.in - Very strong ease in
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'expo.in'
})

// Expo.inOut - Both very strong
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'expo.inOut'
})
```

### Circ and Sine

```javascript
// Circ - Circular easing
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'circ.out'
})

// Sine - Gentle sine wave
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'sine.out'
})
```

## Steps Ease

### Basic Steps

```javascript
// 5 discrete steps
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'steps(5)'
})
```

### Steps with Direction

```javascript
// Start at top of step
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'steps(5, start)'
})

// End at top of step
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'steps(5, end)'
})

// Both
gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'steps(5, both)'
})
```

### Steps for Sprite Animation

```javascript
gsap.to('.sprite', {
  backgroundPosition: `-${frameWidth * 7}px 0`,
  duration: 0.8,
  ease: 'steps(7)',  // 7 frames
  repeat: -1
})
```

## EasePack Plugin

### SlowMo

```bash
npm install gsap
```

```javascript
import { EasePack } from 'gsap/EasePack'
gsap.registerPlugin(EasePack)

// SlowMo - Decelerates, holds, accelerates
gsap.to('.box', {
  x: 200,
  duration: 2,
  ease: 'slow(0.7, 0.7, false)'
  // First: ease portion
  // Second: hold portion
  // Third: ease out portion (true/false)
})
```

### RoughEase

```javascript
// RoughEase - Jagged, organic feel
gsap.to('.box', {
  x: 200,
  duration: 2,
  ease: 'rough({
    template: 'power1.out',
    strength: 1,
    points: 20,
    taper: 'both',
    randomize: true,
    clamp: false
  })
})

// Pre-configured rough eases
gsap.to('.box', {
  x: 200,
  duration: 2,
  ease: 'rough.ease'  // Simplified
})
```

### ExpoScale

```javascript
// ExpoScale - For scaling animations
gsap.to('.box', {
  scale: 5,
  duration: 2,
  ease: 'expoScale(0.5, 3, 'power2.inOut)'
  // From scale, to scale, ease function
})
```

## CustomEase (formerly members-only; now included)

### Create Custom Ease

```bash
npm install gsap
```

```javascript
import { CustomEase } from 'gsap/CustomEase'
gsap.registerPlugin(CustomEase)

// Create from SVG path
CustomEase.create('myEase', 'M0,0 C0.5,0 0.5,1 1,1')

gsap.to('.box', {
  x: 200,
  duration: 1,
  ease: 'myEase'
})
```

### Create from Points

```javascript
CustomEase.create('myEase', [
  { x: 0, y: 0 },
  { x: 0.3, y: 0.2, controlPoint: { x: 0.15, y: 0 } },
  { x: 0.7, y: 0.8, controlPoint: { x: 0.85, y: 1 } },
  { x: 1, y: 1 }
])
```

### Get SVG Path

```javascript
// Visual method - get path from UI
CustomEase.create('visualEase', 'M0,100 C50,0 100,100 100,100')
```

## CustomWiggle (formerly members-only; now included)

```javascript
import { CustomWiggle } from 'gsap/CustomWiggle'
gsap.registerPlugin(CustomWiggle)

// Create wiggle ease
CustomWiggle.create('myWiggle', {
  wiggles: 2,
  amplitude: 1
})

gsap.to('.box', {
  x: 200,
  rotation: 20,
  duration: 2,
  ease: 'myWiggle'
})
```

## CustomBounce (formerly members-only; now included)

```javascript
import { CustomBounce } from 'gsap/CustomBounce'
gsap.registerPlugin(CustomBounce)

// Create custom bounce
CustomBounce.create('myBounce', {
  squash: 2,
  bounce: 5
})

gsap.to('.ball', {
  y: -200,
  duration: 1,
  ease: 'myBounce'
})
```

## Ease Selection Guide

### By Use Case

| Effect | Recommended Ease |
|--------|-----------------|
| Default UI | `power2.out` |
| Entrance | `back.out(1.7)` or `power3.out` |
| Exit | `power2.in` |
| Attention | `elastic.out(1, 0.3)` |
| Playful | `bounce.out` |
| Smooth | `sine.inOut` |
| Punchy | `power4.out` |
| Organic | `rough.ease` |
| Subtle | `power1.inOut` |
| Natural | `expo.inOut` |
| Step | `steps(5)` |

### By Property

| Property | Recommended Ease |
|----------|-----------------|
| Position (x,y) | `power2.out`, `back.out` |
| Scale | `back.out(1.7)`, `elastic.out` |
| Rotation | `elastic.out`, `back.out` |
| Opacity | `power2.out`, `sine.out` |
| Color | `power1.out` |
| Filter | `power1.out` |

## Timeline Ease Control

### Per-Tween Ease

```javascript
const tl = gsap.timeline()

tl.to('.box1', {
    x: 100,
    duration: 1,
    ease: 'power2.out'  // Individual ease
  })
  .to('.box2', {
    x: 100,
    duration: 1,
    ease: 'back.out'  // Different ease
  })
```

### Timeline Defaults

```javascript
const tl = gsap.timeline({
  defaults: {
    ease: 'power2.out',  // Default for all tweens
    duration: 1
  }
})

tl.to('.box1', { x: 100 })  // Uses default ease
  .to('.box2', {
    x: 100,
    ease: 'back.out'  // Overrides default
  })
```

### Ease Each

```javascript
// Keyframes with per-keyframe ease
gsap.to('.box', {
  keyframes: [
    { x: 100, ease: 'power2.out' },
    { y: 100, ease: 'back.out' },
    { x: 0, y: 0, ease: 'power2.out' }
  ],
  easeEach: 'power1.out'  // If individual ease not specified
})
```

## Ease Testing

### Visual Comparison

```javascript
const eases = [
  'none',
  'power1.out',
  'power2.out',
  'power3.out',
  'power4.out',
  'back.out(1.7)',
  'elastic.out(1, 0.3)',
  'bounce.out'
]

eases.forEach((ease, i) => {
  gsap.to(`.box-${i}`, {
    x: 200,
    duration: 1,
    ease: ease,
    delay: i * 1.2
  })
})
```

### Ease Visualization

```javascript
function visualizeEase(easeName) {
  const path = []
  for (let i = 0; i <= 100; i++) {
    const progress = i / 100
    const easedValue = gsap.parseEase(easeName)(progress)
    path.push({ x: progress * 100, y: (1 - easedValue) * 100 })
  }

  // Draw SVG path
  const d = 'M' + path.map(p => `${p.x},${p.y}`).join(' L')
  console.log(d)
}

visualizeEase('power2.out')
```

## Performance Considerations

### Use Power Eases

```javascript
// ❌ Complex eases on many elements
gsap.to('.many-boxes', {
  x: 200,
  ease: 'elastic.out(1, 0.3)',  // Computationally expensive
  stagger: 0.05
})

// ✅ Simpler eases for performance
gsap.to('.many-boxes', {
  x: 200,
  ease: 'power2.out',  // Faster
  stagger: 0.05
})
```

### Ease Caching

```javascript
// Parse and cache ease
const myEase = gsap.parseEase('power2.out')

// Use cached ease
gsap.to('.box', {
  x: 200,
  ease: myEase
})
```

## Common Patterns

### Elastic Entrance

```javascript
gsap.from('.modal', {
  scale: 0,
  opacity: 0,
  duration: 0.8,
  ease: 'back.out(1.7)'
})
```

### Bouncy Button

```javascript
const btn = document.querySelector('.button')

btn.addEventListener('mouseenter', () => {
  gsap.to(btn, {
    scale: 1.1,
    duration: 0.3,
    ease: 'elastic.out(1, 0.5)'
  })
})

btn.addEventListener('mouseleave', () => {
  gsap.to(btn, {
    scale: 1,
    duration: 0.3,
    ease: 'power2.out'
  })
})
```

### Smooth Scroll

```javascript
gsap.to(window, {
  scrollTo: { y: target },
  duration: 1,
  ease: 'power2.inOut'
})
```

### Natural Motion

```javascript
gsap.to('.ball', {
  y: 500,
  duration: 1.5,
  ease: 'bounce.out'
})
```

## Common Mistakes

### 1. Wrong Ease for Context

```javascript
// ❌ Elastic for subtle hover
gsap.to('.link', {
  color: '#ff0000',
  ease: 'elastic.out(1, 0.3)',
  duration: 0.3
})

// ✅ Use appropriate ease
gsap.to('.link', {
  color: '#ff0000',
  ease: 'power2.out',
  duration: 0.3
})
```

### 2. Using Wrong Ease Direction

```javascript
// ❌ Using in for entrance
gsap.from('.box', {
  opacity: 0,
  ease: 'power2.in'  // Wrong direction!
})

// ✅ Use out for entrance
gsap.from('.box', {
  opacity: 0,
  ease: 'power2.out'
})
```

### 3. Overpowering Overshoot

```javascript
// ❌ Too much overshoot
gsap.to('.box', {
  x: 200,
  ease: 'back.out(5)'  // Too aggressive!
})

// ✅ Reasonable overshoot
gsap.to('.box', {
  x: 200,
  ease: 'back.out(1.7)'  // Sweet spot
})
```

## Best Practices

1. **Match ease to use case** - UI, playful, natural
2. **Consider property type** - Different properties benefit from different eases
3. **Test different eases** - Try multiple options
4. **Use power eases for performance** - Simpler = faster
5. **Reserve complex eases for attention** - Don't overuse elastic/bounce
6. **Set timeline defaults** - Consistent feel across animations
7. **Visualize eases** - Understand curve behavior
8. **Consider user experience** - Don't make users wait

## Quick Reference

| Ease | Description |
|------|-------------|
| `none` | Linear (no easing) |
| `power1.out` | Default GSAP ease |
| `power2.out` | Standard UI ease |
| `back.out(1.7)` | Overshoots target |
| `elastic.out(1, 0.3)` | Springy oscillation |
| `bounce.out` | Ball-like bounce |
| `expo.out` | Very strong ease |
| `sine.out` | Gentle sine wave |
| `steps(5)` | Discrete steps |
| `circ.out` | Circular easing |
| `rough.ease` | Organic, jagged |
| `slow(0.7)` | Decelerate-hold-accelerate |
