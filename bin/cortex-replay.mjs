#!/usr/bin/env node

/**
 * CLI entry point for cortex-replay.
 * Converts Cortex Code session JSON files into interactive HTML replays.
 */

import { parseArgs } from "node:util";
import { basename, dirname, join, resolve } from "node:path";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { parseSession, filterTurns } from "../src/parser.mjs";
import { render } from "../src/renderer.mjs";
import { getTheme, loadThemeFile, listThemes } from "../src/themes.mjs";

const DEFAULT_SESSION_DIR = join(homedir(), ".snowflake", "cortex", "conversations");

const options = {
  output: { type: "string", short: "o" },
  turns: { type: "string" },
  from: { type: "string" },
  to: { type: "string" },
  speed: { type: "string", default: "1" },
  "no-thinking": { type: "boolean", default: false },
  "no-tool-calls": { type: "boolean", default: false },
  theme: { type: "string", default: "snowflake" },
  "theme-file": { type: "string" },
  "list-themes": { type: "boolean", default: false },
  "no-redact": { type: "boolean", default: false },
  title: { type: "string" },
  "user-label": { type: "string", default: "User" },
  "assistant-label": { type: "string", default: "Cortex Code" },
  mark: { type: "string", multiple: true },
  bookmarks: { type: "string" },
  "no-animate": { type: "boolean", default: false },
  "no-compress": { type: "boolean", default: false },
  "session-dir": { type: "string" },
  "list-sessions": { type: "boolean", default: false },
  last: { type: "boolean", default: false },
  help: { type: "boolean", short: "h", default: false },
};

let parsed;
try {
  parsed = parseArgs({ options, allowPositionals: true });
} catch (e) {
  console.error(`Error: ${e.message}`);
  process.exit(1);
}

const { values, positionals } = parsed;

if (values.help) {
  console.log(`Usage: cortex-replay <session.json> [options]
       cortex-replay --last [options]
       cortex-replay --list-sessions

Convert Cortex Code session transcripts into embeddable HTML replays.

Options:
  -o, --output FILE       Output HTML file (default: stdout)
  --last                  Use the most recent session
  --list-sessions         List available sessions and exit
  --session-dir DIR       Session directory (default: ~/.snowflake/cortex/conversations)
  --turns N-M             Only include turns N through M
  --from TIMESTAMP        Start time filter (ISO 8601)
  --to TIMESTAMP          End time filter (ISO 8601)
  --speed N               Initial playback speed (default: 1.0)
  --no-thinking           Hide thinking blocks by default
  --no-tool-calls         Hide tool call blocks by default
  --title TEXT            Page title (default: from session title)
  --no-redact             Disable secret redaction in output
  --no-animate            Disable typewriter animation (use classic instant-reveal)
  --theme NAME            Built-in theme (default: snowflake)
  --theme-file FILE       Custom theme JSON file (overrides --theme)
  --user-label NAME       Label for user messages (default: User)
  --assistant-label NAME  Label for assistant messages (default: Cortex Code)
  --mark "N:Label"        Add a bookmark at turn N (repeatable)
  --bookmarks FILE        JSON file with bookmarks [{turn, label}]
  --no-compress           Embed raw JSON instead of compressed
  --list-themes           List available built-in themes and exit
  -h, --help              Show this help message`);
  process.exit(0);
}

if (values["list-themes"]) {
  for (const name of listThemes()) {
    console.log(name);
  }
  process.exit(0);
}

// --- Session discovery ---
const sessionDir = values["session-dir"] || DEFAULT_SESSION_DIR;

/**
 * Read minimal metadata from a session file without parsing the full history.
 */
function readSessionInfo(filePath) {
  try {
    const raw = readFileSync(filePath, "utf-8");
    const data = JSON.parse(raw);
    return {
      id: data.session_id || basename(filePath, ".json"),
      title: (data.title || "(untitled)").replace(/<[^>]+>/g, "").trim() || "(untitled)",
      created_at: data.created_at || "",
      last_updated: data.last_updated || "",
      turns: Array.isArray(data.history) ? data.history.filter(h => h.role === "user").length : 0,
      file: filePath,
    };
  } catch {
    return null;
  }
}

