# ASCII Rendering Reference

Detailed tables, sampling math, and complete renderers for ASCII animation.

## Brightness ramp tables

Order is **dark → light**. Index into the ramp with `Math.round(lum * (ramp.length - 1))` where `lum` is 0..1.

### 10-level (compact, generative)
```
 .:-=+*#%@
```
Good for low-resolution generative fields and terminals. Distinct steps, low banding artifacts.

### 70-level Paul Bourke ramp (photo fidelity)
```
$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\|()1{}[]?-_+~<>i!lI;:,"^`'. 
```
This is ordered **light → dark** (densest first). For luminance mapping, either reverse the string or use `index = Math.round((1 - lum) * (len - 1))`. Best results for grayscale photos; whitespace at the end represents black/empty.

### 16-level extended (balance)
```
 .'`,^:";~-_+<>i!lI?/\|()1{}[]rcvunxzjftLCJUYXZO0Qoahkbdpqwm*WMB8&%$#@
```
Truncate or downsample to taste. For UI/loaders a hand-picked 8–12 char ramp usually looks cleaner than a 70-char ramp because the steps are visually distinct.

### Block / shade characters (Unicode, smoother gradient)
```
 ░▒▓█
```
Or with the 1/8 block fills for vertical bars: `▁▂▃▄▅▆▇█`. Renders as a near-continuous gradient in monospace fonts; great for waveforms, meters, and smooth fades. Requires a font with box-drawing glyphs (most monospace fonts have them).

## Luminance computation

Perceptual (sRGB-weighted, recommended):
```js
const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255; // 0..1
```
Fast average (acceptable for stylized output):
```js
const lum = (r + g + b) / (3 * 255);
```
Invert for dark-on-light surfaces: `lum = 1 - lum`. Apply gamma to spread midtones: `lum = Math.pow(lum, 0.8)` (lower exponent brightens).

## Pixel sampling and cell aspect correction

Monospace cells are about twice as tall as wide. Real cell aspect depends on the font: measure once.

```js
function measureCellAspect(fontFamily = 'monospace', fontPx = 16) {
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  ctx.font = `${fontPx}px ${fontFamily}`;
  const w = ctx.measureText('M').width;           // glyph advance width
  const h = fontPx * 1.0;                          // with line-height: 1
  return w / h;                                    // ~0.5 for most fonts
}
```

Compute the character grid for a source image, correcting aspect so the picture is not vertically stretched:
```js
function gridSize(imgW, imgH, cols, cellAspect = 0.5) {
  const rows = Math.round(cols * (imgH / imgW) * cellAspect);
  return { cols, rows };
}
```
Draw the source into an offscreen canvas at exactly `cols × rows`, then read all pixels once with `getImageData(0, 0, cols, rows)`. One `getImageData` call per frame is far cheaper than per-pixel reads.

## `<pre>` vs canvas

| Aspect | `<pre>` + textContent | Canvas `fillText` |
|--------|----------------------|-------------------|
| Setup  | trivial, one string  | per-cell draw loop |
| Color  | single color (or per-span, slow) | per-char color cheap |
| Max size | ~120×60 @ 30fps    | thousands of cells @ 60fps |
| Selectable text | yes           | no |
| Best for | generative fields, loaders | video, per-char color, large grids |

`<pre>` styling that avoids gaps and stretching:
```css
pre { font-family: ui-monospace, monospace; line-height: 1; letter-spacing: 0;
      margin: 0; white-space: pre; }
```

Canvas per-char color renderer:
```js
function drawAsciiCanvas(ctx, chars, colors, cols, rows, cellW, cellH) {
  ctx.clearRect(0, 0, cols * cellW, rows * cellH);
  ctx.textBaseline = 'top';
  ctx.font = `${cellH}px monospace`;
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      const i = y * cols + x;
      ctx.fillStyle = colors[i];                   // e.g. `rgb(r,g,b)`
      ctx.fillText(chars[i], x * cellW, y * cellH);
    }
  }
}
```

## ANSI terminal frame loop (Node)

```js
const ESC = '\x1b[';
const out = process.stdout;

