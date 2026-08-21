# GSAP ScrollTrigger

## Setup

```javascript
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)
```

## Basic Usage

### Simplest Form

```javascript
// Trigger when element enters viewport
gsap.to('.box', {
  x: 500,
  scrollTrigger: '.box'  // element is the trigger
})
```

### With Configuration

```javascript
gsap.to('.box', {
  x: 500,
  scrollTrigger: {
    trigger: '.box',
    start: 'top 80%',   // trigger top hits viewport 80%
    end: 'top 20%',
    markers: true       // visual debugging
  }
})
```

## Start and End Positions

Format: `"[trigger position] [scroller position]"`

```javascript
// Keywords: top, center, bottom, left, right
start: 'top center'      // trigger top hits viewport center
start: 'center center'   // trigger center hits viewport center
start: 'bottom top'      // trigger bottom hits viewport top

// Percentages
start: 'top 80%'         // trigger top hits viewport 80% down
start: '20% 50%'         // trigger 20% hits viewport 50%

// Pixels
start: 'top+=100 center' // 100px below trigger top
start: 'top center-=50'  // 50px above viewport center

// Relative to trigger height
start: 'top bottom-=10%' // 10% of trigger height above bottom

// End position
end: 'bottom top'        // trigger bottom hits viewport top
end: '+=500'             // 500px after start
end: '+=100%'            // 100% of trigger height after start
```

## Scrub

Link animation progress directly to scroll:

```javascript
gsap.to('.box', {
  x: 500,
  scrollTrigger: {
    trigger: '.section',
    start: 'top top',
    end: 'bottom top',
    scrub: true           // direct 1:1 link
  }
})

// Smoothed scrub
scrub: 0.5    // 0.5 second smoothing
scrub: 1      // 1 second smoothing
scrub: 2      // 2 second smoothing
```

## Pin

Lock element in place during scroll:

```javascript
gsap.to('.panel', {
  x: -500,
  scrollTrigger: {
    trigger: '.container',
    start: 'top top',
    end: '+=1000',        // pin for 1000px of scroll
    pin: true,            // pin the trigger
    scrub: true
  }
})

// Pin a different element
pin: '.header'           // pin .header, not trigger

// Pin options
pinSpacing: true,        // add space (default)
pinSpacing: false,       // no added space
pinSpacing: 'margin',    // use margin instead of padding
pinType: 'transform',    // or 'fixed'
pinReparent: true        // move pinned element to body
```

## Snap

Snap to specific points after scrolling:

```javascript
gsap.to('.box', {
  x: 500,
  scrollTrigger: {
    trigger: '.section',
    snap: 0.2             // snap to 20% increments
  }
})

// Snap to array values
snap: [0, 0.25, 0.5, 0.75, 1]

// Snap to timeline labels
snap: 'labels'

// Advanced snap config
snap: {
  snapTo: 'labels',
  duration: { min: 0.2, max: 0.5 },
  delay: 0.1,
  ease: 'power1.inOut',
  directional: true,     // snap in direction of scroll
  onStart: () => {},
  onComplete: () => {}
}
```

## Toggle Actions

Control tween on enter/leave events:

```javascript
scrollTrigger: {
  trigger: '.box',
  toggleActions: 'play pause resume reset'
  // onEnter onLeave onEnterBack onLeaveBack
}

// Options for each:
// play, pause, resume, reset, restart, complete, reverse, none

// Common patterns
toggleActions: 'play none none none'     // play once on enter
toggleActions: 'play reverse play reverse' // toggle on scroll
toggleActions: 'play complete none none'   // play once, stay at end
toggleActions: 'restart pause resume reset' // restart each time
```

## Toggle Class

Add/remove class based on scroll:

```javascript
scrollTrigger: {
  trigger: '.box',
  toggleClass: 'active'   // adds class on enter
}

// Target different element
toggleClass: {
  targets: '.nav',
  className: 'scrolled'
}

// Multiple classes
toggleClass: 'visible animated'
```

## Callbacks

```javascript
scrollTrigger: {
  trigger: '.box',
  onEnter: (self) => console.log('entered'),
  onLeave: (self) => console.log('left'),
  onEnterBack: (self) => console.log('entered from bottom'),
  onLeaveBack: (self) => console.log('left to top'),
  onUpdate: (self) => {
    console.log('progress:', self.progress)
    console.log('direction:', self.direction)
    console.log('velocity:', self.getVelocity())
  },
  onToggle: (self) => {
    console.log('toggled:', self.isActive)
  },
  onRefresh: (self) => console.log('refreshed'),
  onScrubComplete: () => console.log('scrub done')
}
```

