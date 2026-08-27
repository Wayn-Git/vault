---
name: gsap-text
description: Use when implementing text animations, text effects, character/word/line animations, text reveals, scrambling effects, or using SplitText, TextPlugin, ScrambleTextPlugin.
---

# GSAP Text Animations

GSAP provides powerful tools for text animation through SplitText, TextPlugin, and ScrambleTextPlugin. Create dramatic reveals, highlights, and interactive text effects.

## Installation

### SplitText (formerly members-only; now included)

```bash
npm install gsap
```

```javascript
import { SplitText } from 'gsap/SplitText'
gsap.registerPlugin(SplitText)
```

### TextPlugin (Free)

```javascript
import { TextPlugin } from 'gsap/TextPlugin'
gsap.registerPlugin(TextPlugin)
```

### ScrambleTextPlugin (formerly members-only; now included)

```javascript
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin'
gsap.registerPlugin(ScrambleTextPlugin)
```

## SplitText

### Basic Setup

```javascript
gsap.registerPlugin(SplitText)

// Create split text
const split = new SplitText('#myText', {
  type: 'chars,words,lines'  // What to split
})

// Access split elements
console.log(split.chars)   // Array of char elements
console.log(split.words)   // Array of word elements
console.log(split.lines)   // Array of line elements
```

### Split Types

```javascript
// Split only characters
const split = new SplitText('#myText', {
  type: 'chars'
})

// Split words
const split = new SplitText('#myText', {
  type: 'words'
})

// Split lines
const split = new SplitText('#myText', {
  type: 'lines'
})

// Multiple types
const split = new SplitText('#myText', {
  type: 'chars,words,lines'
})

// Split all
const split = new SplitText('#myText', {
  type: 'chars,words,lines'
})
```

### Character Animations

```javascript
const split = new SplitText('#heading', { type: 'chars' })

// Reveal characters
gsap.from(split.chars, {
  opacity: 0,
  y: 20,
  stagger: 0.05,
  duration: 0.5,
  ease: 'back.out(1.7)'
})

// Scale and rotate
gsap.from(split.chars, {
  opacity: 0,
  scale: 0,
  rotation: () => gsap.utils.random(-20, 20),
  stagger: 0.03,
  duration: 0.8,
  ease: 'elastic.out(1, 0.5)'
})
```

### Word Animations

```javascript
const split = new SplitText('#paragraph', { type: 'words' })

// Slide in words
gsap.from(split.words, {
  opacity: 0,
  x: -30,
  stagger: 0.1,
  duration: 0.6,
  ease: 'power2.out'
})

// Bounce effect
gsap.from(split.words, {
  opacity: 0,
  y: 50,
  stagger: {
    each: 0.15,
    from: 'center',
    ease: 'back.out(1.7)'
  },
  duration: 0.8
})
```

### Line Animations

```javascript
const split = new SplitText('#paragraph', { type: 'lines' })

// Reveal lines
gsap.from(split.lines, {
  opacity: 0,
  y: 50,
  stagger: 0.2,
  duration: 0.8,
  ease: 'power2.out'
})

// Slide from sides
gsap.from(split.lines, {
  opacity: 0,
  x: (i) => i % 2 === 0 ? -100 : 100,  // Alternate directions
  stagger: 0.15,
  duration: 0.7,
  ease: 'power2.out'
})
```

### Combined Split Animations

```javascript
const split = new SplitText('#text', { type: 'chars,words,lines' })

// Animate characters
gsap.from(split.chars, {
  opacity: 0,
  scale: 0.5,
  stagger: 0.02,
  duration: 0.5,
  ease: 'back.out(1.7)'
})

// Then animate words
gsap.from(split.words, {
  opacity: 0,
  y: 30,
  stagger: 0.1,
  duration: 0.5,
  ease: 'power2.out',
  delay: 0.8
})
```

### Stagger Patterns

```javascript
const split = new SplitText('#text', { type: 'chars' })

// From center
gsap.from(split.chars, {
  opacity: 0,
  scale: 0,
  stagger: {
    each: 0.02,
    from: 'center',
    ease: 'power2.out'
  },
  duration: 0.8
})

// From edges
gsap.from(split.chars, {
  opacity: 0,
  y: 20,
  stagger: {
    each: 0.02,
    from: 'edges',
    ease: 'power2.out'
  },
  duration: 0.6
})

// Grid pattern
gsap.from(split.chars, {
  opacity: 0,
  scale: 0,
  stagger: {
    each: 0.02,
    from: 'center',
    grid: [10, 5],  // 10 columns, 5 rows
    ease: 'power2.out'
  },
  duration: 0.8
})
```

