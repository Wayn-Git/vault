# GSAP Utility Methods

## gsap.utils.toArray()

Convert various inputs to arrays:

```javascript
// Selector string
const boxes = gsap.utils.toArray('.box')

// NodeList
const items = gsap.utils.toArray(document.querySelectorAll('.item'))

// Single element
const single = gsap.utils.toArray(element)  // [element]

// jQuery object
const $els = gsap.utils.toArray($('.box'))

// Already an array (returns copy)
const copy = gsap.utils.toArray([a, b, c])
```

## gsap.utils.selector()

Create scoped selector function:

```javascript
// Scope to container
const container = document.querySelector('.container')
const q = gsap.utils.selector(container)

// Now queries are scoped
gsap.to(q('.box'), { x: 100 })    // only .box inside container
gsap.to(q('.title'), { y: 20 })   // only .title inside container

// React pattern
function Component() {
  const el = useRef()
  const q = gsap.utils.selector(el)

  useGSAP(() => {
    gsap.to(q('.box'), { x: 100 })
  }, { scope: el })

  return <div ref={el}><div className="box" /></div>
}
```

## gsap.utils.clamp()

Constrain values to a range:

```javascript
// Create clamp function
const clamp = gsap.utils.clamp(0, 100)

clamp(-20)   // 0
clamp(50)    // 50
clamp(150)   // 100

// Direct usage
gsap.utils.clamp(0, 100, 150)  // 100
```

## gsap.utils.mapRange()

Map value from one range to another:

```javascript
// Create mapper function
const mapper = gsap.utils.mapRange(0, 100, 0, 500)

mapper(0)    // 0
mapper(50)   // 250
mapper(100)  // 500

// Direct usage
gsap.utils.mapRange(0, 100, 0, 500, 50)  // 250

// Example: scroll progress to rotation
window.addEventListener('scroll', () => {
  const progress = window.scrollY / (document.body.scrollHeight - window.innerHeight)
  const rotation = gsap.utils.mapRange(0, 1, 0, 360, progress)
})
```

## gsap.utils.normalize()

Convert value to 0-1 range:

```javascript
// Create normalizer
const normalize = gsap.utils.normalize(100, 500)

normalize(100)  // 0
normalize(300)  // 0.5
normalize(500)  // 1

// Direct usage
gsap.utils.normalize(100, 500, 300)  // 0.5
```

## gsap.utils.interpolate()

Interpolate between values:

```javascript
// Numbers
const lerp = gsap.utils.interpolate(0, 100)
lerp(0.5)    // 50

// Colors
const colorLerp = gsap.utils.interpolate('red', 'blue')
colorLerp(0.5)  // "rgba(128,0,128,1)"

// Objects
const objLerp = gsap.utils.interpolate(
  { x: 0, y: 0 },
  { x: 100, y: 200 }
)
objLerp(0.5)  // { x: 50, y: 100 }

// Arrays (progresses through)
const arrayLerp = gsap.utils.interpolate([0, 100, 50, 200])
arrayLerp(0.33)  // ~100
arrayLerp(0.66)  // ~50

// Direct usage
gsap.utils.interpolate(0, 100, 0.5)  // 50
```

## gsap.utils.snap()

Snap values to increments or array:

```javascript
// Snap to increment
const snap = gsap.utils.snap(10)
snap(23)   // 20
snap(27)   // 30

// Snap to array values
const snapArray = gsap.utils.snap([0, 25, 50, 100])
snapArray(30)   // 25
snapArray(80)   // 100

// Snap object properties
const snapObj = gsap.utils.snap({
  values: [0, 25, 50, 100],
  radius: 10  // only snap if within 10 of a value
})
snapObj(22)   // 25
snapObj(15)   // 15 (not within radius of any value)

// Direct usage
gsap.utils.snap(10, 23)  // 20
```

## gsap.utils.wrap()

Wrap values around a range:

```javascript
// Wrap in range
const wrap = gsap.utils.wrap(0, 100)
wrap(150)   // 50
wrap(-20)   // 80
wrap(100)   // 0

// Wrap through array
const wrapArray = gsap.utils.wrap(['a', 'b', 'c'])
wrapArray(0)   // 'a'
wrapArray(3)   // 'a' (wraps)
wrapArray(4)   // 'b'
wrapArray(-1)  // 'c'

// Useful for infinite galleries
const getItem = gsap.utils.wrap(items)
```

## gsap.utils.wrapYoyo()

Wrap with yoyo (ping-pong):

```javascript
const wrapYoyo = gsap.utils.wrapYoyo(0, 100)
wrapYoyo(50)   // 50
wrapYoyo(150)  // 50 (bounced back)
wrapYoyo(200)  // 0

// With array
const wrapYoyoArray = gsap.utils.wrapYoyo([0, 1, 2, 3])
wrapYoyoArray(5)  // 1 (bounced: 0,1,2,3,2,1,0,1...)
```

