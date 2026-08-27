# GSAP Text Plugins

## TextPlugin

Animates text content character by character.

### Setup

```javascript
import gsap from 'gsap'
import { TextPlugin } from 'gsap/TextPlugin'

gsap.registerPlugin(TextPlugin)
```

### Basic Usage

```javascript
// Replace text character by character
gsap.to('.text', {
  duration: 2,
  text: 'New text content',
  ease: 'none'
})
```

### Configuration

```javascript
gsap.to('.text', {
  text: {
    value: 'New text content',

    // Delimiter (default: '' for characters)
    delimiter: ' ',      // word by word
    delimiter: '',       // character by character

    // Padding
    padSpace: true,      // pad with spaces during transition

    // Preserve structure
    preserveSpaces: true,

    // New lines
    newClass: 'new-char',    // class for new characters
    oldClass: 'old-char',    // class for old characters

    // Type effect
    type: 'diff'         // only animate differing characters
  },
  duration: 2,
  ease: 'none'
})
```

### Common Patterns

#### Typewriter Effect

```javascript
// Set initial empty
gsap.set('.text', { text: '' })

// Type out
gsap.to('.text', {
  duration: 2,
  text: 'Hello, World!',
  ease: 'none'
})
```

#### Delete and Replace

```javascript
const tl = gsap.timeline()

// Delete current text
tl.to('.text', {
  duration: 1,
  text: '',
  ease: 'none'
})
// Type new text
.to('.text', {
  duration: 1.5,
  text: 'New content here',
  ease: 'none'
})
```

#### Word by Word

```javascript
gsap.to('.text', {
  text: {
    value: 'This reveals word by word',
    delimiter: ' '
  },
  duration: 3,
  ease: 'power1.in'
})
```

---

## ScrambleTextPlugin

Scrambles text with random characters before revealing.

### Setup

```javascript
import gsap from 'gsap'
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin'

gsap.registerPlugin(ScrambleTextPlugin)
```

### Basic Usage

```javascript
gsap.to('.text', {
  duration: 2,
  scrambleText: 'Decoded message'
})
```

### Configuration

```javascript
gsap.to('.text', {
  scrambleText: {
    text: 'Final revealed text',

    // Character set for scrambling
    chars: 'upperCase',      // A-Z
    chars: 'lowerCase',      // a-z
    chars: 'upperAndLowerCase',
    chars: 'ABCXYZ123',      // custom characters
    chars: '01',             // binary effect
    chars: 'symbols',        // !@#$%^&*()

    // Timing
    revealDelay: 0.5,        // delay before revealing starts
    speed: 0.3,              // scramble speed multiplier

    // Control
    tweenLength: true,       // animate string length
    rightToLeft: false,      // reveal direction

    // Preserve
    newClass: 'new',         // class for revealed chars
    oldClass: 'old'          // class for scrambled chars
  },
  duration: 2
})
```

### Common Patterns

#### Hacker/Decode Effect

```javascript
gsap.from('.text', {
  scrambleText: {
    text: '{original}',      // {original} uses current text
    chars: '01',
    revealDelay: 0.3,
    speed: 0.5
  },
  duration: 2
})
```

#### Glitch Reveal

```javascript
gsap.to('.heading', {
  scrambleText: {
    text: 'ACCESS GRANTED',
    chars: 'ABCDEFGHIJKLMNOPQRSTUVWXYZ!@#$%',
    revealDelay: 0.2,
    speed: 0.4
  },
  duration: 1.5,
  ease: 'power1.in'
})
```

#### Staggered Scramble

```javascript
gsap.to('.text-item', {
  scrambleText: {
    text: (i, el) => el.dataset.reveal,  // from data attribute
    chars: 'lowerCase'
  },
  duration: 1,
  stagger: 0.2
})
```

#### Timeline Sequence

```javascript
const tl = gsap.timeline()

tl.to('.line1', {
  scrambleText: { text: 'Initializing...', chars: '01' },
  duration: 1
})
.to('.line2', {
  scrambleText: { text: 'Loading modules', chars: 'XO' },
  duration: 1
})
.to('.line3', {
  scrambleText: { text: 'System ready', chars: 'upperCase' },
  duration: 1.5
})
```

### Notes

- ScrambleTextPlugin is available in the public `gsap` npm package (GSAP 3.13+) under the GSAP Standard No-Charge License.
- TextPlugin is free
- Both work with any text element (span, p, h1, etc.)
- For multiline, ensure proper CSS (white-space handling)
- Use `ease: 'none'` for typewriter effect (linear character reveal)
