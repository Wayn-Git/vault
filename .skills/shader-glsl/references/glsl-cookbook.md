# GLSL Cookbook

Complete, copy-pasteable GLSL for noise, SDFs, palettes, domain warping, transitions, and Three.js wiring.

## Cosine palettes (Inigo Quilez)

`color = a + b * cos(2π * (c * t + d))`. Tune the four vec3s.
```glsl
vec3 palette(float t, vec3 a, vec3 b, vec3 c, vec3 d){
  return a + b * cos(6.28318 * (c * t + d));
}
// Pleasant default (rainbow-ish):
// a = vec3(0.5), b = vec3(0.5), c = vec3(1.0), d = vec3(0.0, 0.33, 0.67)
// Warm sunset: a=vec3(0.5,0.5,0.5) b=vec3(0.5,0.5,0.5) c=vec3(1.0,1.0,0.5) d=vec3(0.8,0.9,0.3)
```
Drive `t` with `length(p) + u_time * 0.2` for radial pulses, or `fbm(p)` for organic color fields.

## Hash and value noise

```glsl
float hash21(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }
vec2  hash22(vec2 p){
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return fract(sin(p) * 43758.5453);
}

float valueNoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
```

## Gradient (Perlin-style) noise

```glsl
float gradNoise(vec2 p){
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = dot(hash22(i)               * 2.0 - 1.0, f);
  float b = dot(hash22(i + vec2(1,0))   * 2.0 - 1.0, f - vec2(1,0));
  float c = dot(hash22(i + vec2(0,1))   * 2.0 - 1.0, f - vec2(0,1));
  float d = dot(hash22(i + vec2(1,1))   * 2.0 - 1.0, f - vec2(1,1));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y) * 0.5 + 0.5;
}
```

## Simplex noise 2D (Ashima / Gustavson, public domain)

```glsl
vec3 mod289(vec3 x){ return x - floor(x * (1.0/289.0)) * 289.0; }
vec2 mod289(vec2 x){ return x - floor(x * (1.0/289.0)) * 289.0; }
vec3 permute(vec3 x){ return mod289(((x * 34.0) + 1.0) * x); }

float snoise(vec2 v){
  const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                     -0.577350269189626, 0.024390243902439);
  vec2 i  = floor(v + dot(v, C.yy));
  vec2 x0 = v -   i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                         + i.x + vec3(0.0, i1.x, 1.0));
  vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
  m = m * m; m = m * m;
  vec3 x  = 2.0 * fract(p * C.www) - 1.0;
  vec3 h  = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x  = a0.x * x0.x  + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130.0 * dot(m, g);                          // range ~ -1..1
}
```

## fbm (fractal Brownian motion)

```glsl
float fbm(vec2 p){
  float v = 0.0, a = 0.5;
  mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);              // rotate each octave to hide grid
  for (int i = 0; i < 6; i++){
    v += a * snoise(p);
    p = rot * p * 2.0;
    a *= 0.5;
  }
  return v;
}
```

## Domain warping (fluid / marble)

```glsl
float warped(vec2 p, float t){
  vec2 q = vec2(fbm(p + vec2(0.0, 0.0)),
                fbm(p + vec2(5.2, 1.3)));
  vec2 r = vec2(fbm(p + 4.0 * q + vec2(1.7, 9.2) + 0.15 * t),
                fbm(p + 4.0 * q + vec2(8.3, 2.8) + 0.12 * t));
  return fbm(p + 4.0 * r);
}
```
Use the result both as a luminance/height field and to drive a palette: `vec3 col = palette(warped(p,t), ...);`.

## SDF shape library

All return signed distance (negative inside). Render with the AA mask below.
```glsl
float sdCircle(vec2 p, float r){ return length(p) - r; }
float sdBox(vec2 p, vec2 b){ vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
float sdRoundBox(vec2 p, vec2 b, float r){ return sdBox(p, b - r) - r; }
float sdSegment(vec2 p, vec2 a, vec2 b){
  vec2 pa = p - a, ba = b - a;
  float h = clamp(dot(pa, ba) / dot(ba, ba), 0.0, 1.0);
  return length(pa - ba * h);
}
float sdHexagon(vec2 p, float r){
  const vec3 k = vec3(-0.866025404, 0.5, 0.577350269);
  p = abs(p);
  p -= 2.0 * min(dot(k.xy, p), 0.0) * k.xy;
  p -= vec2(clamp(p.x, -k.z * r, k.z * r), r);
  return length(p) * sign(p.y);
}
// Boolean ops:
float opUnion(float a, float b){ return min(a, b); }
float opSubtract(float a, float b){ return max(-a, b); }
float opIntersect(float a, float b){ return max(a, b); }
float opSmoothUnion(float a, float b, float k){
  float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0);
  return mix(b, a, h) - k * h * (1.0 - h);
}
// Antialiased fill from a distance d:
float fill(float d){ float w = fwidth(d); return smoothstep(w, -w, d); }
```

