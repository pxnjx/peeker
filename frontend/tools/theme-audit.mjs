/**
 * Theme audit: reads the token blocks out of app/tokens.css and checks them as numbers.
 *
 * The dark surface ramp in this app is hand-tuned, which means it can drift back to a flat,
 * unreadable state without anyone noticing between design reviews. This script is the check:
 * every contrast pair the rules promise, and the perceptual step between the surfaces that
 * R5's elevation is supposed to be built from.
 *
 * Run:  npm run theme:audit
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const CSS = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "app", "tokens.css"), "utf8");

/* ---------- colour maths (sRGB, WCAG 2.2 relative luminance, CIE L*) ---------- */

function parseColor(input) {
  const value = input.trim();
  const hex = /^#([\da-f]{3,8})$/i.exec(value);
  if (hex) {
    let body = hex[1];
    if (body.length === 3) body = [...body].map((c) => c + c).join("");
    const parts = body.match(/.{2}/g).map((pair) => Number.parseInt(pair, 16));
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] / 255 : 1 };
  }
  const fn = /^rgba?\(([^)]+)\)$/i.exec(value);
  if (fn) {
    const nums = fn[1].split(/[,/]/).map((part) => Number.parseFloat(part));
    return { r: nums[0], g: nums[1], b: nums[2], a: nums.length > 3 ? nums[3] : 1 };
  }
  return null;
}

/** Flatten a translucent colour onto an opaque one, the way the browser paints it. */
function over(fg, bg) {
  const mix = (x, y) => x * fg.a + y * (1 - fg.a);
  return { r: mix(fg.r, bg.r), g: mix(fg.g, bg.g), b: mix(fg.b, bg.b), a: 1 };
}

const channel = (byte) => {
  const c = byte / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};

