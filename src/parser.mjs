/**
 * Parse Cortex Code JSON session files into structured turns.
 *
 * Cortex Code stores session metadata in a `.json` file and history in a
 * separate `.history.jsonl` sidecar file (one message per line). This parser
 * handles both the sidecar format and the legacy embedded `history` array,
 * along with nested tool_use/tool_result wrappers, internalOnly flags,
 * system-reminder filtering, and user_sent_time timestamps.
 */

import { existsSync, readFileSync } from "node:fs";

/**
 * @typedef {{ tool_use_id: string, name: string, input: object, result: string|null, resultTimestamp: string|null, status: string|null }} ToolCall
 * @typedef {{ kind: string, text: string, tool_call: ToolCall|null, timestamp: string|null }} AssistantBlock
 * @typedef {{ index: number, user_text: string, blocks: AssistantBlock[], timestamp: string, system_events?: string[] }} Turn
 * @typedef {{ title: string, session_id: string, created_at: string, last_updated: string, connection_name: string|null, working_directory: string|null }} SessionMeta
 */

/**
 * Strip system-reminder tags and other internal markup from text.
 */
function cleanSystemTags(text) {
  // Remove <system-reminder> blocks
  text = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>\s*/g, "");
  // Remove <local-command-caveat> boilerplate
  text = text.replace(/<local-command-caveat>[\s\S]*?<\/local-command-caveat>\s*/g, "");
  // Extract slash command name, keep as visible text
  text = text.replace(/<command-name>([\s\S]*?)<\/command-name>\s*/g, (_, name) => name.trim() + "\n");
  // Remove command-message (redundant with command-name) and empty args
  text = text.replace(/<command-message>[\s\S]*?<\/command-message>\s*/g, "");
  text = text.replace(/<command-args>\s*<\/command-args>\s*/g, "");
  // Keep non-empty command args
  text = text.replace(/<command-args>([\s\S]*?)<\/command-args>\s*/g, (_, args) => {
    const trimmed = args.trim();
    return trimmed ? trimmed + "\n" : "";
  });
  // Remove local command stdout
  text = text.replace(/<local-command-stdout>[\s\S]*?<\/local-command-stdout>\s*/g, "");
  // Replace task-notification blocks with compact markers
  text = text.replace(
    /<task-notification>\s*<task-id>[^<]*<\/task-id>\s*<output-file>[^<]*<\/output-file>\s*<status>([^<]*)<\/status>\s*<summary>([^<]*)<\/summary>\s*<\/task-notification>/g,
    (_, status, summary) => `[bg-task: ${summary}]`
  );
  text = text.replace(/\n*Read the output file to retrieve the result:[^\n]*/g, "");
  return text.trim();
}

/**
 * Extract visible user text from a message's content blocks.
 * Filters out internalOnly blocks and system reminders.
 */
function extractUserText(content) {
  if (typeof content === "string") return cleanSystemTags(content);
  const parts = [];
  for (const block of content) {
    if (block.type !== "text") continue;
    // Skip internal-only blocks (system reminders injected by the platform)
    if (block.internalOnly === true) continue;
    // Skip blocks that are system prompts, not user text
    if (block.is_user_prompt === false && !block.displayText) continue;
    // Use displayText if available (compact representation)
    const text = block.displayText || block.text || "";
    if (text) parts.push(text);
  }
  return cleanSystemTags(parts.join("\n"));
}

/**
 * Check if a user message contains only tool_result blocks (no user text).
 */
function isToolResultOnly(content) {
  if (typeof content === "string") return false;
  if (!Array.isArray(content)) return false;
  return content.every(
    (b) => b.type === "tool_result" || (b.type === "text" && b.internalOnly === true)
  );
}

/**
 * Collect assistant content blocks from consecutive assistant messages
 * starting at index `start`. Returns [blocks, nextIndex].
 */
