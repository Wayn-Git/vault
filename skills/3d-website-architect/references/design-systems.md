# Design System Quick Reference

Detailed reference guide for building consistent, premium design systems for 3D-enhanced websites.
Consult this when establishing design foundations in Step 3 of the Immersive Design Process.

## Table of Contents

1. [Typography Systems](#typography-systems)
2. [Color Palette Construction](#color-palette-construction)
3. [Niche-Specific Palettes](#niche-specific-palettes)
4. [Gradient and Glow Recipes](#gradient-and-glow-recipes)
5. [Glassmorphism Recipes](#glassmorphism-recipes)
6. [Spacing Scales](#spacing-scales)
7. [Shadow Systems](#shadow-systems)
8. [Border Radius Languages](#border-radius-languages)
9. [Responsive Breakpoints](#responsive-breakpoints)
10. [3D Material Palettes](#3d-material-palettes)

---

## Typography Systems

### Recommended Font Pairings

| Heading | Body | Vibe | Best For |
|---------|------|------|----------|
| Inter | Inter | Clean, neutral, Swiss-style | Most versatile — works everywhere |
| Cal Sans | Inter | SaaS, modern product | SaaS landing pages, dashboards |
| Space Grotesk | DM Sans | Tech, developer tools | Dev tools, API products |
| Playfair Display | Source Sans 3 | Editorial, luxury | Agencies, luxury brands, portfolios |
| Sora | Nunito Sans | Friendly, approachable | Education, health, consumer apps |
| JetBrains Mono | Inter | Developer, terminal | CLI tools, code-heavy products |
| Clash Display | Satoshi | Bold, creative, startup | Creative agencies, bold startups |
| Manrope | Inter | Geometric, modern | AI products, modern SaaS |
| Cabinet Grotesk | General Sans | Bold, contemporary | Startup landing pages |
| Outfit | Plus Jakarta Sans | Clean, geometric | Modern tech startups |

### Type Scale (1.250 — Major Third)

| Level | Size | Weight | Line Height | Letter Spacing | Usage |
|-------|------|--------|-------------|----------------|-------|
| Display XL | 96px / 6rem | 800 | 1.0 | -0.05em | Immersive hero headlines |
| Display | 72px / 4.5rem | 700-800 | 1.1 | -0.04em | Hero headlines |
| H1 | 48px / 3rem | 700 | 1.2 | -0.03em | Page titles |
| H2 | 36px / 2.25rem | 600-700 | 1.25 | -0.02em | Section headings |
| H3 | 24px / 1.5rem | 600 | 1.3 | -0.01em | Card titles, subsections |
| H4 | 20px / 1.25rem | 600 | 1.4 | 0 | Small headings, labels |
| Body | 16-18px / 1rem | 400 | 1.6 | 0 | Paragraphs, descriptions |
| Small | 14px / 0.875rem | 400 | 1.5 | 0.01em | Secondary text, captions |
| Caption | 12px / 0.75rem | 500 | 1.4 | 0.02em | Labels, badges, metadata |

### Fluid Typography with clamp()

```css
/* Scales smoothly between mobile and desktop sizes */
.display-xl { font-size: clamp(2.5rem, 1.5rem + 5vw, 6rem); }
.display    { font-size: clamp(2rem, 1rem + 3.76vw, 4.5rem); }
.h1         { font-size: clamp(1.75rem, 1rem + 2.5vw, 3rem); }
.h2         { font-size: clamp(1.5rem, 1rem + 1.67vw, 2.25rem); }
.h3         { font-size: clamp(1.25rem, 1rem + 0.83vw, 1.5rem); }
```

### Typography Best Practices

- Use negative letter-spacing on display/h1/h2 — this is what makes headings feel "designed"
- Max line width: `max-width: 65ch` for body text readability
- Use `font-feature-settings: 'kern' 1, 'liga' 1` for professional kerning
- Mix weights within a heading for emphasis: "Build Faster With **Lumine** *Insights*"
- Italic accent words in heroes create visual interest without adding color
- Over 3D scenes, use `text-shadow` or a dark overlay to maintain readability

---

## Color Palette Construction

### Neutral Scale (11 stops)

```
50  — page backgrounds, subtle fills, light mode base
100 — alternate row backgrounds, hover states (light mode)
200 — borders, dividers, input outlines
300 — disabled states, subtle decorative elements
400 — placeholder text, muted icons
500 — secondary text, inactive nav items
600 — body text (dark mode primary text)
700 — headings, primary text (light mode)
800 — high-emphasis text, active states
900 — near-black, dark mode card backgrounds
950 — darkest backgrounds, dark mode page base
```

### Semantic Color Tokens

| Token | Light Mode | Dark Mode | Usage |
|-------|-----------|-----------|-------|
| primary | 600 | 400 | CTAs, links, active states |
| primary-hover | 700 | 300 | Hover on primary elements |
| primary-subtle | 50 | 950 | Tinted backgrounds, badges |
| success | green-600 | green-400 | Positive actions, growth |
| warning | amber-600 | amber-400 | Caution states |
| error | red-600 | red-400 | Errors, destructive actions |
| info | blue-600 | blue-400 | Informational elements |
| glow | primary @ 15% | primary @ 20% | 3D element glow emanation |

---

## Niche-Specific Palettes

### AI / SaaS Dark Theme

```css
--bg-primary: #050510;        /* Near-black with blue undertone */
--bg-secondary: #0a0a1a;      /* Slightly elevated surface */
--bg-card: #0f0f23;           /* Card backgrounds */
--accent-primary: #6366f1;    /* Indigo for CTAs */
--accent-secondary: #8b5cf6;  /* Purple for gradients */
--accent-glow: rgba(99, 102, 241, 0.15);   /* 3D glow effects */
--accent-emissive: #4f46e5;   /* Three.js emissive material */
--text-primary: #f1f5f9;      /* Primary text */
--text-secondary: #94a3b8;    /* Muted text */
--border: rgba(255, 255, 255, 0.08);        /* Subtle borders */
```

### Cybersecurity Dark

```css
--bg-primary: #020617;        /* Near-black slate */
--bg-secondary: #0f172a;      /* Dark blue-slate */
--bg-card: #1e293b;           /* Elevated card */
--accent-primary: #22d3ee;    /* Cyan for active/alert */
--accent-secondary: #06b6d4;  /* Variant cyan */
--accent-glow: rgba(34, 211, 238, 0.12);
--accent-emissive: #0891b2;
--accent-danger: #ef4444;     /* Threat indicators */
--text-primary: #e2e8f0;
--text-secondary: #64748b;
--border: rgba(34, 211, 238, 0.1);
```

### Creative Agency (Warm Dark)

```css
--bg-primary: #0a0806;        /* Warm near-black */
--bg-secondary: #1a1410;      /* Warm dark brown */
--bg-card: #1f1a14;           /* Card with warmth */
--accent-primary: #d4956a;    /* Copper/terracotta */
--accent-secondary: #e8c49a;  /* Gold/champagne */
--accent-glow: rgba(212, 149, 106, 0.12);
--accent-emissive: #b87333;
--text-primary: #faf5f0;      /* Warm white */
--text-secondary: #a89888;    /* Warm gray */
--border: rgba(212, 149, 106, 0.15);
```

### Fintech (Professional Light)

```css
--bg-primary: #ffffff;
--bg-secondary: #f8fafc;
--bg-card: #ffffff;
--accent-primary: #2563eb;    /* Professional blue */
--accent-secondary: #1e40af;
--accent-success: #16a34a;    /* Green for positive trends */
--accent-error: #dc2626;      /* Red for negative trends */
--text-primary: #0f172a;
--text-secondary: #64748b;
--border: #e2e8f0;
```

### Web3 / Blockchain Neon

```css
--bg-primary: #030014;        /* Deep violet-black */
--bg-secondary: #0d0628;      /* Dark purple */
--bg-card: #1a0f3c;           /* Elevated purple */
--accent-primary: #a855f7;    /* Vivid purple */
--accent-secondary: #ec4899;  /* Pink gradient pair */
--accent-glow: rgba(168, 85, 247, 0.2);
--accent-emissive: #7c3aed;
--text-primary: #f5f3ff;      /* Purple-tinted white */
--text-secondary: #a78bfa;    /* Light purple muted */
--border: rgba(168, 85, 247, 0.12);
```

### Gaming / Entertainment

```css
--bg-primary: #09090b;        /* True near-black */
--bg-secondary: #18181b;      /* Zinc-900 */
--bg-card: #27272a;           /* Zinc-800 */
--accent-primary: #f97316;    /* Orange energy */
--accent-secondary: #eab308;  /* Yellow highlight */
--accent-glow: rgba(249, 115, 22, 0.15);
--accent-emissive: #ea580c;
--text-primary: #fafafa;
--text-secondary: #a1a1aa;
--border: rgba(249, 115, 22, 0.1);
```

### Dark Mode Rules

- Never use pure black (#000000) — always add a subtle color undertone
- Reduce primary color saturation by 10–20% to prevent eye strain
- Elevate surface layers with slightly lighter backgrounds, not stronger shadows
- Card backgrounds should be 1–2 steps lighter than the page background
- Ensure minimum 4.5:1 contrast ratio for body text, 3:1 for large display text
- Use opacity-based borders (rgba white) not solid color borders
- For 3D scenes: dark backgrounds make emissive and bloom effects dramatically more effective

---

## Gradient and Glow Recipes

### Hero Background Gradients

```css
/* Deep space — AI/SaaS products */
background: radial-gradient(ellipse at 50% 0%, rgba(99,102,241,0.15) 0%, transparent 60%),
            radial-gradient(ellipse at 80% 50%, rgba(139,92,246,0.08) 0%, transparent 50%),
            #050510;

/* Warm agency — creative/portfolio */
background: radial-gradient(ellipse at 30% 20%, rgba(212,149,106,0.12) 0%, transparent 50%),
            radial-gradient(ellipse at 70% 80%, rgba(232,196,154,0.06) 0%, transparent 50%),
            #0a0806;

/* Cyber — security/network */
background: radial-gradient(ellipse at 50% 30%, rgba(34,211,238,0.1) 0%, transparent 50%),
            radial-gradient(ellipse at 20% 70%, rgba(6,182,212,0.05) 0%, transparent 40%),
            #020617;

/* Web3 — blockchain/neon */
background: radial-gradient(ellipse at 40% 20%, rgba(168,85,247,0.15) 0%, transparent 50%),
            radial-gradient(ellipse at 70% 60%, rgba(236,72,153,0.08) 0%, transparent 50%),
            #030014;
```

### Gradient Text

```css
.gradient-text {
  background: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #6366f1 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

/* Animated gradient text */
.gradient-text-animated {
  background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899, #6366f1);
  background-size: 300% 100%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: gradient-shift 4s ease-in-out infinite;
}

@keyframes gradient-shift {
  0%, 100% { background-position: 0% 50%; }
  50% { background-position: 100% 50%; }
}
```

### Glow Effects

```css
/* Button glow */
.btn-glow {
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.3),
              0 0 60px rgba(99, 102, 241, 0.1);
  transition: box-shadow 0.3s ease;
}
.btn-glow:hover {
  box-shadow: 0 0 30px rgba(99, 102, 241, 0.5),
              0 0 80px rgba(99, 102, 241, 0.2);
}

/* Card ambient glow */
.card-glow {
  position: relative;
}
.card-glow::before {
  content: '';
  position: absolute;
  inset: -1px;
  border-radius: inherit;
  background: linear-gradient(135deg, rgba(99,102,241,0.3), transparent, rgba(139,92,246,0.3));
  mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
  mask-composite: exclude;
  padding: 1px;
}

/* Section glow divider */
.glow-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(99,102,241,0.5), transparent);
}

/* 3D canvas backdrop glow */
.canvas-glow {
  filter: drop-shadow(0 0 40px rgba(99, 102, 241, 0.15));
}
```

---

## Glassmorphism Recipes

### Standard Glass Card

```css
.glass-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 16px;
}
```

### Elevated Glass Card (for featured items)

```css
.glass-card-elevated {
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3),
              inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
```

### Glass Navbar

```css
.glass-nav {
  background: rgba(5, 5, 16, 0.8);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}
```

### Glassmorphism over 3D Canvas

When placing glass cards over a Three.js canvas, the blur effect creates a natural depth separation. Use higher blur values (16–24px) and lower opacity backgrounds to let the 3D scene show through while maintaining text readability:

```css
.glass-over-canvas {
  background: rgba(5, 5, 16, 0.6);
  backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
```

---

## Spacing Scales

### Base Scale (4px unit)

| Token | Value | Common Usage |
|-------|-------|-------------|
| 1 | 4px | Icon gaps, tight internal padding |
| 2 | 8px | Button padding, badge padding |
| 3 | 12px | Input padding, small gaps |
| 4 | 16px | Card padding, mobile side margins |
| 5 | 20px | Component gaps |
| 6 | 24px | Section inner padding |
| 8 | 32px | Card padding (desktop), desktop side margins |
| 10 | 40px | Large component gaps |
| 12 | 48px | Section padding (mobile) |
| 16 | 64px | Medium section padding |
| 20 | 80px | Section padding (tablet) |
| 24 | 96px | Section padding (desktop) |
| 32 | 128px | Hero padding, large sections |

### Section Rhythm

```css
/* Consistent vertical rhythm for sections */
.section { padding: 96px 0; }                /* Desktop */
@media (max-width: 1024px) { .section { padding: 80px 0; } }  /* Tablet */
@media (max-width: 768px) { .section { padding: 48px 0; } }   /* Mobile */
```

---

## Shadow Systems

### Three-Level Shadow System

```css
/* Level 1 — Cards and elevated surfaces */
--shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.12),
             0 1px 2px rgba(0, 0, 0, 0.08);

/* Level 2 — Dropdowns, popovers, floating elements */
--shadow-md: 0 4px 12px rgba(0, 0, 0, 0.15),
             0 2px 4px rgba(0, 0, 0, 0.1);

/* Level 3 — Modals, drawers, overlays */
--shadow-lg: 0 12px 40px rgba(0, 0, 0, 0.25),
             0 4px 12px rgba(0, 0, 0, 0.15);
```

### Tinted Shadows (Premium Feel)

```css
/* Blue-tinted for AI/SaaS */
--shadow-tinted: 0 4px 20px rgba(99, 102, 241, 0.1),
                 0 1px 3px rgba(0, 0, 0, 0.1);

/* Warm-tinted for agencies */
--shadow-warm: 0 4px 20px rgba(212, 149, 106, 0.08),
               0 1px 3px rgba(0, 0, 0, 0.1);
```

---

## Border Radius Languages

| Style | Radius | Best For |
|-------|--------|----------|
| Sharp | 2–4px | Enterprise, fintech, data-dense apps |
| Soft | 8–12px | SaaS, modern tools, dashboards |
| Rounded | 16–24px | Consumer, creative, playful brands |
| Pill | 9999px | Badges, tags, small buttons |

Commit to one radius language throughout the entire design. Mixing sharp corners and fully rounded creates visual inconsistency.

---

## Responsive Breakpoints

### Tailwind Default System

| Token | Width | DPR | Usage |
|-------|-------|-----|-------|
| default | 0px | 1x | Mobile-first base styles |
| sm | 640px | 1x | Large phones, landscape |
| md | 768px | 1-2x | Tablets |
| lg | 1024px | 1-2x | Small laptops, landscape tablets |
| xl | 1280px | 1-2x | Desktops |
| 2xl | 1536px | 1-2x | Large displays, ultrawide |

### Content Width Constraints

```css
--max-width-content: 1200px;    /* Standard content sections */
--max-width-wide: 1440px;       /* Full-width hero, navbar */
--max-width-narrow: 720px;      /* Blog text, about sections */
```

---

## 3D Material Palettes

When building Three.js scenes, materials should mirror the 2D design system. This creates visual cohesion between the UI and 3D elements.

### AI / SaaS Material Set

```tsx
// Primary geometry — emissive accent
<meshStandardMaterial
  color="#1e1b4b"
  emissive="#6366f1"
  emissiveIntensity={0.4}
  roughness={0.3}
  metalness={0.7}
/>

// Secondary geometry — subtle complement
<meshStandardMaterial
  color="#0f0f23"
  emissive="#8b5cf6"
  emissiveIntensity={0.2}
  roughness={0.5}
  metalness={0.5}
/>

// Glass/transparent element
<meshPhysicalMaterial
  color="#ffffff"
  transmission={0.9}
  roughness={0.1}
  thickness={0.5}
  ior={1.5}
/>

// Wireframe accent
<meshBasicMaterial
  color="#6366f1"
  wireframe
  transparent
  opacity={0.3}
/>
```

### Cybersecurity Material Set

```tsx
// Shield / protection element
<meshStandardMaterial
  color="#0c4a6e"
  emissive="#22d3ee"
  emissiveIntensity={0.5}
  roughness={0.2}
  metalness={0.8}
/>

// Network node
<meshStandardMaterial
  color="#164e63"
  emissive="#06b6d4"
  emissiveIntensity={0.3}
  roughness={0.4}
  metalness={0.6}
/>

// Alert / threat element
<meshStandardMaterial
  color="#450a0a"
  emissive="#ef4444"
  emissiveIntensity={0.6}
  roughness={0.3}
  metalness={0.5}
/>
```

### Creative / Warm Material Set

```tsx
// Primary warm element
<meshStandardMaterial
  color="#44230a"
  emissive="#d4956a"
  emissiveIntensity={0.4}
  roughness={0.4}
  metalness={0.6}
/>

// Gold accent
<meshStandardMaterial
  color="#3d2800"
  emissive="#e8c49a"
  emissiveIntensity={0.3}
  roughness={0.2}
  metalness={0.9}
/>
```

### Material Best Practices

- Match emissive colors to your CSS accent palette for visual cohesion
- Use `emissiveIntensity` between 0.2–0.6 — higher creates nuclear glow
- Pair emissive materials with Bloom post-processing for cinematic effect
- `metalness` + low `roughness` creates reflective surfaces that interact with environment maps
- Use `MeshPhysicalMaterial` for glass/crystal — `transmission` + `ior` for realism
- Keep material count low (3–5 materials per scene) for GPU efficiency