## ScrollTrigger.create()

Standalone trigger without animation:

```javascript
ScrollTrigger.create({
  trigger: '.section',
  start: 'top center',
  end: 'bottom center',
  markers: true,
  onEnter: () => console.log('section visible'),
  onLeave: () => console.log('section hidden')
})

// Returns ScrollTrigger instance
const st = ScrollTrigger.create({ ... })
st.kill()
```

## Timeline with ScrollTrigger

```javascript
const tl = gsap.timeline({
  scrollTrigger: {
    trigger: '.container',
    start: 'top top',
    end: '+=3000',
    pin: true,
    scrub: 1,
    snap: 'labels'
  }
})

tl.addLabel('start')
  .to('.box1', { x: 500 })
  .addLabel('middle')
  .to('.box2', { x: 500 })
  .addLabel('end')
```

## Static Methods

```javascript
// Refresh all triggers (after layout changes)
ScrollTrigger.refresh()

// Get all instances
ScrollTrigger.getAll()

// Get by ID
const st = ScrollTrigger.getById('myTrigger')

// Kill all
ScrollTrigger.killAll()

// Batch create
ScrollTrigger.batch('.box', {
  onEnter: (elements) => {
    gsap.to(elements, { opacity: 1, stagger: 0.1 })
  }
})

// Save/restore scroll position
ScrollTrigger.saveStyles('.box')
ScrollTrigger.clearScrollMemory()

// Check if scrolling
ScrollTrigger.isScrolling()

// Sort triggers
ScrollTrigger.sort()
```

## Match Media

Responsive ScrollTriggers:

```javascript
ScrollTrigger.matchMedia({
  // Desktop
  '(min-width: 800px)': function() {
    gsap.to('.box', {
      x: 500,
      scrollTrigger: {
        trigger: '.box',
        scrub: true
      }
    })
  },

  // Mobile
  '(max-width: 799px)': function() {
    gsap.to('.box', {
      y: 100,
      scrollTrigger: {
        trigger: '.box',
        scrub: true
      }
    })
  },

  // All sizes
  'all': function() {
    // Always active
  }
})
```

## Horizontal Scrolling

```javascript
// Container-based horizontal scroll
const sections = gsap.utils.toArray('.panel')

gsap.to(sections, {
  xPercent: -100 * (sections.length - 1),
  ease: 'none',
  scrollTrigger: {
    trigger: '.container',
    pin: true,
    scrub: 1,
    snap: 1 / (sections.length - 1),
    end: () => '+=' + document.querySelector('.container').offsetWidth
  }
})

// Animate within horizontal scroll (containerAnimation)
const scrollTween = gsap.to('.container', {
  x: -2000,
  ease: 'none'
})

gsap.to('.box', {
  y: 100,
  scrollTrigger: {
    trigger: '.box',
    containerAnimation: scrollTween,  // links to horizontal scroll
    start: 'left center',
    end: 'right center',
    scrub: true
  }
})
```

## Common Patterns

### Fade In on Scroll

```javascript
gsap.utils.toArray('.fade-in').forEach(el => {
  gsap.from(el, {
    opacity: 0,
    y: 50,
    duration: 1,
    scrollTrigger: {
      trigger: el,
      start: 'top 80%'
    }
  })
})
```

### Parallax Effect

```javascript
gsap.to('.bg-image', {
  y: -200,
  ease: 'none',
  scrollTrigger: {
    trigger: '.section',
    start: 'top bottom',
    end: 'bottom top',
    scrub: true
  }
})
```

### Progress Bar

```javascript
gsap.to('.progress-bar', {
  scaleX: 1,
  ease: 'none',
  scrollTrigger: {
    trigger: 'body',
    start: 'top top',
    end: 'bottom bottom',
    scrub: 0.3
  }
})
```

### Section Transitions

```javascript
gsap.utils.toArray('.section').forEach((section, i) => {
  ScrollTrigger.create({
    trigger: section,
    start: 'top center',
    end: 'bottom center',
    toggleClass: { targets: section, className: 'active' },
    onEnter: () => updateNav(i),
    onEnterBack: () => updateNav(i)
  })
})
```

## Debugging

```javascript
scrollTrigger: {
  markers: true,                    // show visual markers
  markers: {
    startColor: 'green',
    endColor: 'red',
    fontSize: '12px',
    indent: 20
  },
  id: 'myTrigger'                   // for console logging
}

// Global marker defaults
ScrollTrigger.defaults({
  markers: process.env.NODE_ENV === 'development'
})
```
