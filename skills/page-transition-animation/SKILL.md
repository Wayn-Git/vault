---
name: page-transition-animation
description: This skill should be used when the user asks to "animate page or route transitions", "add a page transition or crossfade between views", "animate route changes in Next.js App Router", "use the View Transitions API", "AnimatePresence exit doesn't fire on navigation", or "Framer Motion exit animation not working / exit animation before unmount in Next.js". Covers enter/exit page-transition animation with the View Transitions API and Framer Motion, for Next.js App Router and general SPA routing.
version: 0.1.0
---

# Page Transition Animation (Next.js App Router)

Implement page enter/exit transitions in the Next.js **App Router**, and fix the single most common failure: **Framer Motion `AnimatePresence` exit animations never fire on navigation**. The reason is structural — in the App Router, when navigating, Next.js unmounts the old route's content and mounts the new one almost immediately. `AnimatePresence` can only animate an exit if the *exiting element stays mounted* under a *persistent* `AnimatePresence` wrapper long enough to run the animation. Because the router swaps children out from under it, the exit is skipped. Two approaches solve this: a pathname-keyed `AnimatePresence` with the **FrozenRouter** pattern, or the **View Transitions API** (native / `next-view-transitions`).

## When to use

Use when adding animated page transitions in a Next.js App Router app, when a Framer Motion `exit` prop does nothing on route change, when an old page disappears instantly instead of animating out, when choosing between Framer Motion and the View Transitions API for Next.js, or when debugging why `AnimatePresence` won't animate between routes.

## Why exit doesn't fire (the core problem)

`AnimatePresence` detects removal of a *direct keyed child*. On App Router navigation:

1. The wrapper must persist across the navigation. If `AnimatePresence` lives in a component that itself unmounts, there is nothing left to run the exit.
2. The child's `key` must change per route so AnimatePresence sees "old removed, new added".
3. During the brief overlap, the *outgoing* subtree must still render its old content — but the App Router has already swapped the route context, so the outgoing tree would otherwise render the *new* page's data. This is what **FrozenRouter** fixes.

## Solution A: template.tsx + keyed AnimatePresence + FrozenRouter

`template.tsx` is the App Router's purpose-built hook for this: unlike `layout.tsx` (which persists), a **template remounts on every navigation**, giving each route a fresh instance — ideal for per-route enter animations. Combine it with a pathname-keyed `AnimatePresence` and FrozenRouter for clean exit + enter.

```tsx
// app/template.tsx
'use client';
import { AnimatePresence } from 'framer-motion';
import { usePathname } from 'next/navigation';
import { FrozenRouter } from './frozen-router';
import { PageTransition } from './page-transition';

export default function Template({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <AnimatePresence mode="wait" initial={false}>
      {/* key on pathname so AnimatePresence sees old removed / new added */}
      <PageTransition key={pathname}>
        {/* FrozenRouter keeps the OUTGOING tree rendering its old content
            while it animates out */}
        <FrozenRouter>{children}</FrozenRouter>
      </PageTransition>
    </AnimatePresence>
  );
}
```

```tsx
// app/page-transition.tsx
'use client';
import { motion } from 'framer-motion';

export function PageTransition({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}
```

```tsx
// app/frozen-router.tsx
'use client';
import { useContext, useRef } from 'react';
import {
  LayoutRouterContext,
} from 'next/dist/shared/lib/app-router-context.shared-runtime';

// Freezes the router context so the exiting page keeps rendering its
// OWN content during the exit animation instead of the next route's.
export function FrozenRouter({ children }: { children: React.ReactNode }) {
  const context = useContext(LayoutRouterContext ?? {});
  const frozen = useRef(context).current;

  return (
    <LayoutRouterContext.Provider value={frozen}>
      {children}
    </LayoutRouterContext.Provider>
  );
}
```

How it fits together:

- `mode="wait"` makes AnimatePresence fully finish the exit before mounting the new page. (Use the default mode if enter/exit should overlap/crossfade.)
- `initial={false}` skips the enter animation on first load (optional).
- `key={pathname}` is what makes AnimatePresence treat each route as a distinct presence.
- `FrozenRouter` snapshots `LayoutRouterContext` so the outgoing subtree renders the *previous* route's content throughout the exit, instead of flashing the new route's content. Without it, exit either skips or shows the wrong content.

Note: `LayoutRouterContext` is a Next.js internal; its import path can change between Next versions. If the import breaks after an upgrade, that path is the thing to update.

## Solution B: native View Transitions API

The View Transitions API animates between two DOM states with the browser capturing before/after snapshots — no per-element exit components.

```css
/* globals.css */
@view-transition { navigation: auto; } /* opt MPA-style in (where supported) */

::view-transition-old(root) { animation: fade 0.25s both reverse; }
::view-transition-new(root) { animation: fade 0.25s both; }
@keyframes fade { from { opacity: 0; } to { opacity: 1; } }
```

For SPA-style App Router navigations, wrap the router update:

```ts
if (document.startViewTransition) {
  document.startViewTransition(() => router.push(href));
} else {
  router.push(href);
}
```

### next-view-transitions library

`next-view-transitions` integrates the View Transitions API with the App Router's client navigation so it works out of the box:

```tsx
// app/layout.tsx
import { ViewTransitions } from 'next-view-transitions';
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ViewTransitions>
      <html lang="en"><body>{children}</body></html>
    </ViewTransitions>
  );
}
```

