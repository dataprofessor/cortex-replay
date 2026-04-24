#!/usr/bin/env python3
"""
Pure Python session replay generator for Cortex Code.
Converts session JSON transcripts into self-contained interactive HTML replays.
Zero external dependencies - uses only Python stdlib.

Usage:
    python replay.py --last -o replay.html
    python replay.py <session-id> -o replay.html
    python replay.py --list-sessions
"""

import argparse
import base64
import html as html_mod
import json
import os
import re
import sys
import urllib.parse
import zlib
from pathlib import Path

# ============================================================================
# THEMES
# ============================================================================

BUILTIN_THEMES = {
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
}

THEME_VARS = [
    "bg", "bg-surface", "bg-hover",
    "text", "text-dim", "text-bright",
    "accent", "accent-dim",
    "green", "blue", "orange", "red", "cyan",
    "border", "tool-bg", "thinking-bg",
]


def get_theme(name):
    if name not in BUILTIN_THEMES:
        available = ", ".join(sorted(BUILTIN_THEMES.keys()))
        raise ValueError(f"Unknown theme '{name}'. Available: {available}")
    return BUILTIN_THEMES[name]


def load_theme_file(path):
    with open(path) as f:
        custom = json.load(f)
    if not isinstance(custom, dict):
        raise ValueError("Theme file must be a JSON object")
    return {**BUILTIN_THEMES["snowflake"], **custom}


def theme_to_css(theme):
    lines = []
    for v in THEME_VARS:
        if v in theme:
            lines.append(f"  --{v}: {theme[v]};")
    return ":root {\n" + "\n".join(lines) + "\n}"


# ============================================================================
# SECRET REDACTION
# ============================================================================

REDACTED = "[REDACTED]"

SECRET_PATTERNS = [
    # Private keys
    re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
    ),
    # AWS access key IDs
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # Anthropic API keys
    re.compile(r"sk-ant-[a-zA-Z0-9-]{20,}"),
    # Generic sk- prefixed secrets
    re.compile(r"sk-[a-zA-Z0-9-]{20,}"),
    # key- prefixed secrets
    re.compile(r"key-[a-zA-Z0-9]{20,}"),
    # Bearer tokens
    re.compile(r"Bearer [A-Za-z0-9_.~+/=-]{20,}"),
    # JWT tokens
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+"),
    # Connection strings
    re.compile(
        r"(?:mongodb|postgres|mysql|redis|amqp|mssql|snowflake)://[^\s\"']+"
    ),
    # Snowflake tokens
    re.compile(
        r"(?:snowflakeToken|masterToken|sessionToken)\s*[:=]\s*[\"']?[^\s\"',]{20,}[\"']?",
        re.IGNORECASE,
    ),
    # Generic key=value secrets
    re.compile(
        r"(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?key|auth[_-]?token|"
        r"bearer|password|passwd)\s*[:=]\s*[\"']?[^\s\"',]{8,}[\"']?",
        re.IGNORECASE,
    ),
    # Env var patterns
    re.compile(
        r"(?:PASSWORD|TOKEN|SECRET|CREDENTIAL|PRIVATE_KEY|SNOWFLAKE_PASSWORD|SF_PASSWORD)=[^\s]+"
    ),
    # Standalone hex tokens (40+ chars)
    re.compile(r"\b[0-9a-fA-F]{40,}\b"),
]


def redact_secrets(text):
    if not isinstance(text, str):
        return text
    result = text
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def redact_object(obj):
    if isinstance(obj, str):
        return redact_secrets(obj)
    if isinstance(obj, list):
        return [redact_object(item) for item in obj]
    if isinstance(obj, dict):
        return {k: redact_object(v) for k, v in obj.items()}
    return obj


# ============================================================================
# PARSER
# ============================================================================

def clean_system_tags(text):
    """Strip system-reminder tags and other internal markup."""
    text = re.sub(r"<system-reminder>[\s\S]*?</system-reminder>\s*", "", text)
    text = re.sub(r"<local-command-caveat>[\s\S]*?</local-command-caveat>\s*", "", text)
    text = re.sub(
        r"<command-name>([\s\S]*?)</command-name>\s*",
        lambda m: m.group(1).strip() + "\n",
        text,
    )
    text = re.sub(r"<command-message>[\s\S]*?</command-message>\s*", "", text)
    text = re.sub(r"<command-args>\s*</command-args>\s*", "", text)
    text = re.sub(
        r"<command-args>([\s\S]*?)</command-args>\s*",
        lambda m: (m.group(1).strip() + "\n") if m.group(1).strip() else "",
        text,
    )
    text = re.sub(r"<local-command-stdout>[\s\S]*?</local-command-stdout>\s*", "", text)
    text = re.sub(
        r"<task-notification>\s*<task-id>[^<]*</task-id>\s*<output-file>[^<]*</output-file>"
        r"\s*<status>([^<]*)</status>\s*<summary>([^<]*)</summary>\s*</task-notification>",
        lambda m: f"[bg-task: {m.group(2)}]",
        text,
    )
    text = re.sub(r"\n*Read the output file to retrieve the result:[^\n]*", "", text)
    return text.strip()


def extract_user_text(content):
    """Extract visible user text from message content blocks."""
    if isinstance(content, str):
        return clean_system_tags(content)
    parts = []
    for block in content:
        if block.get("type") != "text":
            continue
        if block.get("internalOnly") is True:
            continue
        if block.get("is_user_prompt") is False and not block.get("displayText"):
            continue
        text = block.get("displayText") or block.get("text", "")
        if text:
            parts.append(text)
    return clean_system_tags("\n".join(parts))


def is_tool_result_only(content):
    """Check if a user message contains only tool_result blocks."""
    if isinstance(content, str):
        return False
    if not isinstance(content, list):
        return False
    return all(
        b.get("type") == "tool_result"
        or (b.get("type") == "text" and b.get("internalOnly") is True)
        for b in content
    )


def collect_assistant_blocks(history, start):
    """Collect blocks from consecutive assistant messages starting at index."""
    blocks = []
    seen_keys = set()
    i = start

    while i < len(history):
        entry = history[i]
        if entry.get("role") != "assistant":
            break

        timestamp = entry.get("user_sent_time")
        content = entry.get("content", [])

        if isinstance(content, list):
            for block in content:
                btype = block.get("type")

                if btype == "text":
                    text = (block.get("text") or "").strip()
                    if not text or text == "No response requested.":
                        continue
                    key = f"text:{text}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    blocks.append({
                        "kind": "text",
                        "text": text,
                        "tool_call": None,
                        "timestamp": timestamp,
                    })

                elif btype == "thinking":
                    think_obj = block.get("thinking", {})
                    if isinstance(think_obj, str):
                        text = think_obj.strip()
                    else:
                        text = (think_obj.get("text") or "").strip()
                    if not text:
                        continue
                    key = f"thinking:{text}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    blocks.append({
                        "kind": "thinking",
                        "text": text,
                        "tool_call": None,
                        "timestamp": timestamp,
                    })

                elif btype == "tool_use":
                    tu = block.get("tool_use", block)
                    tool_id = tu.get("tool_use_id") or tu.get("id", "")
                    key = f"tool_use:{tool_id}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    blocks.append({
                        "kind": "tool_use",
                        "text": "",
                        "tool_call": {
                            "tool_use_id": tool_id,
                            "name": tu.get("name", ""),
                            "input": tu.get("input", {}),
                            "result": None,
                            "resultTimestamp": None,
                            "status": None,
                        },
                        "timestamp": timestamp,
                    })
        i += 1

    return blocks, i


def attach_tool_results(blocks, history, result_start):
    """Match tool_result blocks to tool_use blocks by ID."""
    pending = {}
    for b in blocks:
        if b["kind"] == "tool_use" and b["tool_call"]:
            pending[b["tool_call"]["tool_use_id"]] = b["tool_call"]

    if not pending:
        return result_start

    i = result_start
    while i < len(history) and pending:
        entry = history[i]
        if entry.get("role") == "assistant":
            break
        if entry.get("role") == "user":
            content = entry.get("content", [])
            if isinstance(content, list):
                has_tool_result = False
                for block in content:
                    if block.get("type") == "tool_result":
                        has_tool_result = True
                        tr = block.get("tool_result", block)
                        tid = tr.get("tool_use_id", "")
                        if tid in pending:
                            result_content = tr.get("content")
                            if isinstance(result_content, list):
                                result_text = "\n".join(
                                    p.get("text", "")
                                    for p in result_content
                                    if p.get("type") == "text"
                                )
                            elif isinstance(result_content, str):
                                result_text = result_content
                            else:
                                result_text = str(result_content or "")
                            tc = pending[tid]
                            tc["result"] = result_text
                            tc["resultTimestamp"] = entry.get("user_sent_time")
                            tc["status"] = tr.get("status")
                            del pending[tid]
                if not has_tool_result:
                    break
            else:
                break
        i += 1

    return i


def parse_session(file_path):
    """Parse a Cortex Code session JSON file into turns and metadata."""
    with open(file_path) as f:
        session = json.load(f)

    meta = {
        "title": session.get("title", ""),
        "session_id": session.get("session_id", ""),
        "created_at": session.get("created_at", ""),
        "last_updated": session.get("last_updated", ""),
        "connection_name": session.get("connection_name"),
        "working_directory": session.get("working_directory"),
    }

    history = session.get("history", [])

    # New format: history stored in a separate .history.jsonl sidecar file
    if not history:
        jsonl_path = Path(file_path).parent / (Path(file_path).stem + ".history.jsonl")
        if jsonl_path.exists():
            with open(jsonl_path) as jf:
                history = [json.loads(line) for line in jf if line.strip()]

    turns = []
    i = 0
    turn_index = 0

    while i < len(history):
        entry = history[i]

        if entry.get("role") == "user":
            content = entry.get("content", [])

            if is_tool_result_only(content):
                i += 1
                continue

            user_text = extract_user_text(content)
            timestamp = entry.get("user_sent_time", "")
            i += 1

            # Absorb consecutive non-tool-result user messages
            while i < len(history):
                nxt = history[i]
                if nxt.get("role") != "user":
                    break
                next_content = nxt.get("content", [])
                if is_tool_result_only(next_content):
                    break
                next_text = extract_user_text(next_content)
                if next_text:
                    user_text = (user_text + "\n" + next_text) if user_text else next_text
                i += 1

            # Extract system events
            system_events = []
            user_text = re.sub(
                r"\[bg-task:\s*(.+)\]",
                lambda m: (system_events.append(m.group(1)), "")[1],
                user_text,
            )
            user_text = user_text.strip()

            assistant_blocks, i = collect_assistant_blocks(history, i)
            i = attach_tool_results(assistant_blocks, history, i)

            turn_index += 1
            turn = {
                "index": turn_index,
                "user_text": user_text,
                "blocks": assistant_blocks,
                "timestamp": timestamp,
            }
            if system_events:
                turn["system_events"] = system_events
            turns.append(turn)

        elif entry.get("role") == "assistant":
            assistant_blocks, i = collect_assistant_blocks(history, i)
            i = attach_tool_results(assistant_blocks, history, i)

            if turns:
                turns[-1]["blocks"].extend(assistant_blocks)
            else:
                turn_index += 1
                turns.append({
                    "index": turn_index,
                    "user_text": "",
                    "blocks": assistant_blocks,
                    "timestamp": entry.get("user_sent_time", ""),
                })
        else:
            i += 1

    # Drop empty turns
    filtered = [
        t for t in turns
        if t["user_text"]
        or t.get("system_events")
        or any(
            (b["kind"] == "tool_use")
            or (b["kind"] == "text" and b["text"] and b["text"] != "No response requested.")
            or (b["kind"] == "thinking" and b["text"])
            for b in t["blocks"]
        )
    ]

    # Re-index
    for j, t in enumerate(filtered):
        t["index"] = j + 1

    return filtered, meta


