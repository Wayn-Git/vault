# GSAP React Integration

## Setup

```bash
npm install gsap @gsap/react
```

```javascript
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

// Register once (typically in main entry file)
gsap.registerPlugin(useGSAP)
```

## useGSAP Hook

The official hook for GSAP in React. Handles cleanup automatically.

### Basic Usage

```javascript
import { useRef } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'

function Component() {
  const container = useRef()

  useGSAP(() => {
    gsap.to('.box', { x: 200, duration: 1 })
  }, { scope: container })

  return (
    <div ref={container}>
      <div className="box">Animated</div>
    </div>
  )
}
```

### With Dependencies

```javascript
function Component({ isActive }) {
  const container = useRef()

  useGSAP(() => {
    if (isActive) {
      gsap.to('.box', { x: 200 })
    }
  }, { scope: container, dependencies: [isActive] })

  return <div ref={container}><div className="box" /></div>
}
```

### Revert on Update

```javascript
useGSAP(() => {
  gsap.to('.box', { x: position })
}, {
  scope: container,
  dependencies: [position],
  revertOnUpdate: true  // cleans up before re-running
})
```

## Configuration Options

```javascript
useGSAP(callback, {
  // Scope selector queries to this element
  scope: containerRef,

  // Dependencies array (like useEffect)
  dependencies: [value1, value2],

  // Revert animations when dependencies change
  revertOnUpdate: true
})

// Or just pass dependency array
useGSAP(() => { ... }, [dep1, dep2])
```

## Context-Safe Animations

Animations created AFTER the hook runs (event handlers, timeouts) must be wrapped:

### Using contextSafe

```javascript
function Component() {
  const container = useRef()
  const { contextSafe } = useGSAP({ scope: container })

  // Wrap event handler
  const handleClick = contextSafe(() => {
    gsap.to('.box', { rotation: 360 })
  })

  return (
    <div ref={container}>
      <div className="box" />
      <button onClick={handleClick}>Animate</button>
    </div>
  )
}
```

### From Hook Callback

```javascript
function Component() {
  const container = useRef()
  const boxRef = useRef()

  useGSAP((context, contextSafe) => {
    // Direct animation (automatically tracked)
    gsap.to(boxRef.current, { x: 100 })

    // Event listener with contextSafe
    const handleClick = contextSafe(() => {
      gsap.to(boxRef.current, { rotation: 360 })
    })

    boxRef.current.addEventListener('click', handleClick)

    // Cleanup function
    return () => {
      boxRef.current.removeEventListener('click', handleClick)
    }
  }, { scope: container })

  return (
    <div ref={container}>
      <div ref={boxRef} className="box" />
    </div>
  )
}
```

## Common Patterns

### Initial Animation

```javascript
function FadeIn({ children }) {
  const container = useRef()

  useGSAP(() => {
    gsap.from('.child', {
      opacity: 0,
      y: 20,
      stagger: 0.1
    })
  }, { scope: container })

  return (
    <div ref={container}>
      {React.Children.map(children, child => (
        <div className="child">{child}</div>
      ))}
    </div>
  )
}
```

### Timeline with Controls

```javascript
function AnimatedComponent() {
  const container = useRef()
  const tl = useRef()

  useGSAP(() => {
    tl.current = gsap.timeline({ paused: true })
      .to('.box', { x: 200 })
      .to('.box', { rotation: 360 })
  }, { scope: container })

  const play = () => tl.current.play()
  const reverse = () => tl.current.reverse()

  return (
    <div ref={container}>
      <div className="box" />
      <button onClick={play}>Play</button>
      <button onClick={reverse}>Reverse</button>
    </div>
  )
}
```

### Scroll Animation

```javascript
import { ScrollTrigger } from 'gsap/ScrollTrigger'

gsap.registerPlugin(ScrollTrigger)

function ScrollComponent() {
  const container = useRef()

  useGSAP(() => {
    gsap.to('.box', {
      x: 500,
      scrollTrigger: {
        trigger: '.box',
        start: 'top 80%',
        end: 'top 20%',
        scrub: true
      }
    })
  }, { scope: container })

  return (
    <div ref={container}>
      <div className="spacer" style={{ height: '100vh' }} />
      <div className="box" />
      <div className="spacer" style={{ height: '100vh' }} />
    </div>
  )
}
```

### State-Driven Animation

```javascript
function ToggleBox() {
  const container = useRef()
  const [isOpen, setIsOpen] = useState(false)

  useGSAP(() => {
    gsap.to('.box', {
      height: isOpen ? 200 : 0,
      duration: 0.3
    })
  }, { scope: container, dependencies: [isOpen] })

  return (
    <div ref={container}>
      <button onClick={() => setIsOpen(!isOpen)}>Toggle</button>
      <div className="box" />
    </div>
  )
}
```

### Multiple Refs

```javascript
function MultiElement() {
  const container = useRef()
  const boxRef = useRef()
  const circleRef = useRef()

  useGSAP(() => {
    const tl = gsap.timeline()
    tl.to(boxRef.current, { x: 100 })
      .to(circleRef.current, { y: 50 })
  }, { scope: container })

  return (
    <div ref={container}>
      <div ref={boxRef} className="box" />
      <div ref={circleRef} className="circle" />
    </div>
  )
}
```

## Without useGSAP (Manual Context)

If you can't use the hook:

```javascript
import { useRef, useEffect, useLayoutEffect } from 'react'
import gsap from 'gsap'

function Component() {
  const container = useRef()

  // Prefer useLayoutEffect for animations
  useLayoutEffect(() => {
    const ctx = gsap.context(() => {
      gsap.to('.box', { x: 200 })
    }, container)

    return () => ctx.revert()  // cleanup
  }, [])

  return <div ref={container}><div className="box" /></div>
}
```

## Server-Side Rendering (SSR)

useGSAP handles SSR automatically (uses useEffect when window undefined).

```javascript
// Next.js App Router - add client directive
'use client'

import { useGSAP } from '@gsap/react'

function Component() {
  useGSAP(() => {
    // Safe - won't run on server
    gsap.to('.box', { x: 200 })
  })
}
```

## Plugin Registration

```javascript
// _app.js or layout.js (once)
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { Flip } from 'gsap/Flip'

gsap.registerPlugin(useGSAP, ScrollTrigger, Flip)
```

## Common Mistakes

### Missing Scope

```javascript
// ❌ Affects ALL .box elements on page
useGSAP(() => {
  gsap.to('.box', { x: 200 })
})

// ✅ Scoped to container
useGSAP(() => {
  gsap.to('.box', { x: 200 })
}, { scope: containerRef })
```

### Animations in Event Handlers

```javascript
// ❌ Not cleaned up properly
const handleClick = () => {
  gsap.to('.box', { rotation: 360 })
}

// ✅ Wrapped with contextSafe
const { contextSafe } = useGSAP({ scope: containerRef })
const handleClick = contextSafe(() => {
  gsap.to('.box', { rotation: 360 })
})
```

### Missing Dependencies

```javascript
// ❌ Animation won't update when targetX changes
useGSAP(() => {
  gsap.to('.box', { x: targetX })
}, { scope: containerRef })

// ✅ Include in dependencies
useGSAP(() => {
  gsap.to('.box', { x: targetX })
}, { scope: containerRef, dependencies: [targetX] })
```

### Animating Before Mount

```javascript
// ❌ Element might not exist
useEffect(() => {
  gsap.to('.box', { x: 200 })
}, [])

// ✅ useGSAP waits for DOM
useGSAP(() => {
  gsap.to('.box', { x: 200 })
}, { scope: containerRef })
```
