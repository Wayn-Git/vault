---
name: gsap-utilities
description: Use when using GSAP utility functions, math helpers, data transformations, or when working with clamp, mapRange, random, and other GSAP utilities.
---

# GSAP Utilities

GSAP provides powerful utility functions for data manipulation, math operations, and common animation tasks. These utilities streamline complex logic and improve code readability.

## Core Utilities

### clamp

```javascript
import { gsap } from 'gsap'

// Clamp value between min and max
const clamped = gsap.utils.clamp(0, 100, 150)  // Returns 100
const clamped2 = gsap.utils.clamp(0, 100, 50)  // Returns 50

// Return reusable function
const clamp50to100 = gsap.utils.clamp(50, 100)
console.log(clamp50to100(150))  // Returns 100
console.log(clamp50to100(25))   // Returns 50
```

### mapRange

```javascript
// Map value from one range to another
const mapped = gsap.utils.mapRange(0, 100, 0, 500, 50)  // Returns 250
const mapped2 = gsap.utils.mapRange(0, 100, 0, window.innerWidth, 50)

// Map with different ratios
const mapped3 = gsap.utils.mapRange(0, 100, 0, 1, 50)  // 0.5
```

### normalize

```javascript
// Normalize value to 0-1 range
const normalized = gsap.utils.normalize(100, 200, 150)  // Returns 0.5
const normalized2 = gsap.utils.normalize(0, 100, 75)   // Returns 0.75

// Use in animations
gsap.to('.box', {
  x: gsap.utils.mapRange(0, window.innerWidth, 0, 500, scrollProgress)
})
```

## Array Utilities

### toArray

```javascript
// Convert array-like to real array
const nodeList = document.querySelectorAll('.box')
const array = gsap.utils.toArray(nodeList)

// Works with arguments
function sum() {
  const args = gsap.utils.toArray(arguments)
  return args.reduce((a, b) => a + b, 0)
}
```

### random

```javascript
// Random number between min and max
const num = gsap.utils.random(0, 100)  // Random between 0-100

// Random with increment
const stepped = gsap.utils.random(0, 100, 10)  // Random multiple of 10 (0, 10, 20...100)

// Random from array
const items = ['red', 'blue', 'green']
const color = gsap.utils.random(items)  // Random color from array

// Use in animations
gsap.to('.particle', {
  x: gsap.utils.random(-200, 200),
  y: gsap.utils.random(-200, 200),
  backgroundColor: gsap.utils.random(['#ff0000', '#00ff00', '#0000ff']),
  duration: 1
})
```

### wrap

```javascript
// Wrap value in range
const wrapped = gsap.utils.wrap(0, 10, 12)  // Returns 2 (12 % 10)
const wrapped2 = gsap.utils.wrap(0, 10, -1) // Returns 9

// Wrap in array
const items = ['a', 'b', 'c', 'd']
const item = gsap.utils.wrap(items)  // Returns 'a', 'b', 'c', 'd', 'a', 'b'...
console.log(item(5))  // Returns 'b'

// Circular animation
gsap.to('.carousel', {
  xPercent: gsap.utils.wrap(0, 100, index * 25),
  duration: 0.5
})
```

### wrapYoyo

```javascript
// Oscillate value in range
const yoyo = gsap.utils.wrapYoyo(0, 10)

console.log(yoyo(0))   // 0
console.log(yoyo(5))   // 5
console.log(yoyo(10))  // 10
console.log(yoyo(15))  // 5
console.log(yoyo(20))  // 0
console.log(yoyo(25))  // 5
```

## Transformation Utilities

### distribute

```javascript
// Distribute value across array
const items = document.querySelectorAll('.item')

gsap.to(items, {
  x: gsap.utils.distribute(500, items)  // 0, 100, 200, 300, 400
  duration: 1
})

// Grid distribution
const grid = gsap.utils.distribute(500, 20, 'columns', 5)
// Creates values for 4 columns, 5 rows

// Custom progression
const custom = gsap.utils.distribute(500, items, (i, total) => {
  return i * (500 / total)
})
```

### interpolate

```javascript
// Interpolate between values
const interpolated = gsap.utils.interpolate(0, 100, 0.5)  // Returns 50

// Interpolate colors
const color = gsap.utils.interpolate('#ff0000', '#0000ff', 0.5)  // Returns purple
const color2 = gsap.utils.interpolate('red', 'blue', 0.7)  // Returns blue-ish

// Interpolate objects
const obj = gsap.utils.interpolate(
  { x: 0, y: 0 },
  { x: 100, y: 100 },
  0.5
)
// Returns { x: 50, y: 50 }

// Get interpolator function
const interpolator = gsap.utils.interpolate(0, 100)
console.log(interpolator(0.25))  // 25
console.log(interpolator(0.75))  // 75
```

### pipe