def filter_turns(turns, turn_range=None, time_from=None, time_to=None):
    """Filter turns by range or time window."""
    result = turns

    if turn_range:
        start, end = turn_range
        result = [t for t in result if start <= t["index"] <= end]

    if time_from:
        result = [t for t in result if not t["timestamp"] or t["timestamp"] >= time_from]

    if time_to:
        result = [t for t in result if not t["timestamp"] or t["timestamp"] <= time_to]

    # Re-index
    for j, t in enumerate(result):
        t["index"] = j + 1

    return result


# ============================================================================
# RENDERER
# ============================================================================

def escape_html(s):
    return html_mod.escape(s, quote=True)


def escape_json_for_script(json_str):
    return json_str.replace("</", "<\\/").replace("<!--", "<\\!--")


def compress_for_embed(json_str):
    """Compress JSON string to base64-encoded deflate for embedding."""
    compressed = zlib.compress(json_str.encode("utf-8"))
    # zlib.compress produces a zlib stream (with header), but we need raw deflate
    # The JS DecompressionStream("deflate") expects zlib format, so this is correct
    return base64.b64encode(compressed).decode("ascii")


def turns_to_json_data(turns, redact=True):
    """Prepare turns data for serialization."""
    result = []
    for turn in turns:
        entry = {
            "index": turn["index"],
            "user_text": redact_secrets(turn["user_text"]) if redact else turn["user_text"],
            "blocks": [],
            "timestamp": turn.get("timestamp", ""),
        }
        if turn.get("system_events"):
            entry["system_events"] = turn["system_events"]

        for b in turn["blocks"]:
            block = {
                "kind": b["kind"],
                "text": redact_secrets(b["text"]) if redact else b["text"],
            }
            if b.get("timestamp"):
                block["timestamp"] = b["timestamp"]
            if b.get("tool_call"):
                tc = b["tool_call"]
                block["tool_call"] = {
                    "name": tc["name"],
                    "input": redact_object(tc["input"]) if redact else tc["input"],
                    "result": redact_secrets(tc["result"]) if redact else tc["result"],
                    "status": tc.get("status"),
                }
                if tc.get("resultTimestamp"):
                    block["tool_call"]["resultTimestamp"] = tc["resultTimestamp"]
            entry["blocks"].append(block)

        result.append(entry)
    return result


def render(turns, theme=None, speed=1.0, show_thinking=True, show_tool_calls=True,
           user_label="User", assistant_label="Cortex Code", title="Cortex Code Replay",
           redact=True, bookmarks=None, compress=True, meta=None, animate=True):
    """Render turns into a self-contained HTML string."""
    if theme is None:
        theme = get_theme("snowflake")
    if bookmarks is None:
        bookmarks = []

    speed = max(0.1, min(speed, 10)) if isinstance(speed, (int, float)) else 1.0

    template = PLAYER_HTML_TEMPLATE

    # Replace template placeholders
    template = template.replace("/*THEME_CSS*/", theme_to_css(theme))
    template = template.replace("/*INITIAL_SPEED*/1", str(speed))
    template = template.replace("/*INITIAL_SPEED*/", str(speed))
    template = template.replace("/*CHECKED_THINKING*/", "checked" if show_thinking else "")
    template = template.replace("/*CHECKED_TOOLS*/", "checked" if show_tool_calls else "")
    template = template.replace("/*PAGE_TITLE*/", escape_html(title))
    template = template.replace("/*USER_LABEL*/", escape_html(user_label))
    template = template.replace("/*ASSISTANT_LABEL*/", escape_html(assistant_label))
    template = template.replace("/*ANIMATE_MODE*/", "true" if animate else "false")

    # Session metadata
    if meta:
        meta_obj = {
            "title": redact_secrets(meta["title"]) if redact else meta["title"],
            "session_id": meta.get("session_id", ""),
            "connection_name": meta.get("connection_name", ""),
            "working_directory": meta.get("working_directory", ""),
            "created_at": meta.get("created_at", ""),
        }
        meta_json = urllib.parse.quote(json.dumps(meta_obj))
    else:
        meta_json = ""
    template = template.replace("/*SESSION_META_JSON*/", meta_json)

    # Data blobs
    turns_json = json.dumps(turns_to_json_data(turns, redact=redact))
    bookmarks_json = json.dumps(bookmarks)

    if compress:
        embed_turns = compress_for_embed(turns_json)
        embed_bookmarks = compress_for_embed(bookmarks_json)
    else:
        embed_turns = escape_json_for_script(turns_json)
        embed_bookmarks = escape_json_for_script(bookmarks_json)

    template = template.replace("/*BOOKMARKS_DATA*/", embed_bookmarks)
    template = template.replace("/*TURNS_DATA*/", embed_turns)

    return template


# ============================================================================
# SESSION DISCOVERY
# ============================================================================

DEFAULT_SESSION_DIR = Path.home() / ".snowflake" / "cortex" / "conversations"


def read_session_info(file_path):
    """Read minimal metadata from a session file."""
    try:
        with open(file_path) as f:
            data = json.load(f)
        title = re.sub(r"<[^>]+>", "", data.get("title", "(untitled)")).strip() or "(untitled)"
        history = data.get("history", [])
        if history:
            user_turns = sum(1 for h in history if h.get("role") == "user")
        else:
            # New format: history_length is total messages; approximate user turns
            user_turns = data.get("history_length", 0) // 2
        return {
            "id": data.get("session_id", Path(file_path).stem),
            "title": title,
            "created_at": data.get("created_at", ""),
            "last_updated": data.get("last_updated", ""),
            "turns": user_turns,
            "file": str(file_path),
        }
    except Exception:
        return None


def find_session(query, session_dir):
    """Find a session file by partial ID match."""
    if not session_dir.exists():
        return None
    files = [f for f in session_dir.iterdir() if f.suffix == ".json"]
    # Exact match
    exact = session_dir / (query + ".json")
    if exact.exists():
        return str(exact)
    # Partial match
    matches = [f for f in files if f.name.startswith(query)]
    if len(matches) == 1:
        return str(matches[0])
    if len(matches) > 1:
        print(f"Ambiguous session ID '{query}'. Matches:", file=sys.stderr)
        for m in matches:
            print(f"  {m.name}", file=sys.stderr)
        sys.exit(1)
    # Check subdirectories
    for d in session_dir.iterdir():
        if d.is_dir():
            sub_files = [f for f in d.iterdir() if f.suffix == ".json"]
            sub = [f for f in sub_files if f.name.startswith(query)]
            if sub:
                return str(sub[0])
    return None


def list_sessions(session_dir):
    """List all sessions sorted by last updated."""
    if not session_dir.exists():
        print(f"Session directory not found: {session_dir}", file=sys.stderr)
        sys.exit(1)

    files = [f for f in session_dir.iterdir() if f.suffix == ".json"]
    sessions = [s for s in (read_session_info(f) for f in files) if s]
    sessions.sort(key=lambda s: s.get("last_updated") or s.get("created_at", ""), reverse=True)

    if not sessions:
        print("No sessions found.", file=sys.stderr)
        return

    id_w, title_w, date_w = 12, 50, 20
    print(f"{'ID':<{id_w}}  {'Title':<{title_w}}  {'Last Updated':<{date_w}}  Turns")
    print("-" * (id_w + title_w + date_w + 12))

    for s in sessions:
        sid = s["id"][:id_w]
        stitle = s["title"][:title_w - 3] + "..." if len(s["title"]) > title_w else s["title"]
        sdate = (s.get("last_updated") or s.get("created_at", ""))[:date_w]
        print(f"{sid:<{id_w}}  {stitle:<{title_w}}  {sdate:<{date_w}}  {s['turns']}")


# ============================================================================
# HTML TEMPLATE (embedded verbatim from cortex-replay player.html)
# ============================================================================

PLAYER_HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>/*PAGE_TITLE*/</title>
<style>
/*THEME_CSS*/

* { margin: 0; padding: 0; box-sizing: border-box; }

html {
  scroll-padding-bottom: 80px;
}
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  -webkit-text-size-adjust: 100%;
  touch-action: manipulation;
}

.container {
  max-width: 960px;
  margin: 0 auto;
  padding: 0;
}

