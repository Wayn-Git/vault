# GSAP SplitText

Split text elements into characters, words, and lines for individual animation.

**Note (2026-02):** SplitText is available in the public `gsap` npm package (GSAP 3.13+) under the GSAP Standard No-Charge License.

## Setup

```javascript
import gsap from 'gsap'
import { SplitText } from 'gsap/SplitText'

gsap.registerPlugin(SplitText)
```

## Basic Usage

```javascript
// Split into characters
const split = SplitText.create('.text', { type: 'chars' })

// Animate characters
gsap.from(split.chars, {
  opacity: 0,
  y: 50,
  stagger: 0.05,
  duration: 0.5
})
```

## Split Types

```javascript
// Characters only
SplitText.create('.text', { type: 'chars' })

// Words only
SplitText.create('.text', { type: 'words' })

// Lines only
SplitText.create('.text', { type: 'lines' })

// Multiple types
SplitText.create('.text', { type: 'chars, words' })
SplitText.create('.text', { type: 'words, lines' })
SplitText.create('.text', { type: 'chars, words, lines' })
```

## Accessing Split Elements

```javascript
const split = SplitText.create('.text', { type: 'chars, words, lines' })

// Arrays of elements
split.chars    // array of character divs
split.words    // array of word divs
split.lines    // array of line divs

// Animate
gsap.from(split.chars, { opacity: 0, stagger: 0.02 })
gsap.from(split.words, { y: 20, stagger: 0.1 })
gsap.from(split.lines, { x: -50, stagger: 0.2 })
```

## Configuration Options

```javascript
SplitText.create('.text', {
  type: 'chars, words, lines',

  // CSS classes for styled hooks
  charsClass: 'char',
  wordsClass: 'word',
  linesClass: 'line',

  // Incremental class (char++, word++, line++)
  charsClass: 'char++',    // char1, char2, char3...
  wordsClass: 'word++',    // word1, word2, word3...
  linesClass: 'line++',    // line1, line2, line3...

  // Spacing
  wordDelimiter: ' ',      // what separates words

  // Preserve position
  position: 'relative',    // or 'absolute'

  // Tag type
  tag: 'div',              // default
  tag: 'span',             // inline

  // Line threshold (for line detection)
  lineThreshold: 0.2       // sensitivity (0-1)
})
```

## Reverting Split

**Important:** Always revert to clean up DOM after animation.

```javascript
const split = SplitText.create('.text', { type: 'words' })

gsap.from(split.words, {
  y: 100,
  opacity: 0,
  stagger: 0.1,
  onComplete: () => split.revert()  // restore original HTML
})
```

## Auto Split (Responsive)

Automatically re-split when container width changes:

```javascript
SplitText.create('.text', {
  type: 'words, lines',
  autoSplit: true,
  onSplit: (self) => {
    // Called on each split (initial and re-splits)
    return gsap.from(self.lines, {
      yPercent: 100,
      opacity: 0,
      stagger: 0.1,
      duration: 0.5
    })
  }
})
```

The returned tween is automatically cleaned up before re-splitting.

## Special Characters

```javascript
// Preserve specific characters
SplitText.create('.text', {
  type: 'chars',
  specialChars: ['&amp;', '&lt;', '&gt;']  // HTML entities
})

// Custom function
SplitText.create('.text', {
  type: 'chars',
  specialChars: (text) => {
    // Return array of strings to treat as single chars
    return text.match(/./gu)  // Unicode-aware
  }
})
```

## Nested Elements

SplitText handles nested elements:

```html
<p class="text">
  This is <strong>bold</strong> and <em>italic</em> text.
</p>
```

```javascript
// Nested tags are preserved
const split = SplitText.create('.text', { type: 'chars, words' })
```

## Common Animation Patterns

### Typewriter Effect

```javascript
const split = SplitText.create('.text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  duration: 0.02,
  stagger: 0.05
})
```

### Wave Effect

```javascript
const split = SplitText.create('.text', { type: 'chars' })

gsap.to(split.chars, {
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

### Line Reveal

```javascript
const split = SplitText.create('.text', {
  type: 'lines',
  linesClass: 'line'
})

// CSS: .line { overflow: hidden; }
gsap.from(split.lines, {
  yPercent: 100,
  opacity: 0,
  duration: 0.8,
  stagger: 0.15,
  ease: 'power2.out'
})
```

### Word by Word

```javascript
const split = SplitText.create('.text', { type: 'words' })

gsap.from(split.words, {
  opacity: 0,
  y: 30,
  rotationX: -90,
  stagger: 0.08,
  duration: 0.6,
  ease: 'back.out(1.7)'
})
```

### Scatter and Gather

```javascript
const split = SplitText.create('.text', { type: 'chars' })

// Scatter
gsap.from(split.chars, {
  opacity: 0,
  x: 'random(-100, 100)',
  y: 'random(-100, 100)',
  rotation: 'random(-180, 180)',
  scale: 0,
  duration: 0.8,
  stagger: 0.02,
  ease: 'back.out(1.7)'
})
```

### Scroll-Triggered Text

```javascript
const split = SplitText.create('.text', { type: 'chars' })

gsap.from(split.chars, {
  opacity: 0,
  y: 50,
  stagger: 0.02,
  scrollTrigger: {
    trigger: '.text',
    start: 'top 80%'
  }
})
```

## Styling Split Elements

```css
/* Overflow hidden for clip effect */
.line {
  overflow: hidden;
}

/* Inline-block for transforms */
.char, .word {
  display: inline-block;
}

/* Will-change for performance */
.char {
  will-change: transform, opacity;
}
```

## Multiple Text Elements

```javascript
gsap.utils.toArray('.split-text').forEach(text => {
  const split = SplitText.create(text, { type: 'words' })

  gsap.from(split.words, {
    opacity: 0,
    y: 20,
    stagger: 0.05,
    scrollTrigger: {
      trigger: text,
      start: 'top 80%'
    },
    onComplete: () => split.revert()
  })
})
```

## Performance Tips

```javascript
// Split once, animate multiple times
const split = SplitText.create('.text', { type: 'chars' })

// Create timeline
const tl = gsap.timeline({ paused: true })
tl.from(split.chars, { opacity: 0, y: 20, stagger: 0.02 })

// Replay without re-splitting
button.addEventListener('click', () => tl.restart())

// Revert when done
onDestroy(() => split.revert())
```

## Edge Cases

### Whitespace Handling

```javascript
// Preserves whitespace between words
SplitText.create('.text', {
  type: 'words',
  wordDelimiter: ' '  // default
})
```

### RTL Text

```javascript
// Works with right-to-left text
SplitText.create('.rtl-text', { type: 'chars' })
```

### Multi-line with Position Absolute

```javascript
// For line-based animations needing absolute positioning
SplitText.create('.text', {
  type: 'lines',
  position: 'absolute'
})
```