```javascript
// Chain multiple functions
const process = gsap.utils.pipe(
  gsap.utils.clamp(0, 100),
  gsap.utils.mapRange(0, 100, 0, 500)
)

const result = process(75)  // Returns 375
console.log(result)  // 375

// Complex processing
const complexPipe = gsap.utils.pipe(
  gsap.utils.clamp(0, 100),
  (val) => val * 2,
  gsap.utils.mapRange(0, 200, 0, 1)
)

const result2 = complexPipe(50)  // Returns 0.5
```

## Unit Utilities

### getUnit

```javascript
// Extract unit from value
const unit = gsap.utils.getUnit('100px')     // 'px'
const unit2 = gsap.utils.getUnit('2.5s')     // 's'
const unit3 = gsap.utils.getUnit('50%')      // '%'
const unit4 = gsap.utils.getUnit('rotate(90deg)') // 'deg'
```

### unitize

```javascript
// Add unit to value
const withUnit = gsap.utils.unitize(100, 'px')  // '100px'
const withUnit2 = gsap.utils.unitize(50, '%')  // '50%'

// Create unitizer function
const toPx = gsap.utils.unitize('px')
console.log(toPx(100))  // '100px'

// Use in animations
gsap.to('.box', {
  x: gsap.utils.unitize(scrollY * 2, 'px'),
  duration: 0.1
})
```

### removeUnit

```javascript
// Remove unit from value
const value = gsap.utils.removeUnit('100px')     // 100
const value2 = gsap.utils.removeUnit('2.5s')      // 2.5
const value3 = gsap.utils.removeUnit('50%')       // 50
```

## Color Utilities

### splitColor

```javascript
// Split color into components
const color = gsap.utils.splitColor('red')
// Returns [255, 0, 0, 1]  // r, g, b, a

const color2 = gsap.utils.splitColor('#ff0000')
// Returns [255, 0, 0, 1]

const color3 = gsap.utils.splitColor('rgba(255, 0, 0, 0.5)')
// Returns [255, 0, 0, 0.5]
```

### checkPrefix

```javascript
// Check and return vendor prefix
const prefix = gsap.utils.checkPrefix('.box', 'transform')
// Returns '-webkit-' or '' if not needed

const prefix2 = gsap.utils.checkPrefix('.box', 'filter')
// Returns appropriate prefix
```

## Selector Utilities

### selector

```javascript
// Create scoped selector
const q = gsap.utils.selector('.container')

// Only selects within .container
const elements = q('.box')

// Use in animations
gsap.to(q('.box'), {
  x: 100,
  duration: 1
})
```

## Math Utilities

### snap

```javascript
// Snap to nearest increment
const snapped = gsap.utils.snap(20, 47)  // Returns 40
const snapped2 = gsap.utils.snap(20, 53)  // Returns 60

// Snap to array
const snapped3 = gsap.utils.snap([0, 50, 100], 45)  // Returns 50
const snapped4 = gsap.utils.snap([0, 50, 100], 30)  // Returns 0

// Snap with radius
const snapped5 = gsap.utils.snap([0, 50, 100], 45, 10)  // Returns 50 (within radius)
const snapped6 = gsap.utils.snap([0, 50, 100], 30, 5)   // Returns 30 (not within radius)
```

### shuffle

```javascript
// Shuffle array
const array = [1, 2, 3, 4, 5]
const shuffled = gsap.utils.shuffle(array)  // Random order

// Shuffle DOM elements
const elements = gsap.utils.toArray('.item')
const shuffledElements = gsap.utils.shuffle(elements)
```

## Practical Examples

### Progress-Based Animation

```javascript
// Map scroll progress to animation
gsap.to('.box', {
  x: gsap.utils.mapRange(0, 1, 0, 500, scrollProgress),
  opacity: gsap.utils.interpolate(1, 0, scrollProgress),
  duration: 1
})
```

### Parallax with Clamp

```javascript
// Clamp parallax value
const parallaxX = gsap.utils.clamp(-50, 50, mouseX - centerX)

gsap.to('.parallax-element', {
  x: parallaxX,
  duration: 0.5
})
```

### Circular Navigation

```javascript
let currentIndex = 0
const total = 5

function nextSlide() {
  currentIndex = gsap.utils.wrap(0, total, currentIndex + 1)
  goToSlide(currentIndex)
}

function prevSlide() {
  currentIndex = gsap.utils.wrap(0, total, currentIndex - 1)
  goToSlide(currentIndex)
}
```

### Distributed Stagger

```javascript
const items = document.querySelectorAll('.item')

gsap.to(items, {
  x: gsap.utils.distribute(500, items),
  duration: 1,
  ease: 'power2.out'
})
```

### Color Interpolation

```javascript
// Interpolate color based on progress
const color = gsap.utils.interpolate('#ff0000', '#0000ff', progress)

gsap.to('.box', {
  backgroundColor: color,
  duration: 1
})
```

