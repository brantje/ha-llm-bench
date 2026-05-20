/**
 * @param {unknown} value
 * @param {string} [key]
 */
function renderValue(value, key = "") {
  if (value === null || value === undefined) {
    return `<span class="json-leaf">${key ? `<span class="json-key">${escape(key)}:</span> ` : ""}null</span>`;
  }
  if (typeof value !== "object") {
    const display = typeof value === "string" ? `"${escape(String(value))}"` : String(value);
    return `<span class="json-leaf">${key ? `<span class="json-key">${escape(key)}:</span> ` : ""}${display}</span>`;
  }
  if (Array.isArray(value)) {
    if (!value.length) {
      return `<span class="json-leaf">${key ? `<span class="json-key">${escape(key)}:</span> ` : ""}[]</span>`;
    }
    const items = value.map((v, i) => `<li>${renderValue(v, String(i))}</li>`).join("");
    return `<details><summary>${key ? `<span class="json-key">${escape(key)}</span> ` : ""}[${value.length}]</summary><ul class="json-tree">${items}</ul></details>`;
  }
  const entries = Object.entries(value);
  if (!entries.length) {
    return `<span class="json-leaf">${key ? `<span class="json-key">${escape(key)}:</span> ` : ""}{}</span>`;
  }
  const inner = entries
    .map(([k, v]) => `<li>${renderValue(v, k)}</li>`)
    .join("");
  return `<details${key ? " open" : ""}><summary>${key ? `<span class="json-key">${escape(key)}</span> ` : ""}{${entries.length}}</summary><ul class="json-tree">${inner}</ul></details>`;
}

/**
 * @param {string} s
 */
function escape(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

/**
 * @param {string|null|undefined} raw
 * @returns {string}
 */
export function renderStateTree(raw) {
  if (raw == null || raw === "") return '<span class="json-leaf">—</span>';
  let parsed = raw;
  if (typeof raw === "string") {
    try {
      parsed = JSON.parse(raw);
    } catch {
      return `<pre class="json-tree">${escape(raw)}</pre>`;
    }
  }
  return `<div class="json-tree">${renderValue(parsed)}</div>`;
}
