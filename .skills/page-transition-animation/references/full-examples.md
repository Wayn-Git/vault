# Full examples and variants

## Working folder layout

```
app/
  layout.tsx           # persistent shell (html/body, providers)
  template.tsx         # remounts per route -> hosts AnimatePresence
  page-transition.tsx  # motion wrapper (enter/exit variants)
  frozen-router.tsx    # FrozenRouter (LayoutRouterContext snapshot)
  page.tsx             # home
  about/page.tsx
  globals.css
```

## Directional slide transitions

Track direction by comparing route depth or a route order map, then feed it to variants.

```tsx
// app/page-transition.tsx
'use client';
import { motion } from 'framer-motion';
import { usePathname } from 'next/navigation';
import { useRef } from 'react';

const order = ['/', '/about', '/work', '/contact'];

export function PageTransition({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const prev = useRef(pathname);
  const dir =
    order.indexOf(pathname) > order.indexOf(prev.current) ? 1 : -1;
  prev.current = pathname;

  return (
    <motion.div
      custom={dir}
      variants={{
        initial: (d: number) => ({ opacity: 0, x: 40 * d }),
        animate: { opacity: 1, x: 0 },
        exit: (d: number) => ({ opacity: 0, x: -40 * d }),
      }}
      initial="initial"
      animate="animate"
      exit="exit"
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
```

## Crossfade variant (no mode="wait")

Omit `mode="wait"` so old and new overlap. Stack them absolutely to avoid layout jump.

```tsx
// app/template.tsx
'use client';
import { AnimatePresence, motion } from 'framer-motion';
import { usePathname } from 'next/navigation';
import { FrozenRouter } from './frozen-router';

export default function Template({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <AnimatePresence initial={false}>
      <motion.div
        key={pathname}
        style={{ gridArea: '1 / 1' }}      // overlap in a 1-cell grid parent
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.35 }}
      >
        <FrozenRouter>{children}</FrozenRouter>
      </motion.div>
    </AnimatePresence>
  );
}
```

Wrap the template output's parent in `display: grid` so both stacked children occupy `grid-area: 1 / 1`.

## Shared-element transition (View Transitions API)

Give the same logical element the same `view-transition-name` on both pages; the browser morphs between them.

```tsx
// list page
<img src={cover} style={{ viewTransitionName: `cover-${id}` }} />
// detail page
<img src={cover} style={{ viewTransitionName: `cover-${id}` }} />
```

```css
::view-transition-old(root),
::view-transition-new(root) { animation-duration: 0.3s; }
/* the named element animates automatically between its two positions */
```

With `next-view-transitions`, use its `<Link>` and the morph happens on navigation. Each `view-transition-name` must be unique on the page at a time.

## loading.tsx + transitions

`loading.tsx` shows an instant Suspense fallback during server work. To animate it, make the fallback a motion component; it mounts/unmounts within the same template-driven AnimatePresence flow.

```tsx
// app/work/loading.tsx
'use client';
import { motion } from 'framer-motion';
export default function Loading() {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      Loading…
    </motion.div>
  );
}
```

## Reduced-motion

```tsx
'use client';
import { useReducedMotion, motion } from 'framer-motion';

export function PageTransition({ children }: { children: React.ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? { opacity: 1 } : { opacity: 0, y: -12 }}
      transition={{ duration: reduce ? 0 : 0.3 }}
    >
      {children}
    </motion.div>
  );
}
```

For the View Transitions API, gate with CSS:

```css
@media (prefers-reduced-motion: reduce) {
  ::view-transition-old(root),
  ::view-transition-new(root) { animation: none; }
}
```

## FrozenRouter import note across versions

The internal context import has shifted across Next versions, e.g.:

```ts
// commonly:
import { LayoutRouterContext } from 'next/dist/shared/lib/app-router-context.shared-runtime';
```

If an upgrade breaks the import, search `node_modules/next/dist/shared/lib/` for `app-router-context` and update the path. Because it is internal, pin awareness of this in any upgrade checklist.

## Framer Motion vs View Transitions decision

| Factor | Framer Motion | View Transitions API |
|---|---|---|
| Browser support | Broad (JS lib) | Uneven; needs fallback |
| Orchestration/stagger | Excellent | Limited |
| Interruptible exits | Yes | Limited |
| Shared element morph | Manual (layoutId) | Native, simple |
| Bundle cost | Adds library | Minimal/native |
| Setup complexity | Medium (FrozenRouter) | Low (next-view-transitions) |

---
Freeze the outgoing route and exit transitions finally fire as intended. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=page-transition-animation)** — the AI motion agent for editable, on-brand motion graphics.