```tsx
// use the library's Link instead of next/link
import { Link } from 'next-view-transitions';
<Link href="/about">About</Link>;
```

Choose View Transitions for simple cross-page fades/morphs and shared-element transitions with minimal JS; choose Framer Motion when fine-grained, orchestrated, interruptible, or staggered exit animations are needed. View Transitions API browser support is still uneven, so provide a graceful fallback (the `if (document.startViewTransition)` guard).

## AnimatePresence debug checklist

When exit still won't fire, verify in order:

1. **Wrapper stays mounted.** `AnimatePresence` must live in something persistent — ideally `template.tsx`, or a layout-level client component — not inside the page that's unmounting.
2. **Stable, changing key.** The animated child needs `key={pathname}` (or similar) so removal is detected. No key, or a key that doesn't change → no exit.
3. **Direct motion descendant.** The element with the `exit` prop must be a `motion.*` component and a child of `AnimatePresence` (a non-motion wrapper in between can block detection).
4. **`mode="wait"`** if old and new should not overlap; without it both render simultaneously and may jump.
5. **FrozenRouter present** if the outgoing page flashes the new route's content during exit.
6. **`'use client'`** on every file using AnimatePresence/usePathname/motion.
7. **Single child at a time** under `mode="wait"` — AnimatePresence expects one keyed presence to swap.

## Deliver & verify (standalone HTML)

> **Packaged helper** (`scripts/`): `scripts/seek-shot.sh anim.html 0 1.5 3` freezes the `?t=N` harness and screenshots each moment; `scripts/contact-sheet.sh sheet.png frame-*.png` tiles them for one-glance review. See `scripts/README.md`.

The real target is a Next.js app, but to *prove the transition shape* (the enter/exit curve, direction, crossfade) you can ship **one HTML file that opens directly in a browser** — two stub "pages" you toggle, animated with `motion` from CDN or the native View Transitions API. One file is the right tier for validating motion before wiring the router; don't stand up Next just to eyeball a fade.

**Output contract:**
- One `.html` file: two view stubs and a toggle, animated with either an inline `<script type="module">` importing `motion`/React from CDN, or `document.startViewTransition` + `::view-transition-*` CSS.
- A way to freeze the **resolved end state** — a route transition is state-driven (which view, mid-swap), so screenshot the state, not a clock.

**Seek harness — pin a transition phase.** `?view=b` mounts the destination view (or `?phase=exit` to hold the outgoing tree mid-animation) so a screenshot lands on a settled phase:

```html
<script>
  const p = new URLSearchParams(location.search);
  document.documentElement.dataset.view = p.get("view") || "a";   // CSS/React keys off this
  // Framer Motion: set the controlled key/route from ?view; for mode="wait" the resolved end is the new page
  // View Transitions: screenshot the END state (snapshots are transient); or pause via emulate slow animations
  window.__ready = true;
</script>
```

**Verify loop — render → set phase → screenshot → check:** open source, mid, and destination (`?view=a`, `?phase=exit`, `?view=b`), screenshot each, and check **fidelity** (exit actually runs, direction/crossfade matches the brief, no `mode="wait"` lag) plus **artifacts** (outgoing tree flashing the new page's content, double-mount, FOUC, jank). Any headless tool works:

```bash
npx playwright screenshot --wait-for-timeout=500 "file://$PWD/transition.html?view=b" dest.png
```

**Before you finish:**
1. Opens standalone — no console errors, CDN `motion`/React (if used) resolves, `startViewTransition` guarded.
2. The `?view=`/`?phase=` freeze lands a deterministic transition phase.
3. Screenshotted at source / mid / destination — matches the brief, no content flash or skipped exit.
4. `prefers-reduced-motion` honored — slide/translate dropped to a short crossfade.
5. Easing is intentional — entrances ease-out, exits ease-in, durations ~0.2–0.4s (not laggy under `mode="wait"`).

## Quick reference

| Need | Approach |
|---|---|
| Per-route enter animation | `app/template.tsx` (remounts each nav) |
| Exit animation on nav | keyed `AnimatePresence mode="wait"` + FrozenRouter |
| Outgoing page shows old content | FrozenRouter (snapshot `LayoutRouterContext`) |
| Detect route change | `usePathname()` as the `key` |
| Simple cross-page fade/morph | View Transitions API / next-view-transitions |
| Shared element transition | `view-transition-name` CSS |
| Skip first-load animation | `initial={false}` |

## Gotchas

- `layout.tsx` persists and will NOT remount per route — use `template.tsx` for per-route enter animations.
- Omitting FrozenRouter makes the exiting page render the *new* route's content mid-animation (visible flash) or skip exit entirely.
- `LayoutRouterContext` import path is a Next internal; it may change across versions — first thing to fix after an upgrade.
- Without `key={pathname}`, AnimatePresence sees the same child and never triggers exit.
- `mode="wait"` waits for exit before enter; overusing it on slow exits makes navigation feel laggy — tune durations (~0.2-0.4s).
- View Transitions API lacks full browser support; always guard `document.startViewTransition`.
- Every transition file needs `'use client'`; server components can't use AnimatePresence/usePathname.

## Reference files

- `references/full-examples.md` — directional/slide transitions, shared-element View Transitions with `view-transition-name`, a non-`mode="wait"` crossfade variant, loading-state transitions with `loading.tsx`, and a complete working App Router folder layout.
