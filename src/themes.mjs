/**
 * Built-in themes and custom theme loading.
 * Adapted from claude-replay with an additional Snowflake theme.
 */

import { readFileSync } from "node:fs";

const THEME_VARS = [
  "bg", "bg-surface", "bg-hover",
  "text", "text-dim", "text-bright",
  "accent", "accent-dim",
  "green", "blue", "orange", "red", "cyan",
  "border", "tool-bg", "thinking-bg",
];

const BUILTIN_THEMES = {
  "snowflake": {
    "bg": "#0f1923",
    "bg-surface": "#172330",
    "bg-hover": "#1e2d3d",
    "text": "#c8d6e5",
    "text-dim": "#5a7a97",
    "text-bright": "#e8f0f8",
    "accent": "#29b5e8",
    "accent-dim": "#1a8ab5",
    "green": "#56d89e",
    "blue": "#29b5e8",
    "orange": "#f0a030",
    "red": "#e85454",
    "cyan": "#29b5e8",
    "border": "#253546",
    "tool-bg": "#0c1620",
    "thinking-bg": "#0e1820",
  },
  "tokyo-night": {
    "bg": "#1a1b26",
    "bg-surface": "#24253a",
    "bg-hover": "#2f3147",
    "text": "#c0caf5",
    "text-dim": "#565f89",
    "text-bright": "#e0e6ff",
    "accent": "#bb9af7",
    "accent-dim": "#7957a8",
    "green": "#9ece6a",
    "blue": "#7aa2f7",
    "orange": "#ff9e64",
    "red": "#f7768e",
    "cyan": "#7dcfff",
    "border": "#3b3d57",
    "tool-bg": "#1e1f33",
    "thinking-bg": "#1c1d2e",
  },
  "monokai": {
    "bg": "#272822",
    "bg-surface": "#2d2e27",
    "bg-hover": "#3e3d32",
    "text": "#f8f8f2",
    "text-dim": "#75715e",
    "text-bright": "#ffffff",
    "accent": "#ae81ff",
    "accent-dim": "#7c5cbf",
    "green": "#a6e22e",
    "blue": "#66d9ef",
    "orange": "#fd971f",
    "red": "#f92672",
    "cyan": "#66d9ef",
    "border": "#49483e",
    "tool-bg": "#1e1f1c",
    "thinking-bg": "#1c1d1a",
  },
  "solarized-dark": {
    "bg": "#002b36",
    "bg-surface": "#073642",
    "bg-hover": "#0a4050",
    "text": "#839496",
    "text-dim": "#586e75",
    "text-bright": "#fdf6e3",
    "accent": "#6c71c4",
    "accent-dim": "#4e5299",
    "green": "#859900",
    "blue": "#268bd2",
    "orange": "#cb4b16",
    "red": "#dc322f",
    "cyan": "#2aa198",
    "border": "#094959",
    "tool-bg": "#012934",
    "thinking-bg": "#012730",
  },
  "github-light": {
    "bg": "#ffffff",
    "bg-surface": "#f6f8fa",
    "bg-hover": "#eaeef2",
    "text": "#1f2328",
    "text-dim": "#656d76",
    "text-bright": "#000000",
    "accent": "#8250df",
    "accent-dim": "#6639ba",
    "green": "#1a7f37",
    "blue": "#0969da",
    "orange": "#bc4c00",
    "red": "#cf222e",
    "cyan": "#0598bc",
    "border": "#d0d7de",
    "tool-bg": "#f6f8fa",
    "thinking-bg": "#f0f3f6",
  },
  "dracula": {
    "bg": "#282a36",
    "bg-surface": "#2d2f3d",
    "bg-hover": "#383a4a",
    "text": "#f8f8f2",
    "text-dim": "#6272a4",
    "text-bright": "#ffffff",
    "accent": "#bd93f9",
    "accent-dim": "#9571d1",
    "green": "#50fa7b",
    "blue": "#8be9fd",
    "orange": "#ffb86c",
    "red": "#ff5555",
    "cyan": "#8be9fd",
    "border": "#44475a",
    "tool-bg": "#21222c",
    "thinking-bg": "#1e1f29",
  },
};

/**
 * Get a built-in theme by name.
 * @param {string} name
 * @returns {Record<string, string>}
 */
export function getTheme(name) {
  if (!(name in BUILTIN_THEMES)) {
    const available = Object.keys(BUILTIN_THEMES).sort().join(", ");
    throw new Error(`Unknown theme '${name}'. Available: ${available}`);
  }
  return BUILTIN_THEMES[name];
}

/**
 * Load a custom theme from a JSON file.
 * Missing keys are filled from snowflake defaults.
 * @param {string} filePath
 * @returns {Record<string, string>}
 */
export function loadThemeFile(filePath) {
  const raw = readFileSync(filePath, "utf-8");
  const custom = JSON.parse(raw);
  if (typeof custom !== "object" || custom === null || Array.isArray(custom)) {
    throw new Error(`Theme file must be a JSON object`);
  }
  return { ...BUILTIN_THEMES["snowflake"], ...custom };
}

/**
 * Convert a theme dict to a CSS :root block.
 * @param {Record<string, string>} theme
 * @returns {string}
 */
export function themeToCss(theme) {
  const lines = [];
  for (const v of THEME_VARS) {
    if (v in theme) lines.push(`  --${v}: ${theme[v]};`);
  }
  let css = ":root {\n" + lines.join("\n") + "\n}";
  if (theme.extraCss) css += "\n" + theme.extraCss;
  return css;
}

/**
 * Return sorted list of built-in theme names.
 * @returns {string[]}
 */
export function listThemes() {
  return Object.keys(BUILTIN_THEMES).sort();
}
