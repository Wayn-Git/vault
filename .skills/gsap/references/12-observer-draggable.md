# GSAP Observer & Draggable

## Observer Plugin

Unified scroll, touch, and pointer event detection.

### Setup

```javascript
import gsap from 'gsap'
import { Observer } from 'gsap/Observer'

gsap.registerPlugin(Observer)
```

### Basic Usage

```javascript
Observer.create({
  target: window,
  type: 'wheel, touch, pointer',
  onUp: () => previousSlide(),
  onDown: () => nextSlide()
})
```

### Configuration

```javascript
Observer.create({
  // Target element
  target: window,              // or element, selector
  target: '.container',

  // Event types
  type: 'wheel',               // mouse wheel
  type: 'touch',               // touch events
  type: 'pointer',             // pointer/mouse events
  type: 'scroll',              // scroll events
  type: 'wheel, touch',        // multiple

  // Direction callbacks
  onUp: (self) => {},          // scroll/drag up
  onDown: (self) => {},        // scroll/drag down
  onLeft: (self) => {},        // scroll/drag left
  onRight: (self) => {},       // scroll/drag right

  // General callbacks
  onChange: (self) => {},      // any change
  onChangeX: (self) => {},     // horizontal change
  onChangeY: (self) => {},     // vertical change
  onPress: (self) => {},       // press start
  onRelease: (self) => {},     // press end
  onMove: (self) => {},        // movement
  onStop: (self) => {},        // movement stopped
  onHover: (self) => {},       // hover start
  onHoverEnd: (self) => {},    // hover end
  onClick: (self) => {},       // click
  onWheel: (self) => {},       // wheel event
  onDrag: (self) => {},        // dragging
  onDragStart: (self) => {},   // drag start
  onDragEnd: (self) => {},     // drag end

  // Thresholds
  tolerance: 10,               // minimum movement (px)
  wheelSpeed: -1,              // wheel sensitivity (negative = natural)
  dragMinimum: 3,              // minimum drag distance

  // Axis control
  axis: 'y',                   // 'x', 'y', or null (both)
  lockAxis: true,              // lock to initial axis

  // State
  preventDefault: true,        // prevent default behavior
  allowClicks: true,           // allow click events

  // Debounce
  debounce: false,             // disable for every frame
  debounce: true               // batch events (default)
})
```

### Self Object Properties

```javascript
Observer.create({
  onDown: (self) => {
    self.deltaX        // horizontal change
    self.deltaY        // vertical change
    self.velocityX     // horizontal velocity
    self.velocityY     // vertical velocity
    self.event         // original event
    self.isDragging    // is currently dragging
    self.isPressed     // is pressed
    self.startX        // drag start X
    self.startY        // drag start Y
    self.x             // current X
    self.y             // current Y
  }
})
```

### Methods

```javascript
const observer = Observer.create({ ... })

observer.enable()              // enable observer
observer.disable()             // disable observer
observer.kill()                // remove completely

// Get velocity
observer.velocityX
observer.velocityY
observer.getVelocity()         // combined velocity
```

### Common Patterns

#### Full-Page Section Scroll

```javascript
let currentIndex = 0
const sections = gsap.utils.toArray('.section')

Observer.create({
  type: 'wheel, touch, pointer',
  wheelSpeed: -1,
  tolerance: 10,
  preventDefault: true,
  onUp: () => goToSection(currentIndex - 1),
  onDown: () => goToSection(currentIndex + 1)
})

function goToSection(index) {
  index = gsap.utils.clamp(0, sections.length - 1, index)
  if (index !== currentIndex) {
    currentIndex = index
    gsap.to(window, {
      scrollTo: sections[index],
      duration: 1
    })
  }
}
```

#### Custom Scroll Progress

```javascript
let progress = 0

Observer.create({
  target: '.container',
  type: 'wheel, touch',
  onChange: (self) => {
    progress = gsap.utils.clamp(0, 1, progress + self.deltaY * 0.001)
    gsap.to('.progress-bar', { scaleX: progress })
  }
})
```

---

## Draggable Plugin

Make elements draggable with physics.

### Setup

```javascript
import gsap from 'gsap'
import { Draggable } from 'gsap/Draggable'

gsap.registerPlugin(Draggable)
```

### Basic Usage

```javascript
// Make element draggable
Draggable.create('.box')

// With options
Draggable.create('.box', {
  type: 'x,y',
  bounds: '.container'
})
```

### Type Options

```javascript
// Movement type
type: 'x,y'          // both axes (default)
type: 'x'            // horizontal only
type: 'y'            // vertical only
type: 'top,left'     // use top/left instead of transforms
type: 'rotation'     // rotate around center
type: 'scroll'       // scroll the element
type: 'scrollTop'    // vertical scroll only
type: 'scrollLeft'   // horizontal scroll only
```

