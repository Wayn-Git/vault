#!/usr/bin/env node
// img-to-ascii.mjs — Convert a PNG/JPG image to ASCII text.
//
// Usage:
//   node img-to-ascii.mjs <image> [--cols 120] [--invert] [--ramp " .:-=+*#%@"]
//
// Dependency: sharp (npm i sharp). Sharp decodes PNG/JPG/WebP and resizes.
//
// Notes:
//  - Applies monospace cell-aspect correction (cells are ~2x taller than wide),
//    so rows = cols * (imgH/imgW) * 0.5.
//  - Luminance uses sRGB perceptual weights (0.2126/0.7152/0.0722).

import sharp from 'sharp';

function parseArgs(argv) {
  const args = { cols: 120, invert: false, ramp: ' .:-=+*#%@', file: null };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--cols') args.cols = parseInt(argv[++i], 10);
    else if (a === '--invert') args.invert = true;
    else if (a === '--ramp') args.ramp = argv[++i];
    else if (!a.startsWith('--')) args.file = a;
  }
  return args;
}

async function main() {
  const { cols, invert, ramp, file } = parseArgs(process.argv);
  if (!file) {
    console.error('Usage: node img-to-ascii.mjs <image> [--cols N] [--invert] [--ramp "..."]');
    process.exit(1);
  }

  const CELL_ASPECT = 0.5; // monospace width:height
  const meta = await sharp(file).metadata();
  const rows = Math.max(1, Math.round(cols * (meta.height / meta.width) * CELL_ASPECT));

  // Resize to the character grid, drop alpha, get raw RGB bytes.
  const { data } = await sharp(file)
    .resize(cols, rows, { fit: 'fill' })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const last = ramp.length - 1;
  const lines = [];
  for (let y = 0; y < rows; y++) {
    let line = '';
    for (let x = 0; x < cols; x++) {
      const i = (y * cols + x) * 3;
      let lum = (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) / 255;
      if (invert) lum = 1 - lum;
      line += ramp[Math.round(lum * last)];
    }
    lines.push(line);
  }
  process.stdout.write(lines.join('\n') + '\n');
}

main().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