function luminance(color) {
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

function contrast(fg, bg) {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** Perceptual lightness, the axis dark-mode elevation is actually built on. */
function lightness(color) {
  const y = luminance(color);
  return y > 0.008856 ? 116 * y ** (1 / 3) - 16 : 903.3 * y;
}

/* ---------- token extraction ---------- */

function tokensOf(selector) {
  const clean = CSS.replace(/\/\*[\s\S]*?\*\//g, "");  // the header comment names these selectors
  const start = clean.indexOf(selector);
  if (start === -1) throw new Error(`missing block: ${selector}`);
  const open = clean.indexOf("{", start);
  const close = clean.indexOf("}", open);
  const body = clean.slice(open + 1, close);
  const out = {};
  for (const line of body.split("\n")) {
    const match = /^\s*(--[\w-]+):\s*([^;]+);/.exec(line);
    if (match) out[match[1]] = match[2].trim();
  }
  return out;
}

/* ---------- the promises the tokens make ---------- */

/* Text roles: [foreground, backgrounds it is painted on, minimum ratio, where it appears]. */
const TEXT_PAIRS = [
  ["--text", ["--panel", "--bg", "--panel-2", "--panel-hover"], 4.5, "body copy"],
  ["--muted", ["--panel", "--bg", "--panel-2"], 4.5, "secondary text"],
  ["--faint", ["--panel", "--panel-2"], 4.5, "meta, 11-12px"],
  ["--accent", ["--panel", "--bg"], 4.5, "links (R1)"],
  ["--on-btn", ["--btn-bg", "--btn-bg-hover", "--btn-bg-press"], 4.5, "primary CTA label"],
  ["--on-accent", ["--accent", "--accent-hover", "--accent-press"], 4.5, "accent chip label"],
  ["--on-amber", ["--amber"], 4.5, "warning CTA label"],
];

/* R2 status hues, always seen as a label on their own soft tint (badges, banners, tags). */
const HUE_PAIRS = [
  ["--green", "--green-soft"],
  ["--amber", "--amber-soft"],
  ["--orange", "--orange-soft"],
  ["--red", "--red-soft"],
  ["--status-neutral", "--chip"],
  ["--tag-own-text", "--tag-own-bg"],
];

/* Elevation. R5 is explicit that only dark has to lean on the surface ramp - a shadow
   on a near-black page is invisible. Light separates with the hairline plus a real
   shadow, so its page-vs-card check is the shadow, not the L* step. */
const RAMP = [
  ["--bg", "--panel", 4, "page vs card", ["dark"]],
  ["--panel", "--panel-2", 2.5, "card vs inset", ["dark", "light"]],
  ["--panel", "--border", 5, "card vs hairline", ["dark", "light"]],
];

/* Light-mode labels that measured below 4.5:1 on their tinted ground when this audit was
   written. Every one has since been darkened into AA, so the set is empty: it stays as the
   place a deliberate exception would be recorded, and anything new that slips under 4.5
   fails outright instead of joining a permanent list of warnings. */
const KNOWN = new Set([]);

const themes = [
  ["light", tokensOf(":root")],
  ["dark", tokensOf('[data-theme="dark"]')],
];

let failures = 0;

function cell(tokens, name) {
  const raw = tokens[name];
  const color = raw ? parseColor(raw) : null;
  if (!color) throw new Error(`unparsable token ${name}: ${raw}`);
  return color;
}

function row(mark, ratio, minimum, label, status) {
  if (status === "fail") failures += 1;
  // Contrast minimums read as 4.5; the elevation minimums are single digits or fractions,
  // so round to whatever precision the rule itself is written at rather than to one step.
  const shown = Number.isInteger(minimum) ? minimum.toFixed(1) : `${minimum}`;
  console.log(`  ${mark}  ${ratio.padEnd(22)} ${label} (min ${shown})`);
}

for (const [name, tokens] of themes) {
  console.log(`\n${name.toUpperCase()} MODE`);
  for (const [fg, backgrounds, minimum, label] of TEXT_PAIRS) {
    for (const bg of backgrounds) {
      const ratio = contrast(cell(tokens, fg), cell(tokens, bg));
      const pass = ratio >= minimum;
      row(pass ? "ok  " : "FAIL", `${ratio.toFixed(2)}:1  ${fg} on ${bg}`, minimum, label, pass ? "pass" : "fail");
    }
  }

  for (const [hue, tint] of HUE_PAIRS) {
    const ground = over(cell(tokens, tint), cell(tokens, "--panel"));
    const ratio = contrast(cell(tokens, hue), ground);
    const status = ratio >= 4.5 ? "pass" : KNOWN.has(`${name}:${hue}`) ? "warn" : "fail";
    row({ pass: "ok  ", warn: "warn", fail: "FAIL" }[status], `${ratio.toFixed(2)}:1  ${hue} on ${tint}`, 4.5, "status label", status);
  }

  for (const [lower, higher, minimum, label, applicable] of RAMP) {
    if (!applicable.includes(name)) continue;
    const delta = Math.abs(lightness(cell(tokens, higher)) - lightness(cell(tokens, lower)));
    const status = delta >= minimum ? "pass" : "fail";
    row({ pass: "ok  ", warn: "warn", fail: "FAIL" }[status], `dL* ${delta.toFixed(1)}      ${lower} -> ${higher}`, minimum, label, status);
  }

  if (name === "light") {
    // Light has the opposite obligation of R5: the page/card step is carried by the
    // level-1 shadow, so that token has to actually cast something.
    const shadow = tokens["--shadow-card"] ?? "";
    const alphas = [...shadow.matchAll(/rgba\([^)]*,\s*(0?\.\d+|1)\s*\)/g)].map((m) => Number(m[1]));
    const strongest = alphas.length ? Math.max(...alphas) : 0;
    const pass = strongest >= 0.05;
    row(pass ? "ok  " : "FAIL", `alpha ${strongest.toFixed(2)}    --shadow-card`, 0.05, "card elevation", pass ? "pass" : "fail");
  }
}

console.log(failures ? `\n${failures} contrast problem(s)\n` : "\ncontrast checks passed\n");
process.exit(failures ? 1 : 0);

