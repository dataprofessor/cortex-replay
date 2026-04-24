---
name: cortex-replay
description: "Generate interactive HTML replays from Cortex Code sessions. Use when: user wants to create a replay, share a session, export a session as HTML, record a demo, make a screencast, list sessions. Triggers: replay, session replay, share session, export session, HTML replay, cortex-replay, record session, session demo, shareable session."
tools: ["Bash", "Read", "Write"]
---

# cortex-replay

Generate self-contained, interactive HTML replays from Cortex Code session transcripts using the bundled Python script.

## Prerequisites

**None.** This skill is fully self-contained -- it uses only Python 3 stdlib (no external dependencies, no npm, no Node.js).

The replay script is bundled at `<SKILL_DIR>/scripts/replay.py`. Run it directly using its absolute path -- no installation needed.

Determine the script path by resolving `<SKILL_DIR>` to the actual skill directory. For local skills this is typically `~/.cortex/skills/cortex-replay/scripts/replay.py` or `~/.snowflake/cortex/skills/cortex-replay/scripts/replay.py`. For stage-deployed skills, check the cached path.

**Quick check:**

```bash
python3 <SKILL_DIR>/scripts/replay.py --help
```

## Workflow

### 1. Determine what the user wants

Ask if needed:
- **Which session?** Options: `--last` (most recent), a session ID, or a file path
- **Output file?** Default: `replay.html` in the current working directory
- **Any customizations?** Theme, turn range, bookmarks, speed, hide thinking/tools

If the user just says "create a replay" or "replay my session" without specifics, default to `--last` with the `snowflake` theme.

### 2. List sessions (if user needs to pick one)

```bash
python3 <SKILL_DIR>/scripts/replay.py --list-sessions
```

This shows all sessions with IDs, titles, timestamps, and turn counts. Help the user pick the right one. Partial ID matching works (e.g., `6868f059` matches `6868f059-3b8a-423d-8a51-ef0397c7f469`).

### 3. Generate the replay

Build the command from user preferences. Base command:

```bash
python3 <SKILL_DIR>/scripts/replay.py <input> -o <output.html>
```

**Input options** (mutually exclusive):
- `--last` -- most recent session
- `<session-id>` -- partial or full session ID
- `<path/to/session.json>` -- direct file path

**Customization flags:**

| Flag | What it does | Example |
|------|-------------|---------|
| `--theme NAME` | Visual theme | `--theme tokyo-night` |
| `--turns N-M` | Include only turns N through M | `--turns 3-15` |
| `--from TIMESTAMP` | Start time filter (ISO 8601) | `--from "2026-03-01T10:00"` |
| `--to TIMESTAMP` | End time filter (ISO 8601) | `--to "2026-03-01T12:00"` |
| `--speed N` | Initial playback speed (0.5-5) | `--speed 2` |
| `--no-thinking` | Hide thinking blocks by default | |
| `--no-tool-calls` | Hide tool call blocks by default | |
| `--no-redact` | Disable automatic secret redaction | |
| `--no-animate` | Disable typewriter animation (classic mode) | |
| `--title TEXT` | Custom page title | `--title "Bug Fix Demo"` |
| `--mark "N:Label"` | Bookmark at turn N (repeatable) | `--mark "3:Setup" --mark "8:Fix"` |
| `--bookmarks FILE` | JSON file with bookmarks | `--bookmarks marks.json` |
| `--theme-file FILE` | Custom theme JSON | `--theme-file my-theme.json` |
| `--user-label NAME` | Label for user messages | `--user-label "Developer"` |
| `--assistant-label NAME` | Label for assistant messages | `--assistant-label "Coco"` |
| `--no-compress` | Embed raw JSON (larger file, debuggable) | |

**Available themes:** `snowflake` (default), `tokyo-night`, `monokai`, `solarized-dark`, `github-light`, `dracula`

### 4. Open the replay

After generating, open it:

```bash
open <output.html>   # macOS
```

### 5. Report results

Tell the user:
- Output file path and size
- Number of turns included
- Theme used
- How to share it (it's fully self-contained -- email, embed, commit to repo)

## Example Commands

```bash
# Quick replay of last session
python3 <SKILL_DIR>/scripts/replay.py --last -o replay.html

# Specific session with dark theme
python3 <SKILL_DIR>/scripts/replay.py 6868f059 --theme dracula -o replay.html

# Trimmed replay with bookmarks for a demo
python3 <SKILL_DIR>/scripts/replay.py --last --turns 3-15 --theme tokyo-night --speed 2 \
  --no-thinking --mark "3:Setup" --mark "8:Implementation" \
  --title "Building a Data Pipeline" -o demo.html

# Light theme for docs embedding
python3 <SKILL_DIR>/scripts/replay.py --last --theme github-light --no-tool-calls -o docs-replay.html

# Custom labels
python3 <SKILL_DIR>/scripts/replay.py session.json --user-label "Engineer" --assistant-label "Coco" -o replay.html
```

## Embedding in Docs or Blogs

The output HTML can be embedded via iframe:

```html
<iframe src="replay.html" width="100%" height="600"
  style="border: 1px solid #333; border-radius: 8px;"></iframe>
```

## Player Controls (for the user's reference)

The generated HTML player supports:
- **Typewriter animation** -- user prompts are typed out character-by-character with a blinking cursor; assistant responses fade in block-by-block (disable with `--no-animate`)
- **Play/Pause** -- auto-advances through turns with animated transitions
- **Step forward/back** -- jump between turns (instantly reveals content when navigating manually)
- **Progress bar** -- click to jump anywhere (instantly reveals all content up to that point)
- **Speed control** -- 0.5x to 5x (scales typing speed and block reveal timing)
- **Toggle checkboxes** -- show/hide thinking and tool calls
- **Keyboard:** Space/K = play/pause, Right/L = forward, Left/H = back

## Custom Themes

Users can create a JSON file with any subset of these keys (missing keys fall back to snowflake defaults):

```json
{
  "bg": "#1a1a2e",
  "bg-surface": "#16213e",
  "bg-hover": "#1a2744",
  "text": "#e0e0e0",
  "text-dim": "#666",
  "text-bright": "#fff",
  "accent": "#e94560",
  "accent-dim": "#b33548",
  "green": "#4ecca3",
  "blue": "#4cc9f0",
  "orange": "#f0a030",
  "red": "#e85454",
  "cyan": "#4cc9f0",
  "border": "#2a2a4a",
  "tool-bg": "#12121f",
  "thinking-bg": "#111122"
}
```

Use with: `--theme-file my-theme.json`

## Session File Location

Cortex Code sessions are stored at `~/.snowflake/cortex/conversations/`. Each `.json` file is a full session transcript.

## Notes

- The output HTML is fully self-contained -- no external dependencies, works offline
- Secrets (API keys, tokens, passwords, Snowflake credentials) are automatically redacted unless `--no-redact` is used
- System-reminder blocks and internal platform noise are stripped automatically
- The `--last` flag reads `~/.snowflake/cortex/conversations/.last-session` to find the most recent session
- This skill requires only Python 3 (stdlib) -- no npm, no Node.js, no pip packages

## Deploying to a Profile

To publish this skill to a Snowflake stage for profile-based distribution:

```bash
cortex skill publish ~/.cortex/skills/cortex-replay --to-stage @DB.SCHEMA.STAGE/skills/
```

This uploads both `SKILL.md` and `scripts/replay.py` to the stage. Any user with the profile will get the skill with the bundled script -- no installation required.