### Responsive Splits

```javascript
// Auto-split on window resize
const split = new SplitText('#text', {
  type: 'chars,words',
  wordsClass: 'word',
  charsClass: 'char'
})

window.addEventListener('resize', () => {
  split.revert()
  new SplitText('#text', {
    type: 'chars,words',
    wordsClass: 'word',
    charsClass: 'char'
  })
})

// Or use matchMedia
const mm = gsap.matchMedia()

mm.add('(min-width: 768px)', () => {
  const split = new SplitText('#text', { type: 'chars' })
  gsap.from(split.chars, { opacity: 0, y: 20, stagger: 0.02 })
  return () => split.revert()
})
```

### Cleanup

```javascript
const split = new SplitText('#text', { type: 'chars' })

// Revert to original HTML
split.revert()

// Kill specific splits
split.chars.revert()

// Clear all splits
SplitText.revert()
```

## ScrambleTextPlugin

### Basic Scramble

```javascript
gsap.registerPlugin(ScrambleTextPlugin)

gsap.to('#text', {
  duration: 2,
  scrambleText: {
    chars: 'upperCase',
    revealDelay: 0.5,
    speed: 0.3
  }
})
```

### Custom Characters

```javascript
gsap.to('#text', {
  duration: 2,
  scrambleText: {
    chars: '!<>-_\\/[]{}—=+*^?#________',
    speed: 0.2
  }
})
```

### Text Change

```javascript
gsap.to('#text', {
  duration: 2,
  scrambleText: {
    text: 'New Text Here',
    chars: 'XO',
    revealDelay: 0.3,
    speed: 0.4
  }
})
```

### Reveal Pattern

```javascript
gsap.to('#text', {
  duration: 3,
  scrambleText: {
    chars: '0123456789',
    revealDelay: 1,
    speed: 0.1
  }
})
```

### Decode Effect

```javascript
gsap.to('#secret', {
  duration: 4,
  scrambleText: {
    text: 'DECODED MESSAGE',
    chars: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ',
    revealDelay: 2,
    speed: 0.2
  }
})
```

### Speed Control

```javascript
gsap.to('#text', {
  duration: 2,
  scrambleText: {
    chars: 'upperCase',
    speed: 0.1,           // Slow scramble
    revealDelay: 1.5
  }
})

// Fast scramble
gsap.to('#text', {
  duration: 1,
  scrambleText: {
    chars: 'upperCase',
    speed: 0.8,           // Fast scramble
    revealDelay: 0.2
  }
})
```

### Combined with SplitText

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  scrambleText: {
    chars: 'XO',
    speed: 0.3,
    revealDelay: 0.5
  },
  stagger: 0.03,
  duration: 2,
  ease: 'power2.out'
})
```

## TextPlugin

### Basic Text Change

```javascript
gsap.registerPlugin(TextPlugin)

gsap.to('#text', {
  duration: 1,
  text: 'New text content'
})
```

### Incremental Text

```javascript
gsap.to('#counter', {
  duration: 2,
  text: {
    value: 1000,
    delimiter: '',
    padZeroes: true
  }
})
```

### Array Text

```javascript
const phrases = ['Hello', 'World', 'GSAP', 'Text']

gsap.to('#text', {
  duration: 3,
  text: {
    value: phrases,
    delimiter: ' ',
    newClass: 'new-text',
    oldClass: 'old-text'
  }
})
```

## ScrollTrigger + Text

### Scroll Reveal

```javascript
gsap.registerPlugin(ScrollTrigger, SplitText)

const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  y: 30,
  stagger: 0.02,
  scrollTrigger: {
    trigger: '#text',
    start: 'top 80%',
    toggleActions: 'play none none reverse'
  }
})
```

### Scrolling Highlight

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.to(split.chars, {
  color: '#ff0000',
  scale: 1.2,
  stagger: 0.01,
  scrollTrigger: {
    trigger: '#text',
    start: 'top center',
    end: 'bottom center',
    scrub: true
  }
})
```

### Scroll Scramble

```javascript
gsap.to('#text', {
  duration: 2,
  scrambleText: {
    text: 'Scrambled Text',
    chars: 'XO',
    speed: 0.3
  },
  scrollTrigger: {
    trigger: '#text',
    start: 'top 80%',
    toggleActions: 'play none none reverse'
  }
})
```

## Text Effects Patterns

