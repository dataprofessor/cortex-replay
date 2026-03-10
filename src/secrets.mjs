/**
 * Secret detection and redaction for replay output.
 * Adapted from claude-replay with additional Snowflake-specific patterns.
 */

const REDACTED = "[REDACTED]";

/** @type {Array<{ name: string, pattern: RegExp }>} */
export const SECRET_PATTERNS = [
  // Private keys (multi-line, checked first)
  {
    name: "private_key",
    pattern:
      /-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----/g,
  },
  // AWS access key IDs
  { name: "aws_key", pattern: /AKIA[0-9A-Z]{16}/g },
  // Anthropic API keys
  { name: "sk_ant_key", pattern: /sk-ant-[a-zA-Z0-9-]{20,}/g },
  // Generic sk- / key- prefixed secrets
  { name: "sk_key", pattern: /sk-[a-zA-Z0-9-]{20,}/g },
  { name: "key_prefix", pattern: /key-[a-zA-Z0-9]{20,}/g },
  // Bearer tokens
  { name: "bearer", pattern: /Bearer [A-Za-z0-9_.~+/=-]{20,}/g },
  // JWT tokens
  {
    name: "jwt",
    pattern: /eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+/g,
  },
  // Connection strings (including Snowflake)
  {
    name: "connection_string",
    pattern:
      /(?:mongodb|postgres|mysql|redis|amqp|mssql|snowflake):\/\/[^\s"']+/g,
  },
  // Snowflake account tokens and session tokens
  {
    name: "snowflake_token",
    pattern: /(?:snowflakeToken|masterToken|sessionToken)\s*[:=]\s*["']?[^\s"',]{20,}["']?/gi,
  },
  // Generic key=value secrets
  {
    name: "key_value",
    pattern:
      /(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?key|auth[_-]?token|bearer|password|passwd)\s*[:=]\s*["']?[^\s"',]{8,}["']?/gi,
  },
  // Env var patterns (PASSWORD=..., TOKEN=..., etc.)
  {
    name: "env_var",
    pattern:
      /(?:PASSWORD|TOKEN|SECRET|CREDENTIAL|PRIVATE_KEY|SNOWFLAKE_PASSWORD|SF_PASSWORD)=[^\s]+/g,
  },
  // Standalone hex tokens (40+ hex chars, word-bounded)
  { name: "hex_token", pattern: /\b[0-9a-fA-F]{40,}\b/g },
];

/**
 * Replace detected secrets in a string with [REDACTED].
 * @param {string} text
 * @returns {string}
 */
export function redactSecrets(text) {
  if (typeof text !== "string") return text;
  let result = text;
  for (const { pattern } of SECRET_PATTERNS) {
    pattern.lastIndex = 0;
    result = result.replace(pattern, REDACTED);
  }
  return result;
}

/**
 * Recursively walk an object/array, redacting string values.
 * @param {unknown} obj
 * @returns {unknown}
 */
export function redactObject(obj) {
  if (typeof obj === "string") return redactSecrets(obj);
  if (Array.isArray(obj)) return obj.map(redactObject);
  if (obj !== null && typeof obj === "object") {
    const out = {};
    for (const [key, value] of Object.entries(obj)) {
      out[key] = redactObject(value);
    }
    return out;
  }
  return obj;
}
