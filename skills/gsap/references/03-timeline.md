# GSAP Timeline

## Creating Timelines

```javascript
// Basic timeline
const tl = gsap.timeline()

// With options
const tl = gsap.timeline({
  paused: true,
  repeat: -1,
  yoyo: true,
  defaults: { duration: 1, ease: 'power2.out' }
})

// With callbacks
const tl = gsap.timeline({
  onStart: () => console.log('Started'),
  onUpdate: () => console.log('Progress:', tl.progress()),
  onComplete: () => console.log('Complete'),
  onRepeat: () => console.log('Repeated')
})
```

## Adding Tweens

### Chained Methods

```javascript
const tl = gsap.timeline()

tl.to('.box1', { x: 100, duration: 1 })
  .to('.box2', { x: 100, duration: 1 })
  .to('.box3', { x: 100, duration: 1 })

// All methods return the timeline
tl.from('.box', { opacity: 0 })
  .fromTo('.box', { scale: 0 }, { scale: 1 })
  .set('.box', { visibility: 'visible' })
```

### Using add()

```javascript
// Add existing tween
const tween = gsap.to('.box', { x: 100 })
tl.add(tween)

// Add function
tl.add(() => console.log('Reached this point'))

// Add label
tl.add('myLabel')

// Add nested timeline
const childTl = gsap.timeline()
childTl.to('.child', { x: 100 })
tl.add(childTl)
```

## Position Parameter

The position parameter controls WHERE in the timeline a tween is placed.

### Absolute Time

```javascript
tl.to('.box', { x: 100 }, 0)     // at 0 seconds (start)
tl.to('.box', { x: 100 }, 2)     // at 2 seconds
tl.to('.box', { x: 100 }, 0.5)   // at 0.5 seconds
```

### Relative to End

```javascript
tl.to('.box', { x: 100 })              // sequential (at end)
tl.to('.box', { y: 100 }, '+=0.5')     // 0.5s after end
tl.to('.box', { z: 100 }, '-=0.5')     // 0.5s before end (overlap)
```

### Relative to Previous Animation

```javascript
tl.to('.box1', { x: 100 })
tl.to('.box2', { x: 100 }, '<')        // same START as previous
tl.to('.box3', { x: 100 }, '>')        // same END as previous

tl.to('.box', { x: 100 }, '<0.5')      // 0.5s after prev START
tl.to('.box', { x: 100 }, '<-0.2')     // 0.2s before prev START
tl.to('.box', { x: 100 }, '>-0.5')     // 0.5s before prev END
```

### Labels

```javascript
tl.addLabel('intro')
tl.to('.box1', { x: 100 })
tl.addLabel('middle')
tl.to('.box2', { x: 100 })
tl.addLabel('end')

// Position at label
tl.to('.box', { y: 50 }, 'intro')
tl.to('.box', { y: 50 }, 'middle+=0.5')
tl.to('.box', { y: 50 }, 'end-=1')
```

### Percentage-Based (v3.7+)

```javascript
// Percentage of inserting animation's duration
tl.to('.box', { x: 100 }, '-=25%')   // overlap by 25%
tl.to('.box', { x: 100 }, '+=50%')   // gap of 50%

// Percentage of previous animation's duration
tl.to('.box', { x: 100 }, '<25%')    // 25% into previous
tl.to('.box', { x: 100 }, '>-75%')   // 75% before prev end
```

## Position Examples

```javascript
// All start at same time
tl.to('.box1', { x: 100 })
  .to('.box2', { y: 100 }, '<')
  .to('.box3', { rotation: 360 }, '<')

// Staggered overlap
tl.to('.box1', { x: 100, duration: 1 })
  .to('.box2', { x: 100, duration: 1 }, '-=0.5')
  .to('.box3', { x: 100, duration: 1 }, '-=0.5')

// Synchronized ending
tl.to('.box1', { x: 100, duration: 2 })
  .to('.box2', { y: 100, duration: 1 }, '>-1')  // ends with box1
```

