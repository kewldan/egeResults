import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Font } from "takumi-js/node";

const dir = join(import.meta.dir, "..", "fonts");
const read = (file: string) => readFileSync(join(dir, file));

// Takumi has NO system-font fallback, and the design's named fonts
// (Space Grotesk / Space Mono) ship Latin only — they have zero Cyrillic
// glyphs. The cards are almost entirely Russian, so we register the named
// fonts for the Latin hero digits AND Cyrillic-capable companions
// (Manrope / JetBrains Mono) that the CSS font stacks fall back to.
export const fonts: Font[] = [
  { name: "Space Grotesk", data: read("SpaceGrotesk.ttf") }, // variable wght 300–700
  { name: "Manrope", data: read("Manrope.ttf") }, // variable, full Cyrillic — sans fallback
  { name: "Space Mono", data: read("SpaceMono-Regular.ttf"), weight: 400 },
  { name: "Space Mono", data: read("SpaceMono-Bold.ttf"), weight: 700 },
  { name: "JetBrains Mono", data: read("JetBrainsMono.ttf") }, // variable, Cyrillic — mono fallback
];

// Font stacks: named font first (Latin/digits), Cyrillic companion second.
export const SANS = "'Space Grotesk', 'Manrope', sans-serif";
export const MONO = "'Space Mono', 'JetBrains Mono', monospace";