/* Session header */
.session-header {
  padding: 12px 48px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  position: sticky;
  top: 0;
  z-index: 50;
}
.session-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-bright);
  margin-bottom: 4px;
}
.session-meta {
  font-size: 11px;
  color: var(--text-dim);
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.session-meta span::before {
  margin-right: 4px;
}

/* Controls bar */
.controls {
  position: fixed;
  bottom: 0;
  left: 0;
  width: 100%;
  z-index: 100;
  background: var(--bg-surface);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column-reverse;
}

.controls-row {
  display: flex;
  align-items: center;
  gap: 8px 12px;
  padding: 8px 12px;
  flex-wrap: wrap;
}

.controls button {
  background: var(--bg-hover);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 10px;
  font-family: inherit;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
  height: 34px;
  min-width: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.controls button:hover { background: var(--border); }
#btn-play { width: 36px; }
.controls button.active { background: var(--accent-dim); border-color: var(--accent); }

.bar-title {
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-decoration: none;
  margin-right: auto;
  flex: 1;
  min-width: 0;
}
body.in-iframe .bar-title { cursor: pointer; }
body.in-iframe .bar-title::after { content: " \2197"; font-size: 9px; }

.progress-wrap {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 36px 8px;
}

.progress-bar {
  flex: 1;
  height: 4px;
  background: var(--bg);
  border-radius: 2px;
  cursor: pointer;
  position: relative;
  transition: height 0.15s;
}
.progress-bar::before {
  content: "";
  position: absolute;
  top: -12px;
  bottom: -12px;
  left: 0;
  right: 0;
}
.progress-bar:hover { height: 6px; }
.progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.2s;
}
.progress-segments {
  display: flex;
  width: 100%;
  height: 100%;
  gap: 1px;
  border-radius: 2px;
  overflow: hidden;
}
.progress-segment {
  height: 100%;
  position: relative;
  overflow: hidden;
  flex-shrink: 0;
  background: var(--bg-hover);
}
.segment-fill {
  height: 100%;
  width: 0%;
  transition: width 0.2s;
  border-radius: 0;
}
.progress-tooltip {
  position: absolute;
  bottom: 12px;
  transform: translateX(-50%);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11px;
  color: var(--text);
  white-space: nowrap;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.15s;
  z-index: 10;
}
.progress-bar:hover .progress-tooltip { opacity: 1; }

.progress-text {
  font-size: 11px;
  color: var(--text-dim);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.speed-wrap { position: relative; }
.speed-wrap button#speed-btn { font-variant-numeric: tabular-nums; }
.speed-popover {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 0;
  z-index: 200;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  min-width: 60px;
}
.speed-wrap.open .speed-popover { display: block; }
.speed-popover button {
  display: block;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-dim);
  font-family: inherit;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  padding: 6px 16px;
  cursor: pointer;
  text-align: center;
  white-space: nowrap;
}
.speed-popover button:hover { background: var(--bg-hover); color: var(--text); }
.speed-popover button.active { color: var(--accent); font-weight: 600; }

.filter-wrap { position: relative; }
.filter-popover {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  z-index: 200;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  min-width: 140px;
}
.filter-wrap.open .filter-popover { display: block; }
.filter-popover label {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-dim);
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  padding: 4px 0;
  white-space: nowrap;
}
.filter-popover label:hover { color: var(--text); }
.filter-popover input[type="checkbox"] { accent-color: var(--accent); }

#btn-prev-turn { margin-left: 36px; }

.controls-secondary {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
  margin-right: 36px;
}

/* More menu */
.more-wrap { position: relative; }
.more-popover {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  z-index: 200;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  min-width: 180px;
  max-height: 40vh;
  overflow-y: auto;
}
.more-wrap.open .more-popover { display: block; }
.more-popover label {
  display: flex; align-items: center; gap: 6px; color: var(--text-dim);
  cursor: pointer; user-select: none; font-size: 12px; padding: 4px 0; white-space: nowrap;
}
.more-popover label:hover { color: var(--text); }
.more-popover input[type="checkbox"] { accent-color: var(--accent); }
.more-popover .more-row {
  display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; color: var(--text-dim);
}
.more-popover .more-row-label { min-width: 50px; }
.more-divider { border: none; border-top: 1px solid var(--border); margin: 4px 0; }

#more-btn {
  display: none;
  background: none !important;
  border: none !important;
  font-size: 16px;
  font-weight: bold;
}
#chapter-btn { font-size: 20px; }

@media (max-width: 600px) {
  body:not(.in-iframe) #more-btn { display: inline-flex; }
  body:not(.in-iframe) .controls-secondary { display: none; }
  body:not(.in-iframe) .chapter-wrap { display: none !important; }
}
@media (max-width: 400px) {
  body.in-iframe #more-btn { display: inline-flex; }
  body.in-iframe .controls-secondary { display: none; }
  body.in-iframe .chapter-wrap { display: none !important; }
}

/* Transcript area */
.transcript {
  padding: 16px 16px 100vh;
  min-height: 100vh;
}

/* Turn visibility: hidden by default, progressively revealed */
.turn {
  margin-bottom: 36px;
  padding-top: 12px;
  padding-bottom: 12px;
  border-left: 3px solid transparent;
  padding-left: 20px;
  display: none;
}
.turn.revealed {
  display: block;
  opacity: 0.3;
  transition: opacity 0.4s, border-color 0.3s, box-shadow 0.3s;
}
.turn.revealed.active {
  opacity: 1;
}

/* User message */
.user-msg { margin-bottom: 8px; }
.user-prompt {
  color: var(--accent);
  font-weight: 600;
}
.user-text {
  color: var(--text-bright);
  word-break: break-word;
}

/* Assistant container */
.assistant-container {
  margin-top: 12px;
  padding: 0;
}

/* Typewriter cursor */
@keyframes blink-caret {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
.typing-cursor {
  display: inline-block;
  width: 2px;
  height: 1.1em;
  background: var(--accent);
  margin-left: 1px;
  vertical-align: text-bottom;
  animation: blink-caret 0.7s step-end infinite;
}

/* Animated block reveal */
.block-wrapper, .thinking-block, .tool-group, .tool-block {
  transition: opacity 0.35s ease, max-height 0.35s ease;
  overflow: hidden;
}
.block-hidden {
  opacity: 0 !important;
  max-height: 0 !important;
  overflow: hidden !important;
  margin-top: 0 !important;
  margin-bottom: 0 !important;
  padding-top: 0 !important;
  padding-bottom: 0 !important;
  pointer-events: none;
}

/* Timestamp */
.timestamp {
  font-size: 10px;
  color: var(--text-dim);
  margin-bottom: 4px;
}

/* Turn header with number */
.turn-header-ts {
  font-size: 10px;
  color: var(--text-dim);
  margin-left: 8px;
}

/* Assistant text */
.assistant-header { margin-bottom: 4px; }
.assistant-prompt {
  color: var(--green);
  font-weight: 600;
}
.assistant-text {
  color: var(--text);
  word-break: break-word;
  margin: 6px 0;
  padding-left: 0;
  line-height: 1.6;
}
.assistant-text p { margin: 0.4em 0; }
.assistant-text pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 8px 0;
  line-height: 1.4;
}
.assistant-text pre code {
  background: none;
  padding: 0;
  border-radius: 0;
  font-size: inherit;
}
.assistant-text code {
  background: var(--bg);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.92em;
}
.assistant-text h3, .assistant-text h4, .assistant-text h5, .assistant-text h6 {
  color: var(--text-bright);
  margin: 0.8em 0 0.3em;
  line-height: 1.3;
}
.assistant-text h3 { font-size: 1.15em; }
.assistant-text h4 { font-size: 1.05em; }
.assistant-text h5, .assistant-text h6 { font-size: 1em; }
.assistant-text ul, .assistant-text ol {
  margin: 0.4em 0;
  padding-left: 1.6em;
}
.assistant-text li { margin: 0.15em 0; }
.assistant-text a {
  color: var(--blue);
  text-decoration: underline;
  text-decoration-color: color-mix(in srgb, var(--blue) 40%, transparent);
}
.assistant-text a:hover { text-decoration-color: var(--blue); }
.assistant-text strong { color: var(--text-bright); }
.assistant-text hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 0.8em 0;
}
.assistant-text table, .user-text table, .thinking-body table {
  border-collapse: collapse;
  margin: 8px 0;
  font-size: 0.95em;
  width: auto;
  overflow-x: auto;
  display: block;
}
.assistant-text th, .assistant-text td,
.user-text th, .user-text td,
.thinking-body th, .thinking-body td {
  border: 1px solid var(--border);
  padding: 4px 10px;
  text-align: left;
}
.assistant-text th, .user-text th, .thinking-body th {
  background: var(--bg-surface);
  color: var(--text-bright);
  font-weight: 600;
}

/* Background task notification badge */
.bg-task-badge {
  display: inline-block;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--text);
  margin: 4px 0;
}

/* Markdown in user text and thinking */
.user-text pre, .thinking-body pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  overflow-x: auto;
  margin: 8px 0;
}
.user-text pre code, .thinking-body pre code {
  background: none; padding: 0; border-radius: 0;
}
.user-text code, .thinking-body code {
  background: var(--bg);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.92em;
}
.user-text a, .thinking-body a {
  color: var(--blue);
  text-decoration: underline;
}
.user-text strong, .thinking-body strong { color: var(--text-bright); }
.user-text ul, .user-text ol, .thinking-body ul, .thinking-body ol {
  margin: 0.4em 0;
  padding-left: 1.6em;
}
.user-text p, .thinking-body p { margin: 0.4em 0; }

/* Tool call */
.tool-block {
  margin: 6px 0;
  margin-left: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--tool-bg);
  overflow: hidden;
}
.tool-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--text-dim);
}
.tool-header:hover { background: var(--bg-hover); }
.tool-chevron {
  transition: transform 0.15s;
  font-size: 10px;
  flex-shrink: 0;
}
.tool-block.open .tool-chevron { transform: rotate(90deg); }
.tool-indicator {
  color: var(--blue);
  font-size: 10px;
  flex-shrink: 0;
}
.tool-name {
  color: var(--cyan);
  font-weight: 600;
}
.tool-summary {
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.tool-status {
  font-size: 10px;
  flex-shrink: 0;
}
.tool-status.success { color: var(--green); }
.tool-status.error { color: var(--red); }
.tool-body {
  display: none;
  border-top: 1px solid var(--border);
  padding: 8px 10px;
  font-size: 12px;
  max-height: 400px;
  overflow: auto;
}
.tool-block.open .tool-body { display: block; }
.tool-input, .tool-output {
  margin: 4px 0;
}
.tool-input-label, .tool-output-label {
  color: var(--text-dim);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}
.tool-input pre, .tool-output pre {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 6px 8px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 11px;
  line-height: 1.5;
  max-height: 300px;
  overflow-y: auto;
}
.tool-output pre.sql-output {
  color: var(--cyan);
}

/* Tool groups (consecutive tool calls) */
.tool-group {
  margin: 6px 0;
  margin-left: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--tool-bg);
  overflow: hidden;
}
.tool-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--text-dim);
}
.tool-group-header:hover { background: var(--bg-hover); }
.tool-group-body {
  display: none;
  border-top: 1px solid var(--border);
}
.tool-group.open .tool-group-body { display: block; }
.tool-group.open .tool-chevron { transform: rotate(90deg); }
.tool-group .tool-block {
  border: none;
  border-radius: 0;
  border-bottom: 1px solid var(--border);
  margin: 0;
}
.tool-group .tool-block:last-child { border-bottom: none; }