### Typewriter Effect

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  x: -10,
  stagger: 0.05,
  duration: 0.1,
  ease: 'none'
})
```

### Wave Effect

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  y: -50,
  opacity: 0,
  stagger: {
    each: 0.03,
    from: 'center',
    ease: 'sine.out'
  },
  duration: 1
})
```

### Explosion Effect

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  scale: 0,
  x: () => gsap.utils.random(-200, 200),
  y: () => gsap.utils.random(-200, 200),
  rotation: () => gsap.utils.random(-180, 180),
  stagger: {
    each: 0.01,
    from: 'random',
    ease: 'power2.out'
  },
  duration: 1.5
})
```

### Glitch Effect

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.to(split.chars, {
  x: () => gsap.utils.random(-5, 5),
  y: () => gsap.utils.random(-5, 5),
  stagger: {
    each: 0.02,
    from: 'random',
    ease: 'steps(3)'
  },
  duration: 0.3,
  repeat: 3,
  yoyo: true,
  onComplete: () => {
    gsap.to(split.chars, { x: 0, y: 0, duration: 0.1 })
  }
})
```

### Magnetic Text

```javascript
const split = new SplitText('#text', { type: 'chars' })

document.querySelectorAll(split.chars).forEach(char => {
  gsap.to(char, {
    x: 0,
    y: 0,
    duration: 0.5,
    ease: 'elastic.out(1, 0.3)'
  })

  char.addEventListener('mouseenter', () => {
    gsap.to(char, {
      x: gsap.utils.random(-10, 10),
      y: gsap.utils.random(-10, 10),
      duration: 0.2
    })
  })
})
```

## Performance Tips

### Optimize Splits

```javascript
// ❌ Split every character unnecessarily
const split = new SplitText('#long-text', { type: 'chars,words,lines' })

// ✅ Split only what you need
const split = new SplitText('#long-text', { type: 'words' })
```

### Revert When Done

```javascript
const split = new SplitText('#text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  y: 20,
  stagger: 0.02,
  duration: 0.5,
  onComplete: () => {
    split.revert()  // Clean up when animation done
  }
})
```

### Use matchMedia

```javascript
// ❌ Always split chars
const split = new SplitText('#text', { type: 'chars' })

// ✅ Only split on large screens
const mm = gsap.matchMedia()

mm.add('(min-width: 768px)', () => {
  const split = new SplitText('#text', { type: 'chars' })
  gsap.from(split.chars, { opacity: 0, y: 20, stagger: 0.02 })
  return () => split.revert()
})
```

## Common Mistakes

### 1. Forgetting Revert

```javascript
// ❌ Memory leaks
const split = new SplitText('#text', { type: 'chars' })
// Never revert

// ✅ Always revert
const split = new SplitText('#text', { type: 'chars' })
// ... animation ...
split.revert()
```

### 2. Splitting Too Much

```javascript
// ❌ Split everything
const split = new SplitText('#text', { type: 'chars,words,lines' })

// ✅ Split only needed parts
const split = new SplitText('#text', { type: 'chars' })
```

### 3. Wrong Scramble Speed

```javascript
// ❌ Too slow, unreadable
gsap.to('#text', {
  duration: 5,
  scrambleText: {
    chars: 'upperCase',
    speed: 0.05
  }
})

// ✅ Readable speed
gsap.to('#text', {
  duration: 2,
  scrambleText: {
    chars: 'upperCase',
    speed: 0.3
  }
})
```

## Best Practices

1. **Revert splits** - Clean up after animations
2. **Use matchMedia** - Responsive text animations
3. **Choose right split type** - Chars, words, or lines based on effect
4. **Control stagger** - Don't make it too slow or too fast
5. **Combine with ScrollTrigger** - Create scroll-based text reveals
6. **Test performance** - Long text with char splits can be heavy
7. **Use appropriate speed** - Scramble should be readable
8. **Consider accessibility** - Ensure text remains accessible

## Quick Reference

| Feature | Method |
|---------|--------|
| Split chars | `new SplitText(target, { type: 'chars' })` |
| Split words | `new SplitText(target, { type: 'words' })` |
| Split lines | `new SplitText(target, { type: 'lines' })` |
| Revert split | `split.revert()` |
| Scramble text | `gsap.to(target, { scrambleText: { chars, speed } })` |
| Change text | `gsap.to(target, { text: 'new text' })` |
| Stagger chars | `gsap.from(split.chars, { stagger: 0.02 })` |
| Scroll reveal | `gsap.from(split.chars, { scrollTrigger: { ... } })` |