## Timeline Control

```javascript
const tl = gsap.timeline({ paused: true })

// Playback
tl.play()
tl.pause()
tl.resume()
tl.reverse()
tl.restart()

// Position
tl.seek(2)              // jump to 2 seconds
tl.seek('myLabel')      // jump to label
tl.progress(0.5)        // jump to 50%
tl.time(1.5)            // set time

// Speed
tl.timeScale(2)         // 2x speed
tl.timeScale(0.5)       // 0.5x speed

// Direction
tl.reversed(true)       // set reversed state
tl.reversed(!tl.reversed())  // toggle

// State queries
tl.isActive()           // currently animating?
tl.progress()           // 0-1 progress
tl.time()               // current time
tl.duration()           // total duration
tl.totalDuration()      // including repeats
```

## Timeline Defaults

```javascript
const tl = gsap.timeline({
  defaults: {
    duration: 1,
    ease: 'power2.out'
  }
})

tl.to('.box1', { x: 100 })           // uses defaults
  .to('.box2', { x: 100 })           // uses defaults
  .to('.box3', { x: 100, duration: 2 })  // overrides duration
```

## Nested Timelines

```javascript
function createIntro() {
  const tl = gsap.timeline()
  tl.from('.logo', { opacity: 0 })
    .from('.tagline', { y: 20 })
  return tl
}

function createMain() {
  const tl = gsap.timeline()
  tl.from('.content', { opacity: 0 })
    .from('.sidebar', { x: -100 })
  return tl
}

// Master timeline
const master = gsap.timeline()
master.add(createIntro())
       .add(createMain(), '+=0.5')
       .add('endScene')

// Control entire sequence
master.play()
master.seek('endScene')
```

## Repeat and Yoyo

```javascript
const tl = gsap.timeline({
  repeat: 3,          // repeat 3 times (4 total plays)
  repeat: -1,         // infinite
  repeatDelay: 0.5,   // pause between repeats
  yoyo: true          // alternate direction on repeat
})

// Individual tweens can also repeat
tl.to('.box', {
  rotation: 360,
  repeat: -1,
  ease: 'none'
})
```

## Adding Callbacks at Positions

```javascript
tl.to('.box', { x: 100 })
  .call(() => console.log('Box moved'))
  .to('.box', { y: 100 })
  .call(myFunction, [arg1, arg2], 'myLabel')  // at label with args
```

## Clear and Kill

```javascript
// Remove all tweens
tl.clear()

// Kill timeline completely
tl.kill()

// Kill from specific time
tl.kill(null, 2)  // kill animations after 2s
```

## Common Patterns

### Sequenced Intro

```javascript
const tl = gsap.timeline({ defaults: { duration: 0.5 } })

tl.from('.header', { y: -100, opacity: 0 })
  .from('.nav-item', { y: -20, opacity: 0, stagger: 0.1 }, '-=0.3')
  .from('.hero-title', { y: 30, opacity: 0 }, '-=0.2')
  .from('.hero-subtitle', { y: 20, opacity: 0 }, '-=0.2')
  .from('.cta-button', { scale: 0 }, '-=0.1')
```

### Toggle Animation

```javascript
const tl = gsap.timeline({ paused: true })

tl.to('.menu', { x: 0, duration: 0.3 })
  .from('.menu-item', { x: -20, opacity: 0, stagger: 0.05 }, '-=0.1')

// Toggle
menuButton.addEventListener('click', () => {
  tl.reversed() ? tl.play() : tl.reverse()
})
```

### Scrubbed Timeline

```javascript
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: '.container',
    start: 'top top',
    end: '+=3000',
    scrub: true,
    pin: true
  }
})

tl.to('.panel1', { xPercent: -100 })
  .to('.panel2', { xPercent: -100 })
  .to('.panel3', { xPercent: -100 })
```