/* Thinking blocks */
.thinking-block {
  margin: 6px 0;
  margin-left: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--thinking-bg);
  overflow: hidden;
}
.thinking-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--text-dim);
}
.thinking-header:hover { background: var(--bg-hover); }
.thinking-body {
  display: none;
  border-top: 1px solid var(--border);
  padding: 8px 10px;
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
  max-height: 400px;
  overflow: auto;
}
.thinking-block.open .thinking-body { display: block; }
.thinking-block.open .tool-chevron { transform: rotate(90deg); }

/* Bookmark dividers */
.bookmark-divider {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 20px 0;
  color: var(--text-dim);
  font-size: 12px;
  font-weight: 600;
  display: none;
}
.bookmark-divider.revealed { display: flex; }

/* Chapter menu */
.chapter-wrap { position: relative; }
.chapter-popover {
  display: none;
  position: absolute;
  bottom: calc(100% + 6px);
  right: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px 0;
  z-index: 200;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  min-width: 200px;
  max-height: 40vh;
  overflow-y: auto;
}
.chapter-wrap.open .chapter-popover { display: block; }
.chapter-popover button {
  display: block;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-dim);
  font-family: inherit;
  font-size: 12px;
  padding: 6px 12px;
  cursor: pointer;
  text-align: left;
  white-space: nowrap;
}
.chapter-popover button:hover { background: var(--bg-hover); color: var(--text); }
</style>
</head>
<body>

<div class="session-header" id="session-header" style="display:none">
  <div class="session-title" id="session-title"></div>
  <div class="session-meta" id="session-meta"></div>
</div>

<div class="container">
  <div class="transcript" id="transcript"></div>
</div>

<div class="controls">
    <div class="progress-wrap">
      <div class="progress-bar" id="progress-bar">
        <div class="progress-fill" id="progress-fill" style="width:0%"></div>
        <div class="progress-tooltip" id="progress-tooltip"></div>
      </div>
      <span class="progress-text" id="progress-text">0 / 0</span>
    </div>
    <div class="controls-row">
      <button id="btn-prev-turn" title="Previous Turn (Left arrow)">&#x23EE;</button>
      <button id="btn-play" title="Play/Pause (Space)">&#x25B6;</button>
      <button id="btn-next-turn" title="Next Turn (Right arrow)">&#x23ED;</button>

      <span class="bar-title" id="bar-title">/*PAGE_TITLE*/</span>

      <div class="controls-secondary">
        <div class="speed-wrap" id="speed-wrap">
          <button id="speed-btn" title="Playback speed">/*INITIAL_SPEED*/x</button>
          <div class="speed-popover" id="speed-popover">
            <button data-speed="0.5">0.5x</button>
            <button data-speed="1">1x</button>
            <button data-speed="1.5">1.5x</button>
            <button data-speed="2">2x</button>
            <button data-speed="3">3x</button>
            <button data-speed="5">5x</button>
          </div>
        </div>

        <div class="chapter-wrap" id="chapter-wrap" style="display:none">
          <button id="chapter-btn" title="Chapters">&#x2630;</button>
          <div class="chapter-popover" id="chapter-popover"></div>
        </div>

        <div class="filter-wrap" id="filter-wrap">
          <button id="filter-btn" title="Filters">&#x2699;</button>
          <div class="filter-popover" id="filter-popover">
            <label><input type="checkbox" id="chk-thinking" /*CHECKED_THINKING*/> Thinking</label>
            <label><input type="checkbox" id="chk-tools" /*CHECKED_TOOLS*/> Tool calls</label>
          </div>
        </div>
      </div>

      <div class="more-wrap" id="more-wrap">
        <button id="more-btn" title="More options">&hellip;</button>
        <div class="more-popover" id="more-popover">
          <div class="more-row">
            <span class="more-row-label">Speed</span>
            <button data-speed="0.5">0.5x</button>
            <button data-speed="1">1x</button>
            <button data-speed="2">2x</button>
            <button data-speed="5">5x</button>
          </div>
          <hr class="more-divider">
          <label><input type="checkbox" id="chk-thinking-m" /*CHECKED_THINKING*/> Thinking</label>
          <label><input type="checkbox" id="chk-tools-m" /*CHECKED_TOOLS*/> Tool calls</label>
        </div>
      </div>
    </div>
  </div>

