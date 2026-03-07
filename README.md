# cortex-replay

Convert [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code) session transcripts into self-contained, interactive HTML replays.

Cortex Code stores full conversation transcripts as JSON files. cortex-replay turns them into visual, shareable replays — a single HTML file with no external dependencies that you can open locally, email, or embed in documentation.

Adapted from [claude-replay](https://github.com/es617/claude-replay) (MIT) for Cortex Code's session format.

## Getting Started

**Requirements:** Node.js 18+

### Install

```bash
npm install -g github:dataprofessor/cortex-replay
```

### Quick start

```bash
# List your sessions
cortex-replay --list-sessions

# Replay the most recent session
cortex-replay --last -o replay.html

# Replay a specific session (partial ID match works)
cortex-replay 151d54c7 -o replay.html

# Open it
open replay.html
```

### Run without installing

```bash
npx github:dataprofessor/cortex-replay --last -o replay.html
```

## Usage

```
cortex-replay <session.json> [options]
cortex-replay --last [options]
cortex-replay --list-sessions
```

### Options

| Flag | Description |
|------|-------------|
| `-o, --output FILE` | Output HTML file (default: stdout) |
| `--last` | Use the most recent session |
| `--list-sessions` | List available sessions and exit |
| `--session-dir DIR` | Session directory (default: `~/.snowflake/cortex/conversations`) |
| `--turns N-M` | Only include turns N through M |
| `--from TIMESTAMP` | Start time filter (ISO 8601) |
| `--to TIMESTAMP` | End time filter (ISO 8601) |
| `--speed N` | Initial playback speed (default: 1.0) |
| `--no-thinking` | Hide thinking blocks by default |
| `--no-tool-calls` | Hide tool call blocks by default |
| `--no-redact` | Disable automatic secret redaction |
| `--theme NAME` | Built-in theme (default: snowflake) |
| `--theme-file FILE` | Custom theme JSON file |
| `--mark "N:Label"` | Add a bookmark at turn N (repeatable) |
| `--bookmarks FILE` | JSON file with bookmarks `[{turn, label}]` |
| `--list-themes` | List available themes and exit |

### Examples

```bash
# Replay turns 3 through 10 at 2x speed
cortex-replay session.json --turns 3-10 --speed 2 -o replay.html

# Use dracula theme, hide thinking blocks
cortex-replay --last --theme dracula --no-thinking -o replay.html

# Filter by time range
cortex-replay session.json --from "2026-03-01T10:00" --to "2026-03-01T12:00" -o replay.html

# Add chapter bookmarks
cortex-replay session.json --mark "1:Setup" --mark "5:Implementation" -o replay.html
```

## Player Controls

The generated HTML is a fully self-contained interactive player:

- **Play/Pause** — auto-advances through turns block by block
- **Step forward/back** — navigate one block at a time
- **Progress bar** — click to jump to any point
- **Speed control** — 0.5x to 5x
- **Toggle checkboxes** — show/hide thinking blocks and tool calls

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| Space / K | Play / Pause |
| Right / L | Step forward |
| Left / H | Step back |

## Themes

```bash
cortex-replay --list-themes
```

Available: `snowflake` (default), `tokyo-night`, `monokai`, `solarized-dark`, `github-light`, `dracula`.

Custom themes via JSON file:

```bash
cortex-replay session.json --theme-file my-theme.json -o replay.html
```

## Features

- **Self-contained HTML** — no external dependencies, works offline
- **Secret redaction** — API keys, tokens, passwords, and Snowflake credentials are automatically replaced with `[REDACTED]`
- **System noise filtering** — strips `<system-reminder>` blocks and internal-only content
- **Session discovery** — lists sessions, supports partial ID matching, `--last` shortcut
- **Cortex-aware tool rendering** — SQL queries, file operations, skills, and searches get contextual summaries
- **Session metadata** — displays title, Snowflake connection, working directory in the header
- **Embeddable** — drop into docs or blogs via iframe

## Embedding

```html
<iframe src="replay.html" width="100%" height="600"
  style="border: 1px solid #333; border-radius: 8px;"></iframe>
```

## Acknowledgments

Based on [claude-replay](https://github.com/es617/claude-replay) by Enrico Santagati, licensed under MIT.

## License

MIT