function collectAssistantBlocks(history, start) {
  const blocks = [];
  const seenKeys = new Set();
  let i = start;

  while (i < history.length) {
    const entry = history[i];
    if (entry.role !== "assistant") break;

    const timestamp = entry.user_sent_time || null;
    const content = entry.content || [];

    if (Array.isArray(content)) {
      for (const block of content) {
        if (block.type === "text") {
          const text = (block.text ?? "").trim();
          if (!text || text === "No response requested.") continue;
          const key = `text:${text}`;
          if (seenKeys.has(key)) continue;
          seenKeys.add(key);
          blocks.push({ kind: "text", text, tool_call: null, timestamp });
        } else if (block.type === "thinking") {
          // Cortex Code nests thinking text: {type: "thinking", thinking: {text, signature}}
          const thinkObj = block.thinking || {};
          const text = (typeof thinkObj === "string" ? thinkObj : thinkObj.text ?? "").trim();
          if (!text) continue;
          const key = `thinking:${text}`;
          if (seenKeys.has(key)) continue;
          seenKeys.add(key);
          blocks.push({ kind: "thinking", text, tool_call: null, timestamp });
        } else if (block.type === "tool_use") {
          // Cortex Code nests: {type: "tool_use", tool_use: {tool_use_id, name, input}}
          const tu = block.tool_use || block;
          const toolId = tu.tool_use_id || tu.id || "";
          const key = `tool_use:${toolId}`;
          if (seenKeys.has(key)) continue;
          seenKeys.add(key);
          blocks.push({
            kind: "tool_use",
            text: "",
            tool_call: {
              tool_use_id: toolId,
              name: tu.name || "",
              input: tu.input || {},
              result: null,
              resultTimestamp: null,
              status: null,
            },
            timestamp,
          });
        }
      }
    }
    i++;
  }

  return [blocks, i];
}

/**
 * Scan forward from resultStart for user messages containing tool_result blocks.
 * Match them to tool_use blocks by tool_use_id.
 * Returns index after consumed entries.
 */
function attachToolResults(blocks, history, resultStart) {
  const pending = new Map();
  for (const b of blocks) {
    if (b.kind === "tool_use" && b.tool_call) {
      pending.set(b.tool_call.tool_use_id, b.tool_call);
    }
  }
  if (pending.size === 0) return resultStart;

  let i = resultStart;
  while (i < history.length && pending.size > 0) {
    const entry = history[i];
    if (entry.role === "assistant") break;
    if (entry.role === "user") {
      const content = entry.content || [];
      if (Array.isArray(content)) {
        let hasToolResult = false;
        for (const block of content) {
          if (block.type === "tool_result") {
            hasToolResult = true;
            // Cortex Code nests: {type: "tool_result", tool_result: {tool_use_id, name, content, status}}
            const tr = block.tool_result || block;
            const tid = tr.tool_use_id || "";
            if (pending.has(tid)) {
              const resultContent = tr.content;
              let resultText;
              if (Array.isArray(resultContent)) {
                resultText = resultContent
                  .filter((p) => p.type === "text")
                  .map((p) => p.text ?? "")
                  .join("\n");
              } else if (typeof resultContent === "string") {
                resultText = resultContent;
              } else {
                resultText = String(resultContent ?? "");
              }
              const tc = pending.get(tid);
              tc.result = resultText;
              tc.resultTimestamp = entry.user_sent_time || null;
              tc.status = tr.status || null;
              pending.delete(tid);
            }
          }
        }
        if (!hasToolResult) break;
      } else {
        break;
      }
    }
    i++;
  }

  return i;
}

/**
 * Parse a Cortex Code session JSON file into a list of Turns.
 * @param {string} filePath
 * @returns {{ turns: Turn[], meta: SessionMeta }}
 */
