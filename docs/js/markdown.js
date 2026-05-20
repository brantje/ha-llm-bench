/**
 * Render markdown safely.
 * @param {string|null|undefined} text
 * @returns {string}
 */
export function renderMarkdown(text) {
  if (!text) return "";
  const raw = typeof marked !== "undefined"
    ? marked.parse(text, { async: false })
    : escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  if (typeof DOMPurify !== "undefined") {
    return DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
  }
  return raw;
}

/**
 * @param {string} s
 */
function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