if (values["list-sessions"]) {
  if (!existsSync(sessionDir)) {
    console.error(`Session directory not found: ${sessionDir}`);
    process.exit(1);
  }

  const files = readdirSync(sessionDir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => join(sessionDir, f));

  const sessions = files
    .map(readSessionInfo)
    .filter(Boolean)
    .sort((a, b) => {
      const da = a.last_updated || a.created_at;
      const db = b.last_updated || b.created_at;
      return db.localeCompare(da); // newest first
    });

  if (sessions.length === 0) {
    console.error("No sessions found.");
    process.exit(0);
  }

  // Print table
  const idW = 12;
  const titleW = 50;
  const dateW = 20;

  console.log(
    "ID".padEnd(idW) + "  " +
    "Title".padEnd(titleW) + "  " +
    "Last Updated".padEnd(dateW) + "  " +
    "Turns"
  );
  console.log("-".repeat(idW + titleW + dateW + 12));

  for (const s of sessions) {
    const id = s.id.substring(0, idW);
    const title = s.title.length > titleW ? s.title.substring(0, titleW - 3) + "..." : s.title;
    const date = (s.last_updated || s.created_at || "").substring(0, dateW);
    console.log(
      id.padEnd(idW) + "  " +
      title.padEnd(titleW) + "  " +
      date.padEnd(dateW) + "  " +
      s.turns
    );
  }
  process.exit(0);
}

// --- Resolve input file ---
let inputFile;

if (values.last) {
  // Read .last-session pointer
  const lastFile = join(sessionDir, ".last-session");
  if (!existsSync(lastFile)) {
    console.error("No .last-session file found. Try specifying a session file directly.");
    process.exit(1);
  }
  const lastId = readFileSync(lastFile, "utf-8").trim();
  const candidate = join(sessionDir, lastId + ".json");
  if (existsSync(candidate)) {
    inputFile = candidate;
  } else {
    // Try finding it in subdirectories
    const found = findSession(lastId);
    if (found) {
      inputFile = found;
    } else {
      console.error(`Last session not found: ${lastId}`);
      process.exit(1);
    }
  }
} else {
  inputFile = positionals[0];
  if (!inputFile) {
    // Try partial session ID match
    console.error("Error: input file is required. Usage: cortex-replay <session.json> [options]");
    console.error("       cortex-replay --last     (use most recent session)");
    console.error("       cortex-replay --list-sessions  (list all sessions)");
    process.exit(1);
  }

  // If it's not a file path, try as session ID
  if (!existsSync(inputFile)) {
    const found = findSession(inputFile);
    if (found) {
      inputFile = found;
    } else {
      console.error(`Error: file not found: ${inputFile}`);
      process.exit(1);
    }
  }
}

/**
 * Find a session file by partial ID match.
 */
function findSession(query) {
  if (!existsSync(sessionDir)) return null;
  const files = readdirSync(sessionDir).filter((f) => f.endsWith(".json"));
  // Exact match
  const exact = files.find((f) => f === query + ".json");
  if (exact) return join(sessionDir, exact);
  // Partial match
  const matches = files.filter((f) => f.startsWith(query));
  if (matches.length === 1) return join(sessionDir, matches[0]);
  if (matches.length > 1) {
    console.error(`Ambiguous session ID '${query}'. Matches:`);
    for (const m of matches) console.error("  " + m);
    process.exit(1);
  }
  // Check subdirectories
  const dirs = readdirSync(sessionDir, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);
  for (const dir of dirs) {
    const subFiles = readdirSync(join(sessionDir, dir)).filter((f) => f.endsWith(".json"));
    const sub = subFiles.find((f) => f.startsWith(query));
    if (sub) return join(sessionDir, dir, sub);
  }
  return null;
}