export function parseSession(filePath) {
  const raw = readFileSync(filePath, "utf-8");
  const session = JSON.parse(raw);

  const meta = {
    title: session.title || "",
    session_id: session.session_id || "",
    created_at: session.created_at || "",
    last_updated: session.last_updated || "",
    connection_name: session.connection_name || null,
    working_directory: session.working_directory || null,
  };

  let history = session.history || [];

  // New format: history stored in a separate .history.jsonl sidecar file
  if (history.length === 0) {
    const jsonlPath = filePath.replace(/\.json$/, ".history.jsonl");
    if (existsSync(jsonlPath)) {
      history = readFileSync(jsonlPath, "utf-8")
        .split("\n")
        .filter(Boolean)
        .map(line => JSON.parse(line));
    }
  }

  const turns = [];
  let i = 0;
  let turnIndex = 0;

  while (i < history.length) {
    const entry = history[i];

    if (entry.role === "user") {
      const content = entry.content || [];

      // Skip pure tool-result messages (they get attached to previous turn)
      if (isToolResultOnly(content)) {
        i++;
        continue;
      }

      let userText = extractUserText(content);
      const timestamp = entry.user_sent_time || "";
      i++;

      // Absorb consecutive non-tool-result user messages into the same turn
      while (i < history.length) {
        const next = history[i];
        if (next.role !== "user") break;
        const nextContent = next.content || [];
        if (isToolResultOnly(nextContent)) break;
        const nextText = extractUserText(nextContent);
        if (nextText) userText = userText ? userText + "\n" + nextText : nextText;
        i++;
      }

      // Extract system events (bg-task notifications) from user text
      const systemEvents = [];
      userText = userText.replace(/\[bg-task:\s*(.+)\]/g, (_, summary) => {
        systemEvents.push(summary);
        return "";
      });
      userText = userText.trim();

      const [assistantBlocks, nextI] = collectAssistantBlocks(history, i);
      i = nextI;
      i = attachToolResults(assistantBlocks, history, i);

      turnIndex++;
      const turn = {
        index: turnIndex,
        user_text: userText,
        blocks: assistantBlocks,
        timestamp,
      };
      if (systemEvents.length) turn.system_events = systemEvents;
      turns.push(turn);
    } else if (entry.role === "assistant") {
      const [assistantBlocks, nextI] = collectAssistantBlocks(history, i);
      i = nextI;
      i = attachToolResults(assistantBlocks, history, i);

      // Merge orphan assistant blocks into the previous turn
      if (turns.length > 0) {
        turns[turns.length - 1].blocks.push(...assistantBlocks);
      } else {
        // No previous turn — create one (first entry is assistant)
        turnIndex++;
        turns.push({
          index: turnIndex,
          user_text: "",
          blocks: assistantBlocks,
          timestamp: entry.user_sent_time || "",
        });
      }
    } else {
      i++;
    }
  }

  // Drop empty turns
  const filtered = turns.filter((t) => {
    if (t.user_text) return true;
    if (t.system_events?.length) return true;
    return t.blocks.some((b) => {
      if (b.kind === "tool_use") return true;
      if (b.kind === "text" && b.text && b.text !== "No response requested.") return true;
      if (b.kind === "thinking" && b.text) return true;
      return false;
    });
  });

  // Re-index after filtering
  for (let j = 0; j < filtered.length; j++) {
    filtered[j].index = j + 1;
  }

  return { turns: filtered, meta };
}

/**
 * Filter turns by range or time window.
 * @param {Turn[]} turns
 * @param {{ turnRange?: [number, number], timeFrom?: string, timeTo?: string }} opts
 * @returns {Turn[]}
 */
export function filterTurns(turns, opts = {}) {
  let result = turns;

  if (opts.turnRange) {
    const [start, end] = opts.turnRange;
    result = result.filter((t) => t.index >= start && t.index <= end);
  }

  if (opts.timeFrom) {
    const from = new Date(opts.timeFrom).getTime();
    result = result.filter((t) => !t.timestamp || new Date(t.timestamp).getTime() >= from);
  }

  if (opts.timeTo) {
    const to = new Date(opts.timeTo).getTime();
    result = result.filter((t) => !t.timestamp || new Date(t.timestamp).getTime() <= to);
  }

  // Re-index after filtering
  for (let j = 0; j < result.length; j++) {
    result[j].index = j + 1;
  }

  return result;
}
