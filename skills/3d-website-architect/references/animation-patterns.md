# Animation Patterns Reference

Complete reference for implementing smooth, premium animations in modern web experiences.
Consult this when implementing Step 6 of the Immersive Design Process.

## Table of Contents

1. [Framer Motion Patterns](#framer-motion-patterns)
2. [GSAP Patterns](#gsap-patterns)
3. [Scroll Animation Choreography](#scroll-animation-choreography)
4. [Micro-Interactions](#micro-interactions)
5. [Page Transitions](#page-transitions)
6. [CSS Animation Recipes](#css-animation-recipes)
7. [Performance Guidelines](#performance-guidelines)
8. [Accessibility](#accessibility)

---

## Framer Motion Patterns

### Scroll Reveal Component

The most-used animation pattern — elements fade and slide in on scroll:

```tsx
'use client';
import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';

interface ScrollRevealProps {
  children: React.ReactNode;
  delay?: number;
  direction?: 'up' | 'down' | 'left' | 'right';
  duration?: number;
  className?: string;
}

export function ScrollReveal({
  children,
  delay = 0,
  direction = 'up',
  duration = 0.6,
  className,
}: ScrollRevealProps) {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, margin: '-100px' });

  const directionOffset = {
    up: { y: 30 },
    down: { y: -30 },
    left: { x: 30 },
    right: { x: -30 },
  };

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, ...directionOffset[direction] }}
      animate={isInView ? { opacity: 1, x: 0, y: 0 } : {}}
      transition={{
        duration,
        delay,
        ease: [0.25, 0.1, 0.25, 1], // Custom cubic bezier — smooth deceleration
      }}
    >
      {children}
    </motion.div>
  );
}
```

### Stagger Container

Animate children sequentially for grids, lists, and feature cards:

```tsx
'use client';
import { motion, useInView } from 'framer-motion';
import { useRef } from 'react';

interface StaggerContainerProps {
  children: React.ReactNode;
  staggerDelay?: number;
  className?: string;
}

export function StaggerContainer({
  children,
  staggerDelay = 0.1,
  className,
}: StaggerContainerProps) {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true, margin: '-50px' });

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        staggerChildren: staggerDelay,
        delayChildren: 0.1,
      },
    },
  };

  return (
    <motion.div
      ref={ref}
      className={className}
      variants={containerVariants}
      initial="hidden"
      animate={isInView ? 'visible' : 'hidden'}
    >
      {children}
    </motion.div>
  );
}

// Stagger Item — use as direct child of StaggerContainer
export function StaggerItem({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    visible: {
      opacity: 1,
      y: 0,
      transition: {
        duration: 0.5,
        ease: [0.25, 0.1, 0.25, 1],
      },
    },
  };

  return (
    <motion.div className={className} variants={itemVariants}>
      {children}
    </motion.div>
  );
}
```

**Usage:**

```tsx
<StaggerContainer className="grid grid-cols-3 gap-6">
  {features.map((feature) => (
    <StaggerItem key={feature.id}>
      <FeatureCard {...feature} />
    </StaggerItem>
  ))}
</StaggerContainer>
```

### Hero Entrance Animation

Orchestrated hero reveal with title, subtitle, and CTA appearing in sequence:

```tsx
const heroVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.15,
      delayChildren: 0.3, // Wait for page load
    },
  },
};

const childVariants = {
  hidden: { opacity: 0, y: 30 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.7, ease: [0.25, 0.1, 0.25, 1] },
  },
};

function HeroSection() {
  return (
    <motion.section
      variants={heroVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.h1 variants={childVariants} className="text-7xl font-bold">
        Build The Future
      </motion.h1>
      <motion.p variants={childVariants} className="text-xl text-gray-400 mt-6">
        The next generation platform for modern teams
      </motion.p>
      <motion.div variants={childVariants} className="flex gap-4 mt-8">
        <Button>Get Started</Button>
        <Button variant="secondary">Learn More</Button>
      </motion.div>
    </motion.section>
  );
}
```

### Counter / Number Animation

Animated number counting for stats sections:

```tsx
import { useInView, useMotionValue, useTransform, animate } from 'framer-motion';
import { useEffect, useRef } from 'react';

function AnimatedCounter({ target, suffix = '' }: { target: number; suffix?: string }) {
  const ref = useRef(null);
  const isInView = useInView(ref, { once: true });
  const count = useMotionValue(0);
  const rounded = useTransform(count, (v) => Math.round(v));

  useEffect(() => {
    if (isInView) {
      animate(count, target, { duration: 2, ease: 'easeOut' });
    }
  }, [isInView, count, target]);

  return (
    <motion.span ref={ref}>
      {rounded}
      {suffix}
    </motion.span>
  );
}

// Usage: <AnimatedCounter target={10000} suffix="+" />
```

### Hover Card Effect

3D tilt on hover — premium feel for cards:

```tsx
import { motion, useMotionValue, useSpring, useTransform } from 'framer-motion';

function TiltCard({ children }: { children: React.ReactNode }) {
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const rotateX = useSpring(useTransform(y, [-0.5, 0.5], [8, -8]), {
    stiffness: 300,
    damping: 30,
  });
  const rotateY = useSpring(useTransform(x, [-0.5, 0.5], [-8, 8]), {
    stiffness: 300,
    damping: 30,
  });

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    x.set((e.clientX - rect.left) / rect.width - 0.5);
    y.set((e.clientY - rect.top) / rect.height - 0.5);
  }

  function handleMouseLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.div
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        rotateX,
        rotateY,
        transformStyle: 'preserve-3d',
        perspective: 800,
      }}
      className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm p-6"
    >
      {children}
    </motion.div>
  );
}
```

---

## GSAP Patterns

### GSAP + ScrollTrigger Setup

```tsx
'use client';
import { useEffect, useRef } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

// Register plugin once
if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger);
}
```

### Scroll-Pinned Section Reveal

Pin a section and reveal content as user scrolls through it:

```tsx
function PinnedFeatures() {
  const sectionRef = useRef<HTMLDivElement>(null);
  const cardsRef = useRef<HTMLDivElement[]>([]);

  useEffect(() => {
    const cards = cardsRef.current;

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: sectionRef.current,
        start: 'top top',
        end: `+=${cards.length * 100}%`,
        pin: true,
        scrub: 1,
      },
    });

    cards.forEach((card, i) => {
      tl.fromTo(
        card,
        { opacity: 0, y: 60, scale: 0.95 },
        { opacity: 1, y: 0, scale: 1, duration: 1 },
        i * 0.8, // Stagger timing
      );

      if (i < cards.length - 1) {
        tl.to(card, { opacity: 0, y: -40, duration: 0.5 }, (i + 1) * 0.8 - 0.2);
      }
    });

    return () => { tl.kill(); };
  }, []);

  return (
    <section ref={sectionRef} className="h-screen relative overflow-hidden">
      {features.map((feature, i) => (
        <div
          key={i}
          ref={(el) => { if (el) cardsRef.current[i] = el; }}
          className="absolute inset-0 flex items-center justify-center"
        >
          <FeatureCard {...feature} />
        </div>
      ))}
    </section>
  );
}
```

### Horizontal Scroll Section

```tsx
function HorizontalScroll() {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const scrollElement = scrollRef.current;
    if (!scrollElement) return;

    const totalWidth = scrollElement.scrollWidth - window.innerWidth;

    gsap.to(scrollElement, {
      x: -totalWidth,
      ease: 'none',
      scrollTrigger: {
        trigger: containerRef.current,
        start: 'top top',
        end: `+=${totalWidth}`,
        pin: true,
        scrub: 1,
      },
    });

    return () => { ScrollTrigger.getAll().forEach((t) => t.kill()); };
  }, []);

  return (
    <section ref={containerRef} className="h-screen overflow-hidden">
      <div ref={scrollRef} className="flex gap-8 h-full items-center px-16">
        {items.map((item, i) => (
          <div key={i} className="min-w-[400px] flex-shrink-0">
            <Card {...item} />
          </div>
        ))}
      </div>
    </section>
  );
}
```

### Text Reveal Animation

Split text and animate character by character:

```tsx
function TextReveal({ text }: { text: string }) {
  const textRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const element = textRef.current;
    if (!element) return;

    // Split text into spans
    const chars = text.split('').map((char) => {
      const span = document.createElement('span');
      span.textContent = char === ' ' ? '\u00A0' : char;
      span.style.display = 'inline-block';
      span.style.opacity = '0';
      span.style.transform = 'translateY(40px)';
      return span;
    });

    element.textContent = '';
    chars.forEach((span) => element.appendChild(span));

    gsap.to(chars, {
      opacity: 1,
      y: 0,
      stagger: 0.03,
      duration: 0.6,
      ease: 'power3.out',
      scrollTrigger: {
        trigger: element,
        start: 'top 80%',
      },
    });

    return () => { ScrollTrigger.getAll().forEach((t) => t.kill()); };
  }, [text]);

  return <h2 ref={textRef} className="text-5xl font-bold">{text}</h2>;
}
```

### Parallax Depth Layers

```tsx
function ParallaxSection() {
  const sectionRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    if (!section) return;

    const layers = section.querySelectorAll('[data-speed]');

    layers.forEach((layer) => {
      const speed = parseFloat(layer.getAttribute('data-speed') || '0');

      gsap.to(layer, {
        yPercent: speed * 100,
        ease: 'none',
        scrollTrigger: {
          trigger: section,
          start: 'top bottom',
          end: 'bottom top',
          scrub: true,
        },
      });
    });

    return () => { ScrollTrigger.getAll().forEach((t) => t.kill()); };
  }, []);

  return (
    <section ref={sectionRef} className="relative h-[150vh] overflow-hidden">
      <div data-speed="-0.3" className="absolute inset-0">
        {/* Background layer — moves slower */}
      </div>
      <div data-speed="0" className="relative z-10">
        {/* Content layer — normal speed */}
      </div>
      <div data-speed="0.2" className="absolute z-20">
        {/* Foreground layer — moves faster */}
      </div>
    </section>
  );
}
```

---

## Scroll Animation Choreography

### Recommended Timing

| Element | Duration | Delay | Ease |
|---------|----------|-------|------|
| Hero headline | 700ms | 300ms | `[0.25, 0.1, 0.25, 1]` |
| Hero subtitle | 700ms | 450ms | `[0.25, 0.1, 0.25, 1]` |
| Hero CTA buttons | 600ms | 600ms | `[0.25, 0.1, 0.25, 1]` |
| Section heading | 600ms | 0ms | `[0.25, 0.1, 0.25, 1]` |
| Card reveal | 500ms | stagger 100ms | `[0.25, 0.1, 0.25, 1]` |
| Image/visual | 800ms | 100ms | `[0.25, 0.1, 0.25, 1]` |
| Stat counter | 2000ms | 0ms | `easeOut` |
| Logo bar | 500ms | stagger 50ms | `easeOut` |

### Scroll Trigger Points

| Element | Trigger (start) | Why |
|---------|----------------|-----|
| Section headings | `top 80%` | Appear as user approaches |
| Content cards | `top 85%` | Visible in lower viewport |
| Large visuals | `top 90%` | Start early — they need time to fully appear |
| Pinned sections | `top top` | Pin when fully in view |
| Background parallax | `top bottom` to `bottom top` | Full scroll range |

### Choreography Rules

1. **Top-to-bottom flow** — elements higher in the DOM animate first
2. **Left-to-right for grids** — stagger follows natural reading order
3. **Heading before content** — the title appears, then supporting elements follow
4. **One animation per scroll viewport** — don't overwhelm; let each section breathe
5. **Never block content** — if animation hasn't triggered, content should still be readable (use `once: true`)

---

## Micro-Interactions

### Button Press Feedback

```tsx
<motion.button
  whileHover={{ scale: 1.02, y: -2 }}
  whileTap={{ scale: 0.98 }}
  transition={{ type: 'spring', stiffness: 400, damping: 17 }}
  className="px-8 py-3 bg-indigo-600 rounded-xl text-white font-medium"
>
  Get Started
</motion.button>
```

### Magnetic Button (Cursor Attraction)

```tsx
function MagneticButton({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLButtonElement>(null);
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const springX = useSpring(x, { stiffness: 150, damping: 15 });
  const springY = useSpring(y, { stiffness: 150, damping: 15 });

  function handleMouseMove(e: React.MouseEvent) {
    const rect = ref.current!.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    x.set((e.clientX - centerX) * 0.2);
    y.set((e.clientY - centerY) * 0.2);
  }

  function handleMouseLeave() {
    x.set(0);
    y.set(0);
  }

  return (
    <motion.button
      ref={ref}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{ x: springX, y: springY }}
    >
      {children}
    </motion.button>
  );
}
```

### Icon Rotation on Hover

```tsx
<motion.div whileHover={{ rotate: 90 }} transition={{ duration: 0.3 }}>
  <PlusIcon className="w-5 h-5" />
</motion.div>
```

### Card Hover Glow Border

```tsx
function GlowCard({ children }: { children: React.ReactNode }) {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const cardRef = useRef<HTMLDivElement>(null);

  function handleMouseMove(e: React.MouseEvent) {
    const rect = cardRef.current!.getBoundingClientRect();
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  }

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      className="relative rounded-2xl border border-white/10 bg-white/5 p-6 overflow-hidden group"
    >
      {/* Moving glow that follows cursor */}
      <div
        className="absolute w-40 h-40 rounded-full bg-indigo-500/20 blur-3xl pointer-events-none
                   opacity-0 group-hover:opacity-100 transition-opacity duration-500"
        style={{
          left: mousePos.x - 80,
          top: mousePos.y - 80,
        }}
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
```

---

## Page Transitions

### Framer Motion Layout Animations

```tsx
import { AnimatePresence, motion } from 'framer-motion';

function PageWrapper({ children, key }: { children: React.ReactNode; key: string }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={key}
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3, ease: 'easeInOut' }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
```

### Slide-In Page Transition

```tsx
const pageTransition = {
  initial: { opacity: 0, x: 100 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -100 },
  transition: { duration: 0.4, ease: [0.25, 0.1, 0.25, 1] },
};
```

---

## CSS Animation Recipes

For simple animations that don't need a library:

### Floating Element

```css
@keyframes float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-10px); }
}

.float {
  animation: float 3s ease-in-out infinite;
}
```

### Pulse Glow

```css
@keyframes pulse-glow {
  0%, 100% { box-shadow: 0 0 20px rgba(99, 102, 241, 0.3); }
  50% { box-shadow: 0 0 40px rgba(99, 102, 241, 0.6); }
}

.pulse-glow {
  animation: pulse-glow 2s ease-in-out infinite;
}
```

### Gradient Shift

```css
@keyframes gradient-shift {
  0% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
  100% { background-position: 0% 50%; }
}

.gradient-animated {
  background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899, #6366f1);
  background-size: 300% 100%;
  animation: gradient-shift 4s ease-in-out infinite;
}
```

### Shimmer / Skeleton Loading

```css
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.skeleton {
  position: relative;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
}

.skeleton::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.05),
    transparent
  );
  animation: shimmer 1.5s infinite;
}
```

### Marquee / Logo Scroll

```css
@keyframes marquee {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

.marquee-track {
  display: flex;
  width: max-content;
  animation: marquee 20s linear infinite;
}

.marquee-track:hover {
  animation-play-state: paused;
}
```

### Spinning Ring (Loading)

```css
@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.loading-ring {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(99, 102, 241, 0.2);
  border-top-color: #6366f1;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
```

---

## Performance Guidelines

### GPU-Accelerated Properties

Only animate these for smooth 60fps:

| Property | GPU? | Notes |
|----------|------|-------|
| `transform` | Yes | translate, rotate, scale — always use these |
| `opacity` | Yes | Fade in/out — GPU composited |
| `filter` | Partial | blur, brightness — GPU on most browsers |
| `width/height` | No | Triggers layout recalculation — AVOID |
| `top/left/right/bottom` | No | Triggers layout — use transform: translate instead |
| `margin/padding` | No | Triggers layout — AVOID animating |
| `background-color` | No | Triggers paint, but lightweight enough for hovers |

### Performance Rules

1. **Batch animations** — use `will-change: transform, opacity` on elements that will animate
2. **Remove will-change after animation** — long-lived will-change wastes GPU memory
3. **Limit simultaneous animations** — max 10–15 elements animating at once on screen
4. **Use `once: true`** on scroll reveals — don't re-trigger animations on scroll back
5. **Stagger over slam** — never animate a grid of 12 cards simultaneously; stagger them
6. **Debounce scroll handlers** — use `requestAnimationFrame` or library-provided throttling
7. **Disable on reduced motion** — check `prefers-reduced-motion: reduce`

### Monitoring Animation Performance

```tsx
// Quick Chrome DevTools check:
// 1. Open DevTools → Performance → Enable paint flashing
// 2. Scroll through the page — green flashes show repaints
// 3. Minimize green flashes by using transform/opacity only

// Framer Motion debug:
<motion.div
  onAnimationStart={() => console.log('Animation started')}
  onAnimationComplete={() => console.log('Animation complete')}
/>
```

---

## Accessibility

### Reduced Motion Support

```tsx
// Framer Motion — automatically respects prefers-reduced-motion if you use:
import { useReducedMotion } from 'framer-motion';

function AnimatedSection({ children }: { children: React.ReactNode }) {
  const shouldReduceMotion = useReducedMotion();

  return (
    <motion.div
      initial={shouldReduceMotion ? {} : { opacity: 0, y: 30 }}
      animate={{ opacity: 1, y: 0 }}
      transition={shouldReduceMotion ? { duration: 0 } : { duration: 0.6 }}
    >
      {children}
    </motion.div>
  );
}
```

### CSS Reduced Motion

```css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

### GSAP Reduced Motion

```tsx
useEffect(() => {
  const prefersReducedMotion = window.matchMedia(
    '(prefers-reduced-motion: reduce)'
  ).matches;

  if (prefersReducedMotion) {
    gsap.globalTimeline.timeScale(100); // Instantly complete animations
    return;
  }

  // Normal GSAP setup...
}, []);
```

### Accessibility Rules for Animation

1. **Never convey information only through animation** — content must be readable without motion
2. **Provide pause controls** for continuous animations (auto-scrolling, marquees, particles)
3. **Avoid rapid flashing** — nothing should flash more than 3 times per second
4. **Keep scroll-triggered content accessible** — ensure content is visible even if animation fails
5. **3D scenes must have `aria-hidden="true"`** or descriptive `aria-label` if they're decorative vs. interactive
