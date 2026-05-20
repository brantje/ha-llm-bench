import { buildModelCompare } from "./parse.js";

/**
 * @param {HTMLElement} container
 * @param {import('./store.js').ViewModel|null} viewA
 * @param {import('./store.js').ViewModel|null} viewB
 */
export function renderCompareTable(container, viewA, viewB) {
  if (!viewA || !viewB) {
    container.innerHTML = "<p class=\"panel-hint\">Select two runs to compare.</p>";
    return;
  }

  const rows = buildModelCompare(viewA, viewB);
  const fmtPct = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
  const fmtNum = (v, digits = 2) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}`;
  const deltaClass = (v, invert = false) => {
    if (v == null || v === 0) return "";
    const good = invert ? v < 0 : v > 0;
    return good ? "delta-positive" : "delta-negative";
  };

  const trs = rows
    .map((r) => {
      const prA = r.passRateA != null ? `${(r.passRateA * 100).toFixed(0)}%` : "—";
      const prB = r.passRateB != null ? `${(r.passRateB * 100).toFixed(0)}%` : "—";
      return `<tr>
        <td>${escape(r.id)}</td>
        <td>${r.inA ? prA : "<em>—</em>"}</td>
        <td>${r.inB ? prB : "<em>—</em>"}</td>
        <td class="${deltaClass(r.passRateDelta)}">${fmtPct(r.passRateDelta)}</td>
        <td>${r.costA != null ? r.costA.toFixed(4) : "—"}</td>
        <td>${r.costB != null ? r.costB.toFixed(4) : "—"}</td>
        <td class="${deltaClass(r.costDelta, true)}">${fmtNum(r.costDelta, 4)}</td>
        <td>${r.latencyA != null ? Math.round(r.latencyA) : "—"}</td>
        <td>${r.latencyB != null ? Math.round(r.latencyB) : "—"}</td>
        <td class="${deltaClass(r.latencyDelta, true)}">${fmtNum(r.latencyDelta, 0)}</td>
      </tr>`;
    })
    .join("");

  container.innerHTML = `
    <p class="panel-hint">A: ${escape(viewA.runId)} · B: ${escape(viewB.runId)}</p>
    <table class="data-table" scope="colgroup">
      <thead>
        <tr>
          <th scope="col">Model</th>
          <th scope="col">Pass A</th>
          <th scope="col">Pass B</th>
          <th scope="col">Δ pass</th>
          <th scope="col">Cost A</th>
          <th scope="col">Cost B</th>
          <th scope="col">Δ cost</th>
          <th scope="col">Lat A</th>
          <th scope="col">Lat B</th>
          <th scope="col">Δ lat</th>
        </tr>
      </thead>
      <tbody>${trs}</tbody>
    </table>`;
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