### Configuration

```javascript
Draggable.create('.box', {
  // Movement
  type: 'x,y',
  bounds: '.container',       // constrain to element
  bounds: { minX: 0, maxX: 500, minY: 0, maxY: 300 },

  // Behavior
  inertia: true,              // momentum on release
  throwProps: true,           // alias for inertia
  edgeResistance: 0.65,       // resistance at bounds edge
  dragResistance: 0,          // resistance during drag
  lockAxis: true,             // lock to initial axis
  allowNativeTouchScrolling: true,
  allowEventDefault: false,

  // Interaction
  trigger: '.handle',         // drag handle
  cursor: 'grab',
  activeCursor: 'grabbing',
  clickableTest: (el) => !el.matches('button'),

  // Grid snapping
  snap: 50,                   // snap to 50px increments
  snap: [0, 100, 200],        // snap to specific values
  snap: {
    x: 50,
    y: 100
  },
  liveSnap: true,             // snap during drag

  // Callbacks
  onPress: function() {},
  onDragStart: function() {},
  onDrag: function() {},
  onDragEnd: function() {},
  onRelease: function() {},
  onClick: function() {},
  onThrowUpdate: function() {},
  onThrowComplete: function() {}
})
```

### Instance Properties

```javascript
const draggable = Draggable.create('.box')[0]

draggable.x                   // current x
draggable.y                   // current y
draggable.rotation            // current rotation
draggable.isDragging          // is dragging
draggable.isPressed           // is pressed
draggable.target              // the element
draggable.vars                // configuration
draggable.maxX                // bounds max X
draggable.minX                // bounds min X
```

### Methods

```javascript
const draggable = Draggable.create('.box')[0]

draggable.enable()            // enable dragging
draggable.disable()           // disable dragging
draggable.kill()              // remove completely
draggable.update()            // recalculate bounds
draggable.startDrag(event)    // start drag programmatically
draggable.endDrag(event)      // end drag programmatically

// Static methods
Draggable.get('.box')         // get Draggable instance
Draggable.hitTest(el1, el2)   // collision detection
Draggable.hitTest(el1, el2, '50%')  // with threshold
```

### Common Patterns

#### Drag with Handle

```javascript
Draggable.create('.modal', {
  trigger: '.modal-header',
  bounds: 'body',
  inertia: true
})
```

#### Rotation Dial

```javascript
Draggable.create('.dial', {
  type: 'rotation',
  inertia: true,
  snap: (value) => Math.round(value / 15) * 15  // snap to 15°
})
```

#### Scrollable List

```javascript
Draggable.create('.list', {
  type: 'scrollTop',
  inertia: true,
  edgeResistance: 0.8
})
```

#### Sortable List

```javascript
Draggable.create('.item', {
  type: 'y',
  bounds: '.list',
  onDrag: function() {
    // Reorder based on position
    const items = gsap.utils.toArray('.item')
    items.sort((a, b) => {
      return gsap.getProperty(a, 'y') - gsap.getProperty(b, 'y')
    })
    // Update visual order
  }
})
```

#### Drag and Drop

```javascript
Draggable.create('.draggable', {
  type: 'x,y',
  onDragEnd: function() {
    const draggable = this
    const dropZones = document.querySelectorAll('.drop-zone')

    dropZones.forEach(zone => {
      if (Draggable.hitTest(draggable.target, zone, '50%')) {
        // Dropped in zone
        zone.appendChild(draggable.target)
        gsap.set(draggable.target, { x: 0, y: 0 })
        draggable.update()
      }
    })
  }
})
```

#### Slider

```javascript
const slider = Draggable.create('.slider-thumb', {
  type: 'x',
  bounds: '.slider-track',
  onDrag: function() {
    const progress = this.x / this.maxX
    updateValue(progress)
  }
})[0]

// Set programmatically
gsap.set('.slider-thumb', { x: slider.maxX * 0.5 })
slider.update()
```

### InertiaPlugin (for physics)

```javascript
import { InertiaPlugin } from 'gsap/InertiaPlugin'
gsap.registerPlugin(InertiaPlugin)

Draggable.create('.box', {
  inertia: true,
  throwResistance: 1000,  // higher = slower deceleration
  maxDuration: 2,         // max throw duration
  minDuration: 0.2        // min throw duration
})
```

### Collision Detection

```javascript
Draggable.create('.box', {
  onDrag: function() {
    const obstacles = document.querySelectorAll('.obstacle')
    obstacles.forEach(obstacle => {
      if (Draggable.hitTest(this.target, obstacle)) {
        // Collision detected
        gsap.to(obstacle, { backgroundColor: 'red' })
      }
    })
  }
})
```