// --- Resolve theme ---
let theme;
if (values["theme-file"]) {
  if (!existsSync(values["theme-file"])) {
    console.error(`Error: theme file not found: ${values["theme-file"]}`);
    process.exit(1);
  }
  try {
    theme = loadThemeFile(values["theme-file"]);
  } catch (e) {
    console.error(`Error loading theme file: ${e.message}`);
    process.exit(1);
  }
} else {
  try {
    theme = getTheme(values.theme);
  } catch (e) {
    console.error(`Error: ${e.message}`);
    process.exit(1);
  }
}

// --- Parse turn range ---
let turnRange;
if (values.turns) {
  const parts = values.turns.split("-");
  if (parts.length !== 2) {
    console.error(`Error: invalid turn range '${values.turns}' (expected N-M)`);
    process.exit(1);
  }
  const start = parseInt(parts[0], 10);
  const end = parseInt(parts[1], 10);
  if (isNaN(start) || isNaN(end)) {
    console.error(`Error: invalid turn range '${values.turns}' (expected integers)`);
    process.exit(1);
  }
  turnRange = [start, end];
}

// --- Parse and filter ---
let sessionData;
try {
  sessionData = parseSession(inputFile);
} catch (e) {
  console.error(`Error parsing session: ${e.message}`);
  process.exit(1);
}

let { turns, meta } = sessionData;

turns = filterTurns(turns, {
  turnRange,
  timeFrom: values.from,
  timeTo: values.to,
});

if (turns.length === 0) {
  console.error("Warning: no turns found after filtering.");
}

const speed = parseFloat(values.speed) || 1.0;

// --- Title ---
let title = values.title;
if (!title) {
  title = meta.title ? "Replay — " + meta.title : "Cortex Code Replay";
}

// --- Parse bookmarks ---
let bookmarks = [];

if (values.mark) {
  for (const m of values.mark) {
    const sep = m.indexOf(":");
    if (sep === -1) {
      console.error(`Error: invalid --mark format '${m}' (expected N:Label)`);
      process.exit(1);
    }
    const turn = parseInt(m.slice(0, sep), 10);
    const label = m.slice(sep + 1);
    if (isNaN(turn)) {
      console.error(`Error: invalid turn number in --mark '${m}'`);
      process.exit(1);
    }
    bookmarks.push({ turn, label });
  }
}

if (values.bookmarks) {
  if (!existsSync(values.bookmarks)) {
    console.error(`Error: bookmarks file not found: ${values.bookmarks}`);
    process.exit(1);
  }
  try {
    const data = JSON.parse(readFileSync(values.bookmarks, "utf-8"));
    if (!Array.isArray(data)) {
      console.error("Error: bookmarks file must contain a JSON array");
      process.exit(1);
    }
    for (const item of data) {
      if (typeof item.turn !== "number" || typeof item.label !== "string") {
        console.error(`Error: each bookmark must have numeric 'turn' and string 'label'`);
        process.exit(1);
      }
      bookmarks.push({ turn: item.turn, label: item.label });
    }
  } catch (e) {
    if (e.message.startsWith("Error:")) throw e;
    console.error(`Error: failed to parse bookmarks file: ${e.message}`);
    process.exit(1);
  }
}

bookmarks.sort((a, b) => a.turn - b.turn);

// --- Render ---
const html = render(turns, {
  speed,
  showThinking: !values["no-thinking"],
  showToolCalls: !values["no-tool-calls"],
  theme,
  redactSecrets: !values["no-redact"],
  userLabel: values["user-label"],
  assistantLabel: values["assistant-label"],
  title,
  bookmarks,
  compress: !values["no-compress"],
  meta,
  animate: !values["no-animate"],
});

if (values.output) {
  writeFileSync(values.output, html);
  console.error(`Wrote ${values.output} (${turns.length} turns, ${meta.title || "untitled"})`);
} else {
  process.stdout.write(html);
}