## gsap.utils.pipe()

Chain utility functions:

```javascript
// Create processing pipeline
const process = gsap.utils.pipe(
  gsap.utils.clamp(0, 100),       // first: clamp
  gsap.utils.normalize(0, 100),   // then: normalize
  gsap.utils.interpolate('red', 'blue')  // then: interpolate
)

process(-50)   // "red" (clamped to 0, normalized to 0)
process(50)    // purple (normalized to 0.5)
process(200)   // "blue" (clamped to 100, normalized to 1)

// Complex transformation
const transformer = gsap.utils.pipe(
  gsap.utils.clamp(0, 100),
  gsap.utils.mapRange(0, 100, 0, window.innerWidth),
  gsap.utils.snap(20)
)
```

## gsap.utils.random()

Generate random values:

```javascript
// Random in range
gsap.utils.random(0, 100)         // random float
gsap.utils.random(0, 100, true)   // random integer
gsap.utils.random(0, 100, 5)      // snapped to nearest 5

// Random from array
gsap.utils.random(['red', 'green', 'blue'])

// Create reusable function
const randomX = gsap.utils.random(-100, 100, true)
randomX()  // different each call

// In animations
gsap.to('.box', {
  x: 'random(-200, 200)',
  y: 'random(-100, 100)',
  rotation: 'random(-180, 180)'
})

// Random array selection
gsap.to('.box', {
  backgroundColor: 'random([red, green, blue, yellow])'
})
```

## gsap.utils.shuffle()

Randomize array order:

```javascript
const arr = [1, 2, 3, 4, 5]
gsap.utils.shuffle(arr)  // mutates and returns array

// Copy first to preserve original
const shuffled = gsap.utils.shuffle([...arr])
```

## gsap.utils.distribute()

Create distributed values:

```javascript
// Linear distribution
const dist = gsap.utils.distribute({
  base: 0,      // starting value
  amount: 100   // total range
})

// For 5 elements: 0, 25, 50, 75, 100
[0,1,2,3,4].map(i => dist(i, null, [0,1,2,3,4]))

// Advanced options
gsap.utils.distribute({
  base: 0,
  amount: 100,
  from: 'center',   // or 'end', 'edges', index, [row,col]
  grid: [3, 3],     // for grid layouts
  axis: 'x',        // 'x', 'y', or null
  ease: 'power2'    // distribution easing
})

// Use in animation
gsap.to('.box', {
  y: gsap.utils.distribute({
    base: -50,
    amount: 100,
    from: 'center'
  })
})
```

## gsap.utils.getUnit()

Extract unit from value:

```javascript
gsap.utils.getUnit('100px')   // 'px'
gsap.utils.getUnit('50%')     // '%'
gsap.utils.getUnit('2rem')    // 'rem'
gsap.utils.getUnit(100)       // ''
```

## gsap.utils.unitize()

Add unit to function results:

```javascript
// Wrap function to add unit
const withPx = gsap.utils.unitize(gsap.utils.clamp(0, 100), 'px')
withPx(50)   // '50px'
withPx(150)  // '100px'

// With mapRange
const toPercent = gsap.utils.unitize(
  gsap.utils.mapRange(0, 100, 0, 100),
  '%'
)
toPercent(50)  // '50%'
```

## gsap.utils.splitColor()

Parse color into components:

```javascript
gsap.utils.splitColor('rgb(255, 128, 0)')
// [255, 128, 0]

gsap.utils.splitColor('#ff8000')
// [255, 128, 0]

gsap.utils.splitColor('rgba(255, 128, 0, 0.5)')
// [255, 128, 0, 0.5]

// HSL output
gsap.utils.splitColor('hsl(30, 100%, 50%)', true)
// [30, 100, 50] (hue, saturation, lightness)
```

## Practical Examples

### Clamped Scroll Progress

```javascript
const clampProgress = gsap.utils.clamp(0, 1)

window.addEventListener('scroll', () => {
  const raw = window.scrollY / 1000
  const progress = clampProgress(raw)
  gsap.set('.progress-bar', { scaleX: progress })
})
```

### Color Based on Progress

```javascript
const getColor = gsap.utils.pipe(
  gsap.utils.clamp(0, 1),
  gsap.utils.interpolate('#ff0000', '#00ff00')
)

// Use with scroll
ScrollTrigger.create({
  onUpdate: (self) => {
    document.body.style.backgroundColor = getColor(self.progress)
  }
})
```

### Infinite Loop Index

```javascript
const items = document.querySelectorAll('.item')
const getIndex = gsap.utils.wrap(0, items.length)

let current = 0
function next() {
  current = getIndex(current + 1)
  // current wraps: 0, 1, 2, 0, 1, 2, ...
}
```