function start(render, fps = 20) {
  out.write(ESC + '?25l');                          // hide cursor
  out.write(ESC + '2J');                            // clear screen once
  const interval = 1000 / fps;
  let start = Date.now();
  const id = setInterval(() => {
    const t = Date.now() - start;
    out.write(ESC + 'H');                           // home (cheap, no full clear)
    out.write(render(t, out.columns || 80, out.rows || 24));
  }, interval);
  const stop = () => {
    clearInterval(id);
    out.write(ESC + '0m' + ESC + '?25h' + ESC + '2J' + ESC + 'H');
    process.exit(0);
  };
  process.on('SIGINT', stop);
  return stop;
}

// Truecolor per character: foreground `\x1b[38;2;R;G;Bm`, reset `\x1b[0m`.
function colored(ch, r, g, b) {
  return `${ESC}38;2;${r};${g};${b}m${ch}${ESC}0m`;
}

// Example: plasma using full terminal size
start((t, cols, rows) => {
  const ramp = ' .:-=+*#%@';
  let s = '';
  for (let y = 0; y < rows - 1; y++) {
    for (let x = 0; x < cols; x++) {
      const v = Math.sin(x * 0.15 + t * 0.001)
              + Math.sin(y * 0.25 + t * 0.0015)
              + Math.sin((x + y) * 0.1 + t * 0.0008);
      const lum = (v + 3) / 6;
      s += ramp[Math.round(lum * (ramp.length - 1))];
    }
    s += '\n';
  }
  return s;
});
```
Notes: writing `ESC + 'H'` (home) and overwriting is much smoother than clearing the screen every frame, which causes flicker. Avoid printing a trailing newline on the last row or the terminal scrolls. `out.columns`/`out.rows` give the live terminal size; recompute the grid on `process.stdout.on('resize', ...)`.

## Three.js AsciiEffect — complete wiring

```js
import * as THREE from 'three';
import { AsciiEffect } from 'three/addons/effects/AsciiEffect.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const renderer = new THREE.WebGLRenderer();
renderer.setSize(innerWidth, innerHeight);

const effect = new AsciiEffect(renderer, ' .:-=+*#%@', { invert: true, resolution: 0.2 });
effect.setSize(innerWidth, innerHeight);
effect.domElement.style.color = 'white';
effect.domElement.style.backgroundColor = 'black';
document.body.appendChild(effect.domElement);      // append the EFFECT's DOM, not renderer.domElement

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(70, innerWidth / innerHeight, 1, 1000);
camera.position.z = 4;
scene.add(new THREE.PointLight(0xffffff, 3).position.set(5, 5, 5));
scene.add(new THREE.AmbientLight(0x808080));
const mesh = new THREE.Mesh(
  new THREE.TorusKnotGeometry(1, 0.3, 100, 16),
  new THREE.MeshStandardMaterial({ flatShading: true })
);
scene.add(mesh);

const controls = new OrbitControls(camera, effect.domElement); // attach to effect DOM

function animate(t) {
  mesh.rotation.y = t * 0.0005;
  effect.render(scene, camera);                    // render through the effect
  requestAnimationFrame(animate);
}
requestAnimationFrame(animate);

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  effect.setSize(innerWidth, innerHeight);
});
```
Key gotchas: append `effect.domElement` (not the renderer's canvas) and call `effect.render`, not `renderer.render`. `resolution` (default ~0.15) controls character density; lower = fewer, larger characters. Lighting matters — ASCII reads luminance, so use strong directional contrast and `flatShading` for crisp edges.

---
Map brightness to the right glyph ramp and the characters come alive. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=web-animation-skills&utm_content=skill_footer&utm_term=ascii-animation)** — the AI motion agent for editable, on-brand motion graphics.