### Value Mapping

```javascript
// Map mouse position to rotation
const rotation = gsap.utils.mapRange(
  0, window.innerWidth,
  -30, 30,
  mouseX
)

gsap.to('.box', {
  rotation: rotation,
  duration: 0.5
})
```

### Responsive Values

```javascript
// Map viewport width to properties
const scale = gsap.utils.mapRange(
  320, 1920,
  0.8, 1.2,
  window.innerWidth
)

gsap.to('.box', {
  scale: scale,
  duration: 0.5
})
```

## Utility in Animations

### Using in Tween

```javascript
gsap.to('.box', {
  x: gsap.utils.random(-100, 100),
  y: gsap.utils.random(-100, 100),
  rotation: gsap.utils.random(0, 360),
  backgroundColor: gsap.utils.interpolate('red', 'blue', Math.random()),
  duration: 1
})
```

### Using in ScrollTrigger

```javascript
ScrollTrigger.create({
  trigger: '.section',
  start: 'top center',
  end: 'bottom center',
  onUpdate: (self) => {
    const progress = gsap.utils.normalize(0, 1, self.progress)
    const x = gsap.utils.mapRange(0, 1, 0, 500, progress)

    gsap.set('.box', { x })
  }
})
```

### Using in Stagger

```javascript
const items = document.querySelectorAll('.item')

gsap.from(items, {
  opacity: 0,
  x: gsap.utils.distribute(300, items),
  stagger: gsap.utils.pipe(
    (i, total) => i / total,
    (progress) => progress * 0.5  // 0.5s total stagger
  ),
  duration: 1
})
```

## Performance Tips

### Cache Utilities

```javascript
// Cache frequently used functions
const clamp100 = gsap.utils.clamp(0, 100)
const mapRange100to500 = gsap.utils.mapRange(0, 100, 0, 500)

// Use cached functions
gsap.to('.box', {
  x: mapRange100to500(clamp100(value)),
  duration: 0.5
})
```

### Batch Operations

```javascript
// Batch utility calls
const values = [10, 20, 30, 40, 50]
const processed = values.map(val =>
  gsap.utils.pipe(
    gsap.utils.clamp(0, 100),
    (v) => v * 2
  )(val)
)
```

## Common Mistakes

### 1. Not Clamping Values

```javascript
// ❌ Values can go outside range
gsap.to('.box', {
  x: gsap.utils.mapRange(0, 100, 0, 500, value)  // value > 100 causes issues
})

// ✅ Clamp first
gsap.to('.box', {
  x: gsap.utils.mapRange(0, 100, 0, 500, gsap.utils.clamp(0, 100, value)),
  duration: 0.5
})
```

### 2. Random In Loops

```javascript
// ❌ Generates new random every frame
gsap.to('.box', {
  x: gsap.utils.random(0, 100),  // Not how it works!
  duration: 1
})

// ✅ Evaluate once
const randomX = gsap.utils.random(0, 100)
gsap.to('.box', {
  x: randomX,
  duration: 1
})
```

### 3. Not Using Pipes

```javascript
// ❌ Multiple operations, hard to read
const result = gsap.utils.mapRange(0, 100, 0, 500, gsap.utils.clamp(0, 50, value))

// ✅ Use pipe for clarity
const process = gsap.utils.pipe(
  gsap.utils.clamp(0, 50),
  gsap.utils.mapRange(0, 50, 0, 500)
)
const result = process(value)
```

## Best Practices

1. **Use clamp for validation** - Ensure values stay in range
2. **Leverage pipe for chaining** - Complex transformations become clear
3. **Cache utility functions** - Better performance if reused
4. **Use mapRange for responsive** - Map viewport to properties
5. **Distribute for staggers** - Even spacing across elements
6. **Interpolate for colors** - Smooth color transitions
7. **Random for variety** - Add randomness to animations
8. **Normalize for progress** - Convert to 0-1 range

## Quick Reference

| Utility | Description |
|----------|-------------|
| `clamp(min, max, value)` | Clamp value between min and max |
| `mapRange(inMin, inMax, outMin, outMax, value)` | Map value to new range |
| `normalize(min, max, value)` | Convert to 0-1 range |
| `toArray(value)` | Convert to array |
| `random(min, max, increment)` | Random number or array item |
| `wrap(min, max, value)` | Wrap value in range |
| `distribute(value, elements)` | Distribute value across elements |
| `interpolate(start, end, progress)` | Interpolate between values |
| `pipe(...functions)` | Chain multiple functions |
| `getUnit(value)` | Extract unit from value |
| `unitize(value, unit)` | Add unit to value |
| `snap(increment, value)` | Snap to nearest increment |
| `shuffle(array)` | Shuffle array randomly |
| `splitColor(color)` | Split color to RGBA |
| `checkPrefix(element, property)` | Get vendor prefix |
| `selector(scope)` | Create scoped selector |