<script>
(function() {
  "use strict";

  // --- Detect iframe ---
  if (window.self !== window.top) document.body.classList.add("in-iframe");

  // --- Config ---
  const USER_LABEL = "/*USER_LABEL*/";
  const ASSISTANT_LABEL = "/*ASSISTANT_LABEL*/";
  const ANIMATE_MODE = /*ANIMATE_MODE*/;

  // --- Decompress or parse embedded data ---
  async function decodeData(raw) {
    if (!raw || raw === "[]") return [];
    // If it starts with [ or {, it's raw JSON (--no-compress mode)
    const firstChar = raw.charAt(0);
    if (firstChar === "[" || firstChar === "{") {
      return JSON.parse(raw);
    }
    // Otherwise it's base64-encoded deflate-compressed data
    const bin = Uint8Array.from(atob(raw), c => c.charCodeAt(0));
    const ds = new DecompressionStream("deflate");
    const writer = ds.writable.getWriter();
    writer.write(bin);
    writer.close();
    const reader = ds.readable.getReader();
    const chunks = [];
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
    }
    const totalLen = chunks.reduce((a, b) => a + b.length, 0);
    const merged = new Uint8Array(totalLen);
    let offset = 0;
    for (const chunk of chunks) { merged.set(chunk, offset); offset += chunk.length; }
    return JSON.parse(new TextDecoder().decode(merged));
  }

  // --- Minimal markdown renderer ---
  function renderMd(text) {
    if (!text) return "";
    let html = text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

    // Extract code blocks and inline code FIRST to protect them from further transforms
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const placeholder = '\x00CB' + codeBlocks.length + '\x00';
      codeBlocks.push('<pre><code class="lang-' + lang + '">' + code.trimEnd() + '</code></pre>');
      return placeholder;
    });

    const inlineCodes = [];
    html = html.replace(/`([^`\n]+)`/g, (_, code) => {
      const placeholder = '\x00IC' + inlineCodes.length + '\x00';
      inlineCodes.push('<code>' + code + '</code>');
      return placeholder;
    });

    // Headers
    html = html.replace(/^######\s+(.+)$/gm, '<h6>$1</h6>');
    html = html.replace(/^#####\s+(.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');

    // Bold and italic
    html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Links
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Horizontal rules
    html = html.replace(/^---$/gm, '<hr>');

    // Tables
    html = html.replace(/(?:^|\n)((?:\|.+\|\n?)+)/g, (_, tableBlock) => {
      const rows = tableBlock.trim().split('\n');
      if (rows.length < 2) return _;
      let t = '<table>';
      rows.forEach((row, ri) => {
        if (ri === 1 && /^\|[\s:-]+\|$/.test(row.trim())) return; // separator
        const cells = row.split('|').filter((_, i, a) => i > 0 && i < a.length - 1);
        const tag = ri === 0 ? 'th' : 'td';
        t += '<tr>' + cells.map(c => '<' + tag + '>' + c.trim() + '</' + tag + '>').join('') + '</tr>';
      });
      t += '</table>';
      return t;
    });

    // Lists
    html = html.replace(/^(\s*)[-*]\s+(.+)$/gm, '$1<li>$2</li>');
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
    html = html.replace(/<\/ul>\s*<ul>/g, '');

    // Numbered lists
    html = html.replace(/^\d+\.\s+(.+)$/gm, '<li>$1</li>');

    // Paragraphs - wrap loose text in <p>
    html = html.replace(/^(?!<[a-z/\x00])((?!<[a-z/\x00]).+)$/gm, '<p>$1</p>');
    html = html.replace(/<p><\/p>/g, '');

    // Restore inline code and code blocks
    inlineCodes.forEach((code, i) => {
      html = html.replace('\x00IC' + i + '\x00', code);
    });
    codeBlocks.forEach((block, i) => {
      html = html.replace('\x00CB' + i + '\x00', block);
    });

    return html;
  }

  // --- Tool summary helpers ---
  function toolSummary(tc) {
    const name = tc.name || "";
    const input = tc.input || {};
    switch (name) {
      case "bash":
        return input.description || (input.command || "").substring(0, 60);
      case "read":
        return shortPath(input.file_path || "");
      case "write":
        return shortPath(input.file_path || "");
      case "edit":
        return shortPath(input.file_path || "");
      case "glob":
        return (input.pattern || "") + (input.path ? " in " + shortPath(input.path) : "");
      case "grep":
        return (input.pattern || "").substring(0, 40) + (input.path ? " in " + shortPath(input.path) : "");
      case "snowflake_sql_execute":
        return input.description || (input.sql || "").substring(0, 60);
      case "skill":
        return input.command || "";
      case "task":
        return input.description || "";
      case "web_fetch":
        return shortPath(input.url || "");
      case "web_search":
        return input.query || "";
      default:
        return JSON.stringify(input).substring(0, 60);
    }
  }

  function shortPath(p) {
    if (!p) return "";
    const parts = p.split("/");
    if (parts.length <= 3) return p;
    return ".../" + parts.slice(-2).join("/");
  }

  function toolInputDisplay(tc) {
    const name = tc.name || "";
    const input = tc.input || {};
    switch (name) {
      case "bash":
        return input.command || JSON.stringify(input, null, 2);
      case "snowflake_sql_execute":
        return input.sql || JSON.stringify(input, null, 2);
      case "read":
      case "write":
      case "edit":
        return input.file_path || JSON.stringify(input, null, 2);
      case "glob":
        return (input.pattern || "") + (input.path ? "\nin: " + input.path : "");
      case "grep":
        return (input.pattern || "") + (input.path ? "\nin: " + input.path : "");
      default:
        return JSON.stringify(input, null, 2);
    }
  }

  // --- Build DOM ---
  function buildTranscript(turns, bookmarks) {
    const container = document.getElementById("transcript");
    const bookmarkMap = {};
    for (const b of bookmarks) bookmarkMap[b.turn] = b.label;

    const allBlocks = []; // flat list of {el, turnEl, turnIdx, kind}
    let currentTurnIdx = 0;

    for (const turn of turns) {
      // Bookmark divider
      if (bookmarkMap[turn.index]) {
        const div = document.createElement("div");
        div.className = "bookmark-divider";
        div.dataset.forTurn = turn.index;
        div.textContent = bookmarkMap[turn.index];
        container.appendChild(div);
      }

      const turnEl = document.createElement("div");
      turnEl.className = "turn";
      turnEl.dataset.turn = turn.index;

      // User message
      if (turn.user_text) {
        const userDiv = document.createElement("div");
        userDiv.className = "user-msg";
        const ts = turn.timestamp ? formatTime(turn.timestamp) : "";
        userDiv.innerHTML =
          '<span class="user-prompt">' + escHtml(USER_LABEL) + ' </span>' +
          (ts ? '<span class="turn-header-ts">' + escHtml(ts) + '</span>' : '');
        // Create user-text container separately for typewriter
        const userTextEl = document.createElement("div");
        userTextEl.className = "user-text";
        userTextEl.dataset.rawText = turn.user_text;
        userDiv.appendChild(userTextEl);
        turnEl.appendChild(userDiv);
        allBlocks.push({ el: userDiv, turnEl, turnIdx: currentTurnIdx, kind: "user", userTextEl: userTextEl, rawText: turn.user_text });
      }

      // System events
      if (turn.system_events) {
        for (const evt of turn.system_events) {
          const badge = document.createElement("div");
          badge.className = "bg-task-badge";
          badge.textContent = evt;
          turnEl.appendChild(badge);
        }
      }

      // Assistant container (separate from user message area)
      let asstContainer = null;
      if (turn.blocks && turn.blocks.length > 0) {
        asstContainer = document.createElement("div");
        asstContainer.className = "assistant-container";
        const asstHeader = document.createElement("div");
        asstHeader.className = "assistant-header block-hidden";
        asstHeader.innerHTML = '<span class="assistant-prompt">' + escHtml(ASSISTANT_LABEL) + '</span>';
        asstContainer.appendChild(asstHeader);
        turnEl.appendChild(asstContainer);
        allBlocks.push({ el: asstHeader, turnEl, turnIdx: currentTurnIdx, kind: "assistant-header" });
      }

      // Assistant blocks
      let toolGroup = null;
      let toolGroupBlocks = [];
      const blockTarget = asstContainer || turnEl;

      function flushToolGroup() {
        if (!toolGroup) return;
        if (toolGroupBlocks.length === 1) {
          const single = toolGroupBlocks[0].el;
          single.style.margin = "";
          single.style.border = "";
          single.style.borderRadius = "";
          single.classList.add("block-hidden");
          blockTarget.insertBefore(single, toolGroup);
          blockTarget.removeChild(toolGroup);
          for (const tb of toolGroupBlocks) tb.el = single;
        } else {
          const count = toolGroupBlocks.length;
          const header = document.createElement("div");
          header.className = "tool-group-header";
          header.innerHTML = '<span class="tool-chevron">&#x25B8;</span> ' +
            '<span class="tool-indicator">&#x25CF;</span> ' +
            count + ' tool calls';
          const body = document.createElement("div");
          body.className = "tool-group-body";
          while (toolGroup.firstChild) body.appendChild(toolGroup.firstChild);
          toolGroup.insertBefore(header, toolGroup.firstChild);
          toolGroup.appendChild(body);
          header.onclick = () => toolGroup.classList.toggle("open");
          toolGroup.classList.add("open");
        }
        toolGroup = null;
        toolGroupBlocks = [];
      }

      for (const block of turn.blocks) {
        if (block.kind === "text") {
          flushToolGroup();
          const div = document.createElement("div");
          div.className = "block-wrapper block-hidden";
          const textDiv = document.createElement("div");
          textDiv.className = "assistant-text";
          textDiv.innerHTML = renderMd(block.text);
          div.appendChild(textDiv);
          blockTarget.appendChild(div);
          allBlocks.push({ el: div, turnEl, turnIdx: currentTurnIdx, kind: "assistant-text", rawText: block.text, textEl: textDiv });
        } else if (block.kind === "thinking") {
          flushToolGroup();
          const div = document.createElement("div");
          div.className = "thinking-block block-wrapper block-hidden";
          div.dataset.blockType = "thinking";
          div.innerHTML =
            '<div class="thinking-header"><span class="tool-chevron">&#x25B8;</span> Thinking</div>' +
            '<div class="thinking-body">' + renderMd(block.text) + '</div>';
          div.querySelector(".thinking-header").onclick = () => div.classList.toggle("open");
          blockTarget.appendChild(div);
          allBlocks.push({ el: div, turnEl, turnIdx: currentTurnIdx, kind: "thinking" });
        } else if (block.kind === "tool_use") {
          const tc = block.tool_call;
          if (!toolGroup) {
            toolGroup = document.createElement("div");
            toolGroup.className = "tool-group block-hidden";
            toolGroup.dataset.blockType = "tool";
            blockTarget.appendChild(toolGroup);
          }

          const div = document.createElement("div");
          div.className = "tool-block";
          div.dataset.blockType = "tool";

          const statusClass = tc.status === "error" ? "error" : (tc.result != null ? "success" : "");
          const statusText = tc.status === "error" ? "error" : (tc.result != null ? "ok" : "...");

          div.innerHTML =
            '<div class="tool-header">' +
              '<span class="tool-chevron">&#x25B8;</span>' +
              '<span class="tool-indicator">&#x25CF;</span>' +
              '<span class="tool-name">' + escHtml(tc.name) + '</span>' +
              '<span class="tool-summary">' + escHtml(toolSummary(tc)) + '</span>' +
              '<span class="tool-status ' + statusClass + '">' + statusText + '</span>' +
            '</div>' +
            '<div class="tool-body">' +
              '<div class="tool-input"><div class="tool-input-label">Input</div><pre>' + escHtml(toolInputDisplay(tc)) + '</pre></div>' +
              (tc.result != null ? '<div class="tool-output"><div class="tool-output-label">Output</div><pre' +
                (tc.name === "snowflake_sql_execute" ? ' class="sql-output"' : '') +
                '>' + escHtml(tc.result) + '</pre></div>' : '') +
            '</div>';

          div.querySelector(".tool-header").onclick = () => div.classList.toggle("open");
          toolGroup.appendChild(div);
          toolGroupBlocks.push({ el: div, turnEl, turnIdx: currentTurnIdx });
          allBlocks.push({ el: toolGroup, turnEl, turnIdx: currentTurnIdx, inGroup: true, kind: "tool", groupEl: toolGroup });
        }
      }
      flushToolGroup();

      container.appendChild(turnEl);
      currentTurnIdx++;
    }
    return allBlocks;
  }

  function escHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function formatTime(ts) {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch { return ""; }
  }

  function formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m + ":" + String(sec).padStart(2, "0");
  }

  // --- Player state ---
  let turns = [];
  let allBlocks = [];
  let bookmarks = [];
  let currentBlock = -1;
  let playing = false;
  let playTimer = null;
  let speed = /*INITIAL_SPEED*/1;
  let turnSegments = [];
  let turnColorMap = {};

  // Animation state machine
  const STATE_IDLE = 0;
  const STATE_TYPING_USER = 1;
  const STATE_REVEALING_BLOCKS = 2;
  const STATE_PAUSING = 3;
  const STATE_TYPING_ASSISTANT = 4;
  let animState = STATE_IDLE;
  let typingCancel = null; // function to cancel in-progress typing
  let revealedUpTo = -1; // highest block index that has been fully revealed

  // --- Turn color palette ---
  function turnColor(i, total) {
    const hue = (270 + (i / Math.max(total - 1, 1)) * 360) % 360;
    return "hsl(" + hue + ", 65%, 55%)";
  }

  function turnColorFaded(i, total) {
    const hue = (270 + (i / Math.max(total - 1, 1)) * 360) % 360;
    return "hsla(" + hue + ", 40%, 35%, 0.6)";
  }

  function turnColorMid(i, total) {
    const hue = (270 + (i / Math.max(total - 1, 1)) * 360) % 360;
    return "hsla(" + hue + ", 50%, 45%, 0.8)";
  }

  function turnColorGlow(i, total) {
    const hue = (270 + (i / Math.max(total - 1, 1)) * 360) % 360;
    return "hsla(" + hue + ", 65%, 55%, 0.35)";
  }

  // --- Build segmented progress bar ---
  function buildProgressSegments() {
    const bar = document.getElementById("progress-bar");
    const oldFill = document.getElementById("progress-fill");
    if (oldFill) oldFill.style.display = "none";

    const blocksPerTurn = {};
    for (const b of allBlocks) {
      blocksPerTurn[b.turnIdx] = (blocksPerTurn[b.turnIdx] || 0) + 1;
    }

    const total = allBlocks.length;
    if (total === 0) return;

    const segContainer = document.createElement("div");
    segContainer.className = "progress-segments";

    const turnIndices = Object.keys(blocksPerTurn).map(Number).sort((a, b) => a - b);
    const turnCount = turnIndices.length;
    let blockOffset = 0;

    for (let si = 0; si < turnIndices.length; si++) {
      const ti = turnIndices[si];
      const count = blocksPerTurn[ti];
      const pct = (count / total) * 100;
      const color = turnColor(si, turnCount);

      const seg = document.createElement("div");
      seg.className = "progress-segment";
      seg.style.width = pct + "%";

      const fill = document.createElement("div");
      fill.className = "segment-fill";
      fill.style.background = color;
      seg.appendChild(fill);

      segContainer.appendChild(seg);
      turnSegments.push({
        el: seg,
        fillEl: fill,
        startBlock: blockOffset,
        endBlock: blockOffset + count - 1,
        turnIdx: ti,
        color: color,
        blockCount: count
      });

      blockOffset += count;
    }

    bar.appendChild(segContainer);

    for (let si = 0; si < turnIndices.length; si++) {
      const ti = turnIndices[si];
      turnColorMap[ti] = {
        full: turnColor(si, turnCount),
        faded: turnColorFaded(si, turnCount),
        mid: turnColorMid(si, turnCount),
        glow: turnColorGlow(si, turnCount)
      };
    }
  }

  // Session metadata
  const SESSION_META = "/*SESSION_META_JSON*/";

  // --- Visibility filters ---
  const chkThinking = document.getElementById("chk-thinking");
  const chkTools = document.getElementById("chk-tools");
  const chkThinkingM = document.getElementById("chk-thinking-m");
  const chkToolsM = document.getElementById("chk-tools-m");

  function syncFilters() {
    const showThinking = chkThinking.checked;
    const showTools = chkTools.checked;
    chkThinkingM.checked = showThinking;
    chkToolsM.checked = showTools;
    document.querySelectorAll('[data-block-type="thinking"]').forEach(el => {
      el.style.display = showThinking ? "" : "none";
    });
    document.querySelectorAll('[data-block-type="tool"]').forEach(el => {
      el.style.display = showTools ? "" : "none";
    });
  }
  chkThinking.onchange = syncFilters;
  chkTools.onchange = syncFilters;
  chkThinkingM.onchange = () => { chkThinking.checked = chkThinkingM.checked; syncFilters(); };
  chkToolsM.onchange = () => { chkTools.checked = chkToolsM.checked; syncFilters(); };

  // =====================================================
  // TYPEWRITER ENGINE
  // =====================================================

  /**
   * Type text character-by-character into an element.
   * Returns a promise that resolves when done.
   * The returned promise has a .cancel() method to abort.
   */
  function typeText(el, text, charDelay) {
    let cancelled = false;
    let resolvePromise;

    const cursor = document.createElement("span");
    cursor.className = "typing-cursor";
    el.textContent = "";
    el.appendChild(cursor);

    const rendered = renderMd(text);
    // We type the raw text then swap to rendered markdown at the end
    const plainText = text;

    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
      let i = 0;

      function typeNext() {
        if (cancelled) {
          // Finish instantly
          el.innerHTML = rendered;
          resolve();
          return;
        }
        if (i < plainText.length) {
          // Insert character before cursor
          const charNode = document.createTextNode(plainText.charAt(i));
          el.insertBefore(charNode, cursor);
          i++;
          // Auto-scroll to keep cursor visible
          scrollToBottom();
          playTimer = setTimeout(typeNext, charDelay);
        } else {
          // Done typing - swap to rendered markdown
          if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
          el.innerHTML = rendered;
          resolve();
        }
      }
      typeNext();
    });

    promise.cancel = () => {
      cancelled = true;
      if (playTimer) { clearTimeout(playTimer); playTimer = null; }
      el.innerHTML = rendered;
      if (resolvePromise) resolvePromise();
    };

    return promise;
  }

  /**
   * Progressively reveal pre-rendered HTML by walking text nodes.
   * The element should already contain the full rendered HTML (hidden).
   * We hide all text content, then reveal character-by-character,
   * preserving the HTML structure (bold, code, headers, etc.).
   * Call prepareTypeHtml(el) BEFORE unhiding the block to avoid a content flash.
   * Returns a cancellable promise like typeText().
   */
  function prepareTypeHtml(el) {
    // Collect all text nodes and empty them BEFORE the block is made visible
    const textNodes = [];
    const hiddenContainers = new Set();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while ((node = walker.nextNode())) {
      if (node.textContent.length > 0) {
        // Find the closest structural container (li, tr, pre) to hide
        let container = null;
        let p = node.parentNode;
        while (p && p !== el) {
          const tag = p.tagName;
          if (tag === "LI" || tag === "TR" || tag === "PRE") { container = p; break; }
          p = p.parentNode;
        }
        textNodes.push({ node: node, fullText: node.textContent, container: container });
        if (container && !hiddenContainers.has(container)) {
          hiddenContainers.add(container);
          container.style.display = "none";
        }
      }
    }
    textNodes.forEach(t => { t.node.textContent = ""; });
    return textNodes;
  }

  function typeHtml(el, charDelay, preparedNodes) {
    let cancelled = false;
    let resolvePromise;

    // Use pre-collected text nodes if available, otherwise collect now
    const textNodes = preparedNodes || (() => {
      const nodes = [];
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null, false);
      let node;
      while ((node = walker.nextNode())) {
        if (node.textContent.length > 0) {
          nodes.push({ node: node, fullText: node.textContent, container: null });
        }
      }
      nodes.forEach(t => { t.node.textContent = ""; });
      return nodes;
    })();

    // Helper: restore all hidden containers
    function restoreContainers() {
      textNodes.forEach(t => {
        if (t.container) t.container.style.display = "";
      });
    }

    // Add a typing cursor — place at el initially (first container may be hidden)
    const cursor = document.createElement("span");
    cursor.className = "typing-cursor";
    el.appendChild(cursor);

    const promise = new Promise((resolve) => {
      resolvePromise = resolve;
      let tIdx = 0; // current text node index
      let cIdx = 0; // current char index within text node

      function revealNext() {
        if (cancelled) {
          // Restore all text and containers instantly
          textNodes.forEach(t => { t.node.textContent = t.fullText; });
          restoreContainers();
          if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
          resolve();
          return;
        }

        // Find next text node that still has chars to reveal
        while (tIdx < textNodes.length && cIdx >= textNodes[tIdx].fullText.length) {
          tIdx++;
          cIdx = 0;
        }

        if (tIdx >= textNodes.length) {
          // All done - remove cursor
          if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
          resolve();
          return;
        }

        const tn = textNodes[tIdx];

        // Reveal the container (li, tr) when we start typing its first character
        if (cIdx === 0 && tn.container && tn.container.style.display === "none") {
          tn.container.style.display = "";
        }

        // Reveal one more character
        cIdx++;
        tn.node.textContent = tn.fullText.substring(0, cIdx);

        // Move cursor after current text node
        if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
        tn.node.parentNode.insertBefore(cursor, tn.node.nextSibling);

        scrollToBottom();
        playTimer = setTimeout(revealNext, charDelay);
      }

      revealNext();
    });

    promise.cancel = () => {
      cancelled = true;
      if (playTimer) { clearTimeout(playTimer); playTimer = null; }
      textNodes.forEach(t => { t.node.textContent = t.fullText; });
      restoreContainers();
      if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
      if (resolvePromise) resolvePromise();
    };

    return promise;
  }

  // =====================================================
  // NAVIGATION & REVEAL
  // =====================================================

  function applyTurnHighlight(activeTurnIdx) {
    document.querySelectorAll(".turn").forEach((el, i) => {
      el.classList.remove("active");
      if (i <= activeTurnIdx) {
        el.classList.add("revealed");
      }
      if (i === activeTurnIdx) {
        el.classList.add("active");
      }
    });

    // Also reveal any bookmark dividers for revealed turns
    document.querySelectorAll(".bookmark-divider").forEach(el => {
      const forTurn = parseInt(el.dataset.forTurn);
      const turnIdx = turns.findIndex(t => t.index === forTurn);
      if (turnIdx >= 0 && turnIdx <= activeTurnIdx) {
        el.classList.add("revealed");
      }
    });

    document.querySelectorAll(".turn").forEach((el, i) => {
      const colors = turnColorMap[i];
      if (!colors) {
        el.style.borderLeftColor = "transparent";
        el.style.boxShadow = "";
      } else if (i < activeTurnIdx) {
        el.style.borderLeftColor = colors.faded;
        el.style.boxShadow = "";
      } else if (i === activeTurnIdx) {
        el.style.borderLeftColor = colors.full;
        el.style.boxShadow = "-4px 0 10px " + colors.glow;
      } else {
        el.style.borderLeftColor = "transparent";
        el.style.boxShadow = "";
      }
    });
  }

  /** Instantly reveal all blocks up to and including blockIdx */
  function revealUpTo(blockIdx) {
    for (let i = 0; i <= blockIdx && i < allBlocks.length; i++) {
      const b = allBlocks[i];
      // Reveal the turn
      b.turnEl.classList.add("revealed");
      // Reveal block content
      b.el.classList.remove("block-hidden");
      // If it's a user block, fill in the markdown content instantly
      if (b.kind === "user" && b.userTextEl) {
        b.userTextEl.innerHTML = renderMd(b.rawText);
      }
      // If it's an assistant-text block, restore full rendered HTML
      if (b.kind === "assistant-text" && b.textEl && b.rawText) {
        b.textEl.innerHTML = renderMd(b.rawText);
      }
    }
    if (blockIdx > revealedUpTo) revealedUpTo = blockIdx;
  }

  /** Hide all blocks after blockIdx */
  function hideAfter(blockIdx) {
    for (let i = blockIdx + 1; i < allBlocks.length; i++) {
      const b = allBlocks[i];
      b.el.classList.add("block-hidden");
      // Hide the turn if no blocks in it are revealed
      const turnHasRevealed = allBlocks.some(
        (ab, j) => j <= blockIdx && ab.turnIdx === b.turnIdx
      );
      if (!turnHasRevealed) {
        b.turnEl.classList.remove("revealed", "active");
      }
      // Reset user text
      if (b.kind === "user" && b.userTextEl) {
        b.userTextEl.textContent = "";
      }
      // Reset assistant text to full rendered HTML (hidden by block-hidden anyway)
      if (b.kind === "assistant-text" && b.textEl && b.rawText) {
        b.textEl.innerHTML = renderMd(b.rawText);
      }
    }
    // Hide bookmark dividers after
    document.querySelectorAll(".bookmark-divider").forEach(el => {
      const forTurn = parseInt(el.dataset.forTurn);
      const turnIdx = turns.findIndex(t => t.index === forTurn);
      const lastRevealedTurn = allBlocks[blockIdx] ? allBlocks[blockIdx].turnIdx : -1;
      if (turnIdx > lastRevealedTurn) {
        el.classList.remove("revealed");
      }
    });
    revealedUpTo = blockIdx;
  }

  let lastScrollTime = 0;
  function scrollToBottom(force) {
    // Throttle: skip if called within 150ms (unless forced)
    const now = Date.now();
    if (!force && now - lastScrollTime < 150) return;
    lastScrollTime = now;

    // Find the target element to keep visible
    let target = document.querySelector(".typing-cursor");
    const isTyping = !!target;
    if (!target) {
      const activeTurn = document.querySelector(".turn.revealed.active");
      if (activeTurn) {
        const visibleBlocks = activeTurn.querySelectorAll(
          ".block-wrapper:not(.block-hidden), .thinking-block:not(.block-hidden), .tool-group:not(.block-hidden), .tool-block:not(.block-hidden), .assistant-header:not(.block-hidden), .user-msg"
        );
        target = visibleBlocks[visibleBlocks.length - 1];
      }
      if (!target) {
        target = document.querySelector(".turn.revealed.active") ||
                 document.querySelector(".turn.revealed:last-child");
      }
    }
    if (!target) return;

    // Get the controls bar height to avoid scrolling behind it
    const controlsBar = document.querySelector(".controls");
    const barH = controlsBar ? controlsBar.offsetHeight : 0;
    const safeBottom = window.innerHeight - barH - 48;

    const rect = target.getBoundingClientRect();
    // Only scroll if the target is below the safe zone
    if (rect.bottom > safeBottom) {
      const scrollY = window.pageYOffset + rect.bottom - safeBottom;
      // Use instant scroll during typing to prevent bounce from competing animations
      window.scrollTo({ top: scrollY, behavior: isTyping ? "instant" : "smooth" });
    }
  }

  /** Go to a specific block index - instantly reveals everything up to it */
  function goTo(idx) {
    if (idx < 0) idx = 0;
    if (idx >= allBlocks.length) idx = allBlocks.length - 1;

    // Cancel any in-progress typing
    cancelAnimation();

    currentBlock = idx;
    revealUpTo(idx);
    hideAfter(idx);

    const activeTurnIdx = allBlocks[idx] ? allBlocks[idx].turnIdx : -1;
    applyTurnHighlight(activeTurnIdx);
    updateProgress();
    scrollToBottom();
  }

  function cancelAnimation() {
    animState = STATE_IDLE;
    if (typingCancel) {
      typingCancel();
      typingCancel = null;
    }
    if (playTimer) {
      clearTimeout(playTimer);
      playTimer = null;
    }
  }

  // =====================================================
  // ANIMATED PLAYBACK STATE MACHINE
  // =====================================================

  async function animatedTick() {
    if (!playing) return;
    if (currentBlock >= allBlocks.length - 1) { stop(); return; }

    const nextIdx = currentBlock + 1;
    const nextBlock = allBlocks[nextIdx];
    const prevTurnIdx = allBlocks[currentBlock] ? allBlocks[currentBlock].turnIdx : -1;
    const nextTurnIdx = nextBlock.turnIdx;

    // If entering a new turn, add a pause
    if (nextTurnIdx !== prevTurnIdx && currentBlock >= 0) {
      animState = STATE_PAUSING;
      // Show the turn container
      nextBlock.turnEl.classList.add("revealed", "active");
      applyTurnHighlight(nextTurnIdx);

      // Also reveal bookmark
      document.querySelectorAll(".bookmark-divider").forEach(el => {
        const forTurn = parseInt(el.dataset.forTurn);
        const turnIdx = turns.findIndex(t => t.index === forTurn);
        if (turnIdx === nextTurnIdx) el.classList.add("revealed");
      });

      await delay(Math.max(200, 600 / speed));
      if (!playing) return;
    }

    currentBlock = nextIdx;

    if (ANIMATE_MODE && nextBlock.kind === "user" && nextBlock.userTextEl && nextBlock.rawText) {
      // TYPEWRITER for user prompts
      animState = STATE_TYPING_USER;
      nextBlock.turnEl.classList.add("revealed", "active");
      applyTurnHighlight(nextTurnIdx);
      scrollToBottom();

      // Brief pause so user sees the empty prompt area before typing begins
      await delay(Math.max(200, 400 / speed));
      if (!playing) return;

      // Ensure clearly visible typing: minimum 1.5s at 1x speed, base 50ms/char
      const minDuration = Math.max(800, 1500 / speed);
      const rawLen = nextBlock.rawText.length;
      const charDelay = Math.max(20, Math.max(50 / speed, minDuration / Math.max(rawLen, 1)));
      const typePromise = typeText(nextBlock.userTextEl, nextBlock.rawText, charDelay);
      typingCancel = typePromise.cancel;

      await typePromise;
      typingCancel = null;
      if (!playing) return;

      revealedUpTo = nextIdx;
      updateProgress();
      scrollToBottom();

      // Brief pause after typing before showing response
      await delay(Math.max(100, 400 / speed));
      if (!playing) return;

    } else if (ANIMATE_MODE && nextBlock.kind === "assistant-text" && nextBlock.textEl && nextBlock.rawText) {
      // TYPEWRITER for assistant response text
      animState = STATE_TYPING_ASSISTANT;
      // Empty text nodes BEFORE unhiding to prevent full-content flash
      const preparedNodes = prepareTypeHtml(nextBlock.textEl);
      nextBlock.el.classList.remove("block-hidden");
      nextBlock.turnEl.classList.add("revealed", "active");
      applyTurnHighlight(nextTurnIdx);
      scrollToBottom();

      // Brief pause before typing begins
      await delay(Math.max(100, 200 / speed));
      if (!playing) return;

      // Calculate char delay: faster than user typing since responses are longer
      // Target ~2s at 1x for a 200-char block, minimum 5ms/char, base 15ms/char
      const rawLen = nextBlock.rawText.length;
      const totalChars = Math.max(rawLen, 1);
      const minDuration = Math.max(500, 1000 / speed);
      const maxDuration = Math.max(2000, 4000 / speed);
      const targetDuration = Math.min(maxDuration, Math.max(minDuration, (totalChars * 15) / speed));
      const charDelay = Math.max(3, targetDuration / totalChars);

      const typePromise = typeHtml(nextBlock.textEl, charDelay, preparedNodes);
      typingCancel = typePromise.cancel;

      await typePromise;
      typingCancel = null;
      if (!playing) return;

      revealedUpTo = nextIdx;
      updateProgress();
      scrollToBottom();

      // Brief pause after response before next block
      await delay(Math.max(50, 200 / speed));
      if (!playing) return;

    } else {
      // REVEAL tool/thinking/other blocks with animation (instant)
      animState = STATE_REVEALING_BLOCKS;
      nextBlock.el.classList.remove("block-hidden");
      nextBlock.turnEl.classList.add("revealed", "active");
      applyTurnHighlight(nextTurnIdx);

      revealedUpTo = nextIdx;
      updateProgress();
      scrollToBottom();

      // Delay between blocks
      const blockDelay = nextBlock.kind === "assistant-header" ? Math.max(30, 100 / speed)
                       : nextBlock.kind === "tool" ? Math.max(80, 400 / speed)
                       : nextBlock.kind === "thinking" ? Math.max(60, 300 / speed)
                       : Math.max(100, 800 / speed);
      await delay(blockDelay);
      if (!playing) return;
    }

    animState = STATE_IDLE;
    // Continue to next
    animatedTick();
  }

  function delay(ms) {
    return new Promise(resolve => {
      playTimer = setTimeout(resolve, ms);
    });
  }

  // =====================================================
  // NON-ANIMATED (classic) PLAYBACK
  // =====================================================

  function classicTick() {
    if (!playing) return;
    if (currentBlock >= allBlocks.length - 1) { stop(); return; }
    goTo(currentBlock + 1);
    const d = Math.max(100, 1500 / speed);
    playTimer = setTimeout(classicTick, d);
  }

  // =====================================================
  // TURN NAVIGATION
  // =====================================================

  function stepNextTurn() {
    if (turnSegments.length === 0) return;
    const curTurnIdx = allBlocks[currentBlock] ? allBlocks[currentBlock].turnIdx : -1;
    for (const seg of turnSegments) {
      if (seg.turnIdx > curTurnIdx) {
        goTo(seg.startBlock);
        return;
      }
    }
    goTo(allBlocks.length - 1);
  }

  function stepPrevTurn() {
    if (turnSegments.length === 0) return;
    const curTurnIdx = allBlocks[currentBlock] ? allBlocks[currentBlock].turnIdx : -1;
    let curSeg = null;
    for (const seg of turnSegments) {
      if (seg.turnIdx === curTurnIdx) { curSeg = seg; break; }
    }
    if (curSeg && currentBlock > curSeg.startBlock) {
      goTo(curSeg.startBlock);
      return;
    }
    for (let i = turnSegments.length - 1; i >= 0; i--) {
      if (turnSegments[i].turnIdx < curTurnIdx) {
        goTo(turnSegments[i].startBlock);
        return;
      }
    }
    goTo(0);
  }

  function play() {
    if (playing) return;
    playing = true;
    document.getElementById("btn-play").innerHTML = "&#x23F8;";
    if (ANIMATE_MODE) {
      animatedTick();
    } else {
      classicTick();
    }
  }

  function stop() {
    playing = false;
    document.getElementById("btn-play").innerHTML = "&#x25B6;";
    cancelAnimation();
  }

  function togglePlay() {
    if (playing) stop(); else play();
  }

  // --- Progress bar ---
  function updateProgress() {
    const activeTurnIdx = allBlocks[currentBlock] ? allBlocks[currentBlock].turnIdx : -1;
    for (const seg of turnSegments) {
      if (seg.turnIdx < activeTurnIdx) {
        seg.fillEl.style.width = "100%";
      } else if (seg.turnIdx === activeTurnIdx) {
        const posInTurn = currentBlock - seg.startBlock + 1;
        const pct = (posInTurn / seg.blockCount) * 100;
        seg.fillEl.style.width = pct + "%";
      } else {
        seg.fillEl.style.width = "0%";
      }
    }

    if (turns.length > 0 && turns[0].timestamp && turns[turns.length - 1].timestamp) {
      const startMs = new Date(turns[0].timestamp).getTime();
      const endMs = new Date(turns[turns.length - 1].timestamp).getTime();
      const currentTurn = allBlocks[currentBlock];
      let currentMs = startMs;
      if (currentTurn && turns[currentTurn.turnIdx]) {
        const ts = turns[currentTurn.turnIdx].timestamp;
        if (ts) currentMs = new Date(ts).getTime();
      }
      document.getElementById("progress-text").textContent =
        formatDuration(currentMs - startMs) + " / " + formatDuration(endMs - startMs);
    } else {
      document.getElementById("progress-text").textContent =
        (currentBlock + 1) + " / " + allBlocks.length;
    }
  }

  function progressPctToBlock(pct) {
    if (turnSegments.length === 0) return Math.round(pct * (allBlocks.length - 1));
    let cumWidth = 0;
    for (const seg of turnSegments) {
      const segWidth = seg.blockCount / allBlocks.length;
      if (pct <= cumWidth + segWidth) {
        const within = (pct - cumWidth) / segWidth;
        const blockInSeg = Math.round(within * (seg.blockCount - 1));
        return seg.startBlock + blockInSeg;
      }
      cumWidth += segWidth;
    }
    return allBlocks.length - 1;
  }

  document.getElementById("progress-bar").addEventListener("click", (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    goTo(progressPctToBlock(pct));
  });

  document.getElementById("progress-bar").addEventListener("mousemove", (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const idx = progressPctToBlock(pct);
    const tooltip = document.getElementById("progress-tooltip");
    tooltip.style.left = (pct * 100) + "%";
    if (allBlocks[idx]) {
      const t = turns[allBlocks[idx].turnIdx];
      tooltip.textContent = "Turn " + (t ? t.index : idx);
    }
  });

  // --- Speed controls ---
  function setSpeed(s) {
    speed = s;
    document.getElementById("speed-btn").textContent = s + "x";
    document.querySelectorAll("#speed-popover button, #more-popover button[data-speed]").forEach(btn => {
      btn.classList.toggle("active", parseFloat(btn.dataset.speed) === s);
    });
  }

  document.getElementById("speed-btn").onclick = () => {
    document.getElementById("speed-wrap").classList.toggle("open");
  };
  document.getElementById("speed-popover").onclick = (e) => {
    const s = e.target.dataset?.speed;
    if (s) { setSpeed(parseFloat(s)); document.getElementById("speed-wrap").classList.remove("open"); }
  };
  document.getElementById("more-popover").onclick = (e) => {
    const s = e.target.dataset?.speed;
    if (s) setSpeed(parseFloat(s));
  };

  // --- Popover toggles ---
  document.getElementById("filter-btn").onclick = () => {
    document.getElementById("filter-wrap").classList.toggle("open");
  };
  document.getElementById("more-btn").onclick = () => {
    document.getElementById("more-wrap").classList.toggle("open");
  };
  document.getElementById("chapter-btn")?.addEventListener("click", () => {
    document.getElementById("chapter-wrap").classList.toggle("open");
  });

  // Close popovers on outside click
  document.addEventListener("click", (e) => {
    for (const id of ["speed-wrap", "filter-wrap", "more-wrap", "chapter-wrap"]) {
      const el = document.getElementById(id);
      if (el && !el.contains(e.target)) el.classList.remove("open");
    }
  });

  // --- Buttons ---
  document.getElementById("btn-play").onclick = togglePlay;
  document.getElementById("btn-next-turn").onclick = stepNextTurn;
  document.getElementById("btn-prev-turn").onclick = stepPrevTurn;

  // --- Keyboard ---
  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    switch (e.key) {
      case " ": case "k": case "K": e.preventDefault(); togglePlay(); break;
      case "ArrowRight": case "l": case "L": e.preventDefault(); stepNextTurn(); break;
      case "ArrowLeft": case "h": case "H": e.preventDefault(); stepPrevTurn(); break;
    }
  });

  // --- Initialize ---
  async function init() {
    const turnsRaw = "/*TURNS_DATA*/";
    const bookmarksRaw = "/*BOOKMARKS_DATA*/";

    const decoded = await decodeData(turnsRaw);
    turns = Array.isArray(decoded) ? decoded : [];
    bookmarks = await decodeData(bookmarksRaw);
    if (!Array.isArray(bookmarks)) bookmarks = [];

    // Session metadata header
    try {
      const meta = JSON.parse(decodeURIComponent(SESSION_META));
      if (meta && meta.title) {
        document.getElementById("session-header").style.display = "";
        document.getElementById("session-title").textContent = meta.title;
        const metaParts = [];
        if (meta.session_id) metaParts.push("Session: " + meta.session_id);
        if (meta.connection_name) metaParts.push("Connection: " + meta.connection_name);
        if (meta.working_directory) metaParts.push("Dir: " + meta.working_directory);
        if (meta.created_at) metaParts.push(new Date(meta.created_at).toLocaleString());
        document.getElementById("session-meta").innerHTML =
          metaParts.map(p => "<span>" + escHtml(p) + "</span>").join("");
      }
    } catch {}

    // Build chapters
    if (bookmarks.length > 0) {
      const wrap = document.getElementById("chapter-wrap");
      wrap.style.display = "";
      const pop = document.getElementById("chapter-popover");
      for (const b of bookmarks) {
        const btn = document.createElement("button");
        btn.textContent = "Turn " + b.turn + ": " + b.label;
        btn.onclick = () => {
          const target = allBlocks.find(ab => turns[ab.turnIdx]?.index === b.turn);
          if (target) goTo(allBlocks.indexOf(target));
          wrap.classList.remove("open");
        };
        pop.appendChild(btn);
      }
    }

    // Build transcript
    allBlocks = buildTranscript(turns, bookmarks);
    buildProgressSegments();
    syncFilters();
    setSpeed(speed);

    if (allBlocks.length > 0) {
      if (ANIMATE_MODE) {
        // In animate mode, start paused at block -1
        // Show the first turn container so user sees the prompt area on load
        currentBlock = -1;
        const firstBlock = allBlocks[0];
        if (firstBlock) {
          firstBlock.turnEl.classList.add("revealed", "active");
          applyTurnHighlight(firstBlock.turnIdx);
        }
        updateProgress();
      } else {
        // Classic mode: reveal first block instantly
        goTo(0);
      }
    }
  }

  init();
})();
</script>
</body>
</html>'''


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert Cortex Code session transcripts into interactive HTML replays.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python replay.py --last -o replay.html
  python replay.py --last --theme dracula -o replay.html
  python replay.py <session-id> --turns 3-15 -o replay.html
  python replay.py --list-sessions""",
    )
    parser.add_argument("input", nargs="?", help="Session file path or session ID")
    parser.add_argument("-o", "--output", help="Output HTML file (default: stdout)")
    parser.add_argument("--last", action="store_true", help="Use the most recent session")
    parser.add_argument("--list-sessions", action="store_true", help="List available sessions")
    parser.add_argument("--list-themes", action="store_true", help="List available themes")
    parser.add_argument("--session-dir", help="Session directory override")
    parser.add_argument("--turns", help="Turn range N-M")
    parser.add_argument("--from", dest="time_from", help="Start time filter (ISO 8601)")
    parser.add_argument("--to", dest="time_to", help="End time filter (ISO 8601)")
    parser.add_argument("--speed", type=float, default=1.0, help="Initial playback speed")
    parser.add_argument("--no-thinking", action="store_true", help="Hide thinking blocks")
    parser.add_argument("--no-tool-calls", action="store_true", help="Hide tool call blocks")
    parser.add_argument("--no-animate", action="store_true",
                        help="Disable typewriter animation (use classic instant-reveal mode)")
    parser.add_argument("--theme", default="snowflake", help="Built-in theme name")
    parser.add_argument("--theme-file", help="Custom theme JSON file")
    parser.add_argument("--title", help="Page title")
    parser.add_argument("--user-label", default="User", help="Label for user messages")
    parser.add_argument("--assistant-label", default="Cortex Code", help="Label for assistant")
    parser.add_argument("--mark", action="append", help="Bookmark at turn N:Label (repeatable)")
    parser.add_argument("--bookmarks", help="JSON file with bookmarks")
    parser.add_argument("--no-redact", action="store_true", help="Disable secret redaction")
    parser.add_argument("--no-compress", action="store_true", help="Embed raw JSON")

    args = parser.parse_args()

    session_dir = Path(args.session_dir) if args.session_dir else DEFAULT_SESSION_DIR

    if args.list_themes:
        for name in sorted(BUILTIN_THEMES.keys()):
            print(name)
        return

    if args.list_sessions:
        list_sessions(session_dir)
        return

    # Resolve input file
    input_file = None
    if args.last:
        last_file = session_dir / ".last-session"
        if not last_file.exists():
            print("No .last-session file found.", file=sys.stderr)
            sys.exit(1)
        last_id = last_file.read_text().strip()
        candidate = session_dir / (last_id + ".json")
        if candidate.exists():
            input_file = str(candidate)
        else:
            input_file = find_session(last_id, session_dir)
            if not input_file:
                print(f"Last session not found: {last_id}", file=sys.stderr)
                sys.exit(1)
    else:
        if not args.input:
            print("Error: input file or --last required.", file=sys.stderr)
            sys.exit(1)
        if os.path.exists(args.input):
            input_file = args.input
        else:
            input_file = find_session(args.input, session_dir)
            if not input_file:
                print(f"Error: file not found: {args.input}", file=sys.stderr)
                sys.exit(1)

    # Resolve theme
    if args.theme_file:
        if not os.path.exists(args.theme_file):
            print(f"Error: theme file not found: {args.theme_file}", file=sys.stderr)
            sys.exit(1)
        theme = load_theme_file(args.theme_file)
    else:
        try:
            theme = get_theme(args.theme)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Parse turn range
    turn_range = None
    if args.turns:
        parts = args.turns.split("-")
        if len(parts) != 2:
            print(f"Error: invalid turn range '{args.turns}' (expected N-M)", file=sys.stderr)
            sys.exit(1)
        try:
            turn_range = (int(parts[0]), int(parts[1]))
        except ValueError:
            print(f"Error: invalid turn range '{args.turns}'", file=sys.stderr)
            sys.exit(1)

    # Parse session
    try:
        turns, meta = parse_session(input_file)
    except Exception as e:
        print(f"Error parsing session: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter
    turns = filter_turns(turns, turn_range=turn_range, time_from=args.time_from, time_to=args.time_to)

    if not turns:
        print("Warning: no turns found after filtering.", file=sys.stderr)

    # Title
    title = args.title or (f"Replay — {meta['title']}" if meta.get("title") else "Cortex Code Replay")

    # Bookmarks
    bookmarks = []
    if args.mark:
        for m in args.mark:
            sep = m.index(":")
            turn_num = int(m[:sep])
            label = m[sep + 1:]
            bookmarks.append({"turn": turn_num, "label": label})
    if args.bookmarks:
        with open(args.bookmarks) as f:
            data = json.load(f)
        for item in data:
            bookmarks.append({"turn": item["turn"], "label": item["label"]})
    bookmarks.sort(key=lambda b: b["turn"])

    # Render
    html_output = render(
        turns,
        theme=theme,
        speed=args.speed,
        show_thinking=not args.no_thinking,
        show_tool_calls=not args.no_tool_calls,
        user_label=args.user_label,
        assistant_label=args.assistant_label,
        title=title,
        redact=not args.no_redact,
        bookmarks=bookmarks,
        compress=not args.no_compress,
        meta=meta,
        animate=not args.no_animate,
    )

    if args.output:
        with open(args.output, "w") as f:
            f.write(html_output)
        print(f"Wrote {args.output} ({len(turns)} turns, {meta.get('title', 'untitled')})", file=sys.stderr)
    else:
        sys.stdout.write(html_output)


if __name__ == "__main__":
    main()