## Image transition shaders (complete)

Shared uniforms: `sampler2D u_from, u_to; float u_progress;`. `vUv` is the 0..1 UV.

### Dissolve / noise wipe
```glsl
void main(){
  float n = valueNoise(vUv * 18.0);
  float t = smoothstep(u_progress - 0.08, u_progress + 0.08, n);
  gl_FragColor = mix(texture2D(u_to, vUv), texture2D(u_from, vUv), t);
}
```

### Displacement transition
```glsl
uniform sampler2D u_disp;
void main(){
  float d = texture2D(u_disp, vUv).r;
  vec2 uvFrom = vUv + vec2(d * u_progress * 0.4, 0.0);
  vec2 uvTo   = vUv - vec2(d * (1.0 - u_progress) * 0.4, 0.0);
  gl_FragColor = mix(texture2D(u_from, uvFrom),
                     texture2D(u_to,   uvTo), u_progress);
}
```

### Glitch + chromatic aberration
```glsl
uniform float u_time;
void main(){
  float block = floor(vUv.y * 24.0);
  float jump  = step(0.85, hash21(vec2(block, floor(u_time * 10.0))));
  float shift = (hash21(vec2(block, floor(u_time * 18.0))) - 0.5) * 0.12 * jump;
  vec2 uv = vUv + vec2(shift, 0.0);
  vec3 c;
  c.r = texture2D(u_from, uv + vec2(0.006, 0.0)).r;
  c.g = texture2D(u_from, uv).g;
  c.b = texture2D(u_from, uv - vec2(0.006, 0.0)).b;
  gl_FragColor = vec4(c, 1.0);
}
```

## Three.js wiring with textures

```js
import * as THREE from 'three';
const loader = new THREE.TextureLoader();
const uniforms = {
  u_from:     { value: loader.load('a.jpg') },
  u_to:       { value: loader.load('b.jpg') },
  u_disp:     { value: loader.load('disp.png') },
  u_progress: { value: 0 },
  u_time:     { value: 0 },
};
const mat = new THREE.ShaderMaterial({ uniforms, vertexShader: VERT, fragmentShader: FRAG });
// VERT passes UV:
const VERT = `
  varying vec2 vUv;
  void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
// Animate progress with GSAP or a tween:
// gsap.to(uniforms.u_progress, { value: 1, duration: 1.2, ease: 'power2.inOut' });
```
Set `texture.minFilter = THREE.LinearFilter` and `texture.generateMipmaps = false` for non-power-of-two source images to avoid black textures. For correct color, set `texture.colorSpace = THREE.SRGBColorSpace` and `renderer.outputColorSpace = THREE.SRGBColorSpace`.

## GLSL ES 3.00 migration (WebGL2)

Add `#version 300 es` as the **first line**, then:
- `attribute` → `in` (vertex), `varying` → `out`/`in`, `texture2D` → `texture`.
- Declare `out vec4 fragColor;` and write to it instead of `gl_FragColor`.
- Gains: `texelFetch`, `textureLod`, integer types, `flat` qualifiers, dynamic-length-safe loops still need constant bounds for unrolling on some drivers.
In Three.js, ShaderMaterial uses GLSL3 when you pass `glslVersion: THREE.GLSL3`.

## Mobile precision gotchas

- `mediump float` has ~10-bit mantissa; large UV coordinates (e.g. `uv * 1000.0`) lose precision and produce visible stepping. Use `highp` for noise domains or keep coordinates small.
- `fwidth` requires the `OES_standard_derivatives` extension in WebGL1 — enable with `#extension GL_OES_standard_derivatives : enable`. Always available in WebGL2.
- Render heavy fbm/domain-warp shaders to a half-resolution `WebGLRenderTarget` and upscale; the noise hides the resolution loss.

---
Build from noise, palettes, and SDFs and a fragment shader paints anything. Built by **[iart.ai](https://iart.ai/?utm_source=github&utm_medium=readme&utm_campaign=webgl-animation-skills&utm_content=skill_footer&utm_term=shader-glsl)** — the AI motion agent for editable, on-brand motion graphics.
