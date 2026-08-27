# GSAP Stagger

## Basic Stagger

```javascript
// Simple numeric stagger (delay between each)
gsap.to('.box', {
  x: 100,
  stagger: 0.1  // 0.1 second delay between each
})

// Negative stagger (reverse order)
gsap.to('.box', {
  x: 100,
  stagger: -0.1
})
```

## Stagger Object Configuration

```javascript
gsap.to('.box', {
  x: 100,
  stagger: {
    each: 0.1,          // delay between each
    // OR
    amount: 1,          // total stagger time distributed

    from: 'start',      // starting position
    ease: 'power2.in',  // stagger easing
    grid: 'auto',       // for grid layouts
    axis: null          // 'x', 'y', or null
  }
})
```

### each vs amount

```javascript
// 'each': fixed delay between elements
gsap.to('.box', {
  x: 100,
  stagger: { each: 0.1 }  // 10 items = 0.9s total stagger
})

// 'amount': total time divided among elements
gsap.to('.box', {
  x: 100,
  stagger: { amount: 1 }  // 10 items = 0.1s each
})
```

### from Options

```javascript
// Keywords
stagger: { from: 'start' }    // default - first to last
stagger: { from: 'end' }      // last to first
stagger: { from: 'center' }   // center outward
stagger: { from: 'edges' }    // edges inward
stagger: { from: 'random' }   // random order

// Index number
stagger: { from: 5 }          // start from 6th element (0-indexed)

// Array [row, column] for grids
stagger: { from: [2, 3], grid: [5, 8] }  // from row 2, col 3
```

### Stagger Easing

```javascript
// Easing affects the stagger timing distribution
gsap.to('.box', {
  x: 100,
  stagger: {
    each: 0.1,
    ease: 'power2.in'  // later elements have shorter delays
  }
})

// Common patterns
ease: 'none'         // equal distribution (default)
ease: 'power2.in'    // accelerating delays
ease: 'power2.out'   // decelerating delays
ease: 'power2.inOut' // slow-fast-slow
```

## Grid Stagger

For elements in a grid layout:

```javascript
// Auto-detect grid
gsap.to('.grid-item', {
  scale: 0,
  stagger: {
    each: 0.05,
    grid: 'auto',      // detects based on element positions
    from: 'center'
  }
})

// Explicit grid dimensions
gsap.to('.grid-item', {
  opacity: 0,
  stagger: {
    each: 0.1,
    grid: [5, 8],      // 5 rows, 8 columns
    from: 'center',
    axis: 'x'          // only consider horizontal distance
  }
})

// From specific cell
gsap.to('.grid-item', {
  y: 50,
  stagger: {
    each: 0.05,
    grid: [5, 8],
    from: [2, 4]       // row 2, column 4
  }
})
```

### Grid Axis

```javascript
// Stagger based on x-distance only (horizontal wave)
stagger: {
  each: 0.1,
  grid: 'auto',
  from: 'start',
  axis: 'x'
}

// Stagger based on y-distance only (vertical wave)
stagger: {
  each: 0.1,
  grid: 'auto',
  from: 'start',
  axis: 'y'
}

// Both axes (radial - default)
stagger: {
  each: 0.1,
  grid: 'auto',
  from: 'center',
  axis: null  // or omit
}
```

## Function-Based Stagger

For complete control:

```javascript
gsap.to('.box', {
  x: 100,
  stagger: (index, target, list) => {
    // index: element index (0-based)
    // target: the current element
    // list: array of all targets

    return index * 0.1  // same as stagger: 0.1
  }
})

// Complex example
gsap.to('.box', {
  y: 100,
  stagger: (i, target, list) => {
    // Get element's data attribute
    const priority = target.dataset.priority || 1
    return i * 0.1 * priority
  }
})

// Random delays
gsap.to('.box', {
  opacity: 0,
  stagger: () => gsap.utils.random(0, 0.5)
})
```

## Stagger with Callbacks

```javascript
gsap.to('.box', {
  x: 100,
  stagger: {
    each: 0.1,
    onStart: function() {
      // Called when EACH element's tween starts
      console.log('Element started:', this.targets()[0])
    },
    onComplete: function() {
      // Called when EACH element's tween completes
      console.log('Element done:', this.targets()[0])
    }
  }
})
```

## Stagger with Repeat

```javascript
gsap.to('.box', {
  x: 100,
  stagger: {
    each: 0.1,
    repeat: -1,      // each element repeats infinitely
    yoyo: true       // each element yoyos
  }
})
```

## Common Patterns

### Fade In List

```javascript
gsap.from('.list-item', {
  opacity: 0,
  y: 20,
  duration: 0.5,
  stagger: 0.1
})
```

### Grid Reveal from Center

```javascript
gsap.from('.grid-cell', {
  scale: 0,
  opacity: 0,
  duration: 0.4,
  ease: 'back.out(1.7)',
  stagger: {
    each: 0.03,
    grid: 'auto',
    from: 'center'
  }
})
```

### Wave Effect

```javascript
gsap.to('.wave-item', {
  y: -20,
  duration: 0.3,
  ease: 'power1.inOut',
  stagger: {
    each: 0.05,
    repeat: -1,
    yoyo: true
  }
})
```

### Typewriter Effect

```javascript
// Split text into characters first
gsap.from('.char', {
  opacity: 0,
  duration: 0.01,
  stagger: 0.05  // reveals one character at a time
})
```

### Random Scatter

```javascript
gsap.from('.particle', {
  x: 'random(-500, 500)',
  y: 'random(-500, 500)',
  opacity: 0,
  scale: 0,
  duration: 1,
  ease: 'power4.out',
  stagger: {
    each: 0.02,
    from: 'random'
  }
})
```

### Staggered Exit

```javascript
// Elements leave in reverse order
gsap.to('.item', {
  opacity: 0,
  y: -20,
  stagger: {
    each: 0.05,
    from: 'end'
  }
})
```

## Using with distribute()

For advanced distribution:

```javascript
gsap.to('.box', {
  y: gsap.utils.distribute({
    base: 0,
    amount: 200,
    from: 'center',
    grid: 'auto',
    ease: 'power2'
  }),
  stagger: {
    each: 0.05,
    from: 'center',
    grid: 'auto'
  }
})
```
