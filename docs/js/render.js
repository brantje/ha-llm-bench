import { getFilteredModels, getFilteredTests } from "./filters.js";
import { renderMarkdown } from "./markdown.js";
import { renderStateTree } from "./json-tree.js";
import { state } from "./store.js";
import { updateCharts } from "./charts.js";
import { renderCompareTable } from "./compare.js";

/**
 * @param {number|null|undefined} n
 * @param {number} [digits]
 */
function fmt(n, digits = 2) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toFixed(digits);
}

/**
 * @param {number} sec
 */
function fmtDuration(sec) {
  if (!sec) return "0s";
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m}m ${s}s` : `${m}m`;
}

/**
 * @param {string} s
 */
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function renderAll() {
  renderMeta();
  renderKpis();
  renderLeaderboard();
  renderPricing();
  renderFilterOptions();
  renderFilterCount();
  renderTestsTable();
  updateCharts(getFilteredModels());
  renderCompare();
}

function renderMeta() {
  const vm = state.viewModel;
  const el = document.getElementById("run-meta");
  const warn = document.getElementById("activity-warning");
  if (!vm || !el) return;

  const live = vm.isLive ? " · Live (in progress)" : "";
  const finished = vm.finishedAt
    ? new Date(vm.finishedAt).toLocaleString()
    : "in progress";
  el.textContent = `Run ${vm.runId} · HA ${vm.haVersion} · ${finished}${live}`;

  if (warn) {
    const msg = vm.summary.activity_warning;
    if (msg) {
      warn.textContent = msg;
      warn.classList.remove("hidden");
    } else {
      warn.classList.add("hidden");
    }
  }
}

function renderKpis() {
  const vm = state.viewModel;
  const el = document.getElementById("kpi-strip");
  if (!vm || !el) return;
  const s = vm.summary;
  const cards = [
    ["Pass rate", `${((s.overall_pass_rate ?? 0) * 100).toFixed(1)}%`],
    ["Models", String(s.models_tested ?? vm.modelIds.length)],
    ["Total cost", `$${fmt(s.total_cost_usd, 4)}`],
    ["Test time", fmtDuration(s.total_test_time_seconds)],
    ["Run time", fmtDuration(s.total_run_time_seconds)],
    ["Avg tok/s", fmt(s.avg_tokens_per_second, 2)],
    ["Tests", String(vm.tests.length)],
  ];
  el.innerHTML = cards
    .map(
      ([label, value]) =>
        `<div class="kpi-card"><div class="kpi-value">${esc(value)}</div><div class="kpi-label">${esc(label)}</div></div>`,
    )
    .join("");
}

function renderLeaderboard() {
  const wrap = document.getElementById("leaderboard-wrap");
  if (!wrap) return;
  let models = [...getFilteredModels()];
  const { key, dir } = state.leaderboardSort;
  const mul = dir === "asc" ? 1 : -1;
  models.sort((a, b) => {
    const va = a[key];
    const vb = b[key];
    if (typeof va === "number" && typeof vb === "number") {
      return (va - vb) * mul;
    }
    return String(va).localeCompare(String(vb)) * mul;
  });

  const cols = [
    { key: "id", label: "Model" },
    { key: "testsPassed", label: "Pass" },
    { key: "testsFailed", label: "Fail" },
    { key: "passRate", label: "Pass %" },
    { key: "latencyAvg", label: "Avg ms" },
    { key: "latencyP50", label: "P50 ms" },
    { key: "latencyP95", label: "P95 ms" },
    { key: "costUsd", label: "Cost" },
    { key: "totalTokens", label: "Tokens" },
    { key: "avgTokensPerSecond", label: "Tok/s" },
    { key: "hallucinationCount", label: "Halluc." },
    { key: "clarificationCount", label: "Clarif." },
    { key: "incorrectEntityTargeting", label: "Wrong ent." },
  ];

  const thead = cols
    .map((c) => {
      const sort =
        state.leaderboardSort.key === c.key ? state.leaderboardSort.dir : "none";
      const aria = sort === "none" ? "none" : sort;
      return `<th scope="col" data-sort="${c.key}" aria-sort="${aria}">${c.label}</th>`;
    })
    .join("");

  const tbody = models
    .map((m) => {
      const active =
        state.selectedModelFilter === m.id ? " leaderboard-row-active" : "";
      return `<tr class="leaderboard-row${active}" data-model="${esc(m.id)}">
        <td>${esc(m.id)}</td>
        <td>${m.testsPassed}</td>
        <td>${m.testsFailed}</td>
        <td>${(m.passRate * 100).toFixed(1)}%</td>
        <td>${Math.round(m.latencyAvg)}</td>
        <td>${Math.round(m.latencyP50)}</td>
        <td>${Math.round(m.latencyP95)}</td>
        <td>${m.costUsd != null ? fmt(m.costUsd, 4) : "—"}</td>
        <td>${m.totalTokens != null ? Math.round(m.totalTokens) : "—"}</td>
        <td>${fmt(m.avgTokensPerSecond, 2)}</td>
        <td>${m.hallucinationCount}</td>
        <td>${m.clarificationCount}</td>
        <td>${m.incorrectEntityTargeting}</td>
      </tr>`;
    })
    .join("");

  wrap.innerHTML = `<table class="data-table" id="leaderboard-table"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;

  wrap.querySelectorAll("th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.getAttribute("data-sort");
      if (!k) return;
      if (state.leaderboardSort.key === k) {
        state.leaderboardSort.dir =
          state.leaderboardSort.dir === "asc" ? "desc" : "asc";
      } else {
        state.leaderboardSort = { key: k, dir: "desc" };
      }
      renderLeaderboard();
    });
  });

  wrap.querySelectorAll(".leaderboard-row").forEach((row) => {
    row.addEventListener("click", () => {
      const model = row.getAttribute("data-model");
      state.selectedModelFilter =
        state.selectedModelFilter === model ? null : model;
      document.getElementById("clear-model-filter")?.classList.toggle(
        "hidden",
        !state.selectedModelFilter,
      );
      renderAll();
    });
  });
}

function renderPricing() {
  const wrap = document.getElementById("pricing-wrap");
  if (!wrap || wrap.classList.contains("hidden")) return;
  const vm = state.viewModel;
  if (!vm) return;

  const blocks = vm.models
    .map((m) => {
      const keys = Object.keys(m.pricing);
      if (!keys.length) return "";
      const rows = keys
        .map(
          (k) =>
            `<tr><td>${esc(k)}</td><td>${esc(m.pricing[k])}</td></tr>`,
        )
        .join("");
      return `<div class="pricing-block"><h3>${esc(m.id)}</h3><table class="data-table"><thead><tr><th>Key</th><th>Rate (USD)</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    })
    .join("");
  wrap.innerHTML = blocks || "<p class=\"panel-hint\">No pricing data.</p>";
}

function renderFilterOptions() {
  const vm = state.viewModel;
  if (!vm) return;

  const modelSel = document.getElementById("filter-model");
  if (modelSel) {
    const selected = new Set(state.filters.models);
    modelSel.innerHTML = vm.modelIds
      .map(
        (id) =>
          `<option value="${esc(id)}"${selected.has(id) ? " selected" : ""}>${esc(id)}</option>`,
      )
      .join("");
  }

  const fileSel = document.getElementById("filter-test-file");
  if (fileSel) {
    fileSel.innerHTML =
      `<option value="all">All</option>` +
      vm.testFiles
        .map(
          (f) =>
            `<option value="${esc(f)}"${state.filters.testFile === f ? " selected" : ""}>${esc(f)}</option>`,
        )
        .join("");
  }

  const entSel = document.getElementById("filter-entity");
  if (entSel) {
    entSel.innerHTML =
      `<option value="all">All</option>` +
      vm.entities
        .map(
          (e) =>
            `<option value="${esc(e)}"${state.filters.entity === e ? " selected" : ""}>${esc(e)}</option>`,
        )
        .join("");
  }

  const outcome = document.getElementById("filter-outcome");
  if (outcome) outcome.value = state.filters.outcome;
  const search = document.getElementById("filter-search");
  if (search) search.value = state.filters.search;
  const latMin = document.getElementById("filter-latency-min");
  if (latMin) latMin.value = state.filters.latencyMin ?? "";
  const latMax = document.getElementById("filter-latency-max");
  if (latMax) latMax.value = state.filters.latencyMax ?? "";
  const costMin = document.getElementById("filter-cost-min");
  if (costMin) costMin.value = state.filters.costMin ?? "";
  const costMax = document.getElementById("filter-cost-max");
  if (costMax) costMax.value = state.filters.costMax ?? "";

  document.querySelectorAll('input[name="group-by"]').forEach((r) => {
    if (r instanceof HTMLInputElement) {
      r.checked = r.value === state.groupBy;
    }
  });
}

function renderFilterCount() {
  const el = document.getElementById("filter-count");
  if (!el) return;
  const total = state.viewModel?.tests.length ?? 0;
  const shown = getFilteredTests().length;
  el.textContent = `Showing ${shown} of ${total} tests`;
}

function flagCell(t) {
  const parts = [];
  if (t.hallucination) parts.push('<span class="flag-icon active" title="Hallucination">H</span>');
  if (t.clarification) parts.push('<span class="flag-icon active" title="Clarification">C</span>');
  if (t.incorrect_entity_targeting) parts.push('<span class="flag-icon active" title="Wrong entity">W</span>');
  return parts.length ? parts.join("") : "—";
}

function renderTestsTable() {
  const wrap = document.getElementById("tests-wrap");
  if (!wrap) return;
  const tests = getFilteredTests();
  const showModel = !state.selectedModelFilter;

  const cols = [
    { key: "outcome", label: "Outcome" },
    ...(showModel ? [{ key: "model", label: "Model" }] : []),
    { key: "nodeid", label: "Node ID" },
    { key: "command", label: "Command" },
    { key: "entity_id", label: "Entity" },
    { key: "latency_ms", label: "Latency" },
    { key: "cost_usd", label: "Cost" },
    { key: "prompt_tokens", label: "Prompt tok" },
    { key: "completion_tokens", label: "Compl tok" },
    { key: "total_tokens", label: "Total tok" },
    { key: "tokens_per_second", label: "Tok/s" },
    { key: "_flags", label: "Flags" },
    { key: "response_type", label: "Resp type" },
    { key: "response_speech", label: "Speech" },
    { key: "failure_reason", label: "Failure" },
    { key: "actual_state", label: "State" },
    { key: "changed_entities", label: "Changed" },
  ];

  const thead = cols
    .map((c) => {
      if (c.key === "_flags") {
        return `<th scope="col">${c.label}</th>`;
      }
      const sort = state.testsSort?.key === c.key ? state.testsSort.dir : "none";
      const aria = sort === "none" ? "none" : sort;
      return `<th scope="col" data-test-sort="${c.key}" aria-sort="${aria}">${c.label}</th>`;
    })
    .join("");

  const renderRow = (t) => {
    const failed = t.outcome === "failed" ? " row-failed" : "";
    const badge =
      t.outcome === "passed"
        ? '<span class="badge badge-pass">pass</span>'
        : '<span class="badge badge-fail">fail</span>';
    const changed =
      t.changed_entities && t.changed_entities.length
        ? esc(JSON.stringify(t.changed_entities))
        : "—";
    return `<tr class="${failed}">
      <td>${badge}</td>
      ${showModel ? `<td>${esc(t.model)}</td>` : ""}
      <td class="cell-nodeid">${esc(t.nodeid)}</td>
      <td>${esc(t.command ?? "—")}</td>
      <td>${esc(t.entity_id ?? "—")}</td>
      <td>${fmt(t.latency_ms, 0)}</td>
      <td>${t.cost_usd != null ? fmt(t.cost_usd, 6) : "—"}</td>
      <td>${t.prompt_tokens != null ? Math.round(t.prompt_tokens) : "—"}</td>
      <td>${t.completion_tokens != null ? Math.round(t.completion_tokens) : "—"}</td>
      <td>${t.total_tokens != null ? Math.round(t.total_tokens) : "—"}</td>
      <td>${t.tokens_per_second != null ? fmt(t.tokens_per_second, 2) : "—"}</td>
      <td>${flagCell(t)}</td>
      <td>${esc(t.response_type ?? "—")}</td>
      <td class="cell-speech"><div class="speech-md">${renderMarkdown(t.response_speech)}</div></td>
      <td class="cell-failure">${esc(t.failure_reason ?? "—")}</td>
      <td>${renderStateTree(t.actual_state)}</td>
      <td>${changed}</td>
    </tr>`;
  };

  let bodyHtml = "";
  if (state.groupBy === "none") {
    bodyHtml = tests.map(renderRow).join("");
  } else {
    const groups = new Map();
    for (const t of tests) {
      const g =
        state.groupBy === "test_file" ? t.testFile : t.entityKey;
      if (!groups.has(g)) groups.set(g, []);
      groups.get(g).push(t);
    }
    for (const [g, items] of groups) {
      const colSpan = cols.length;
      bodyHtml += `<tr class="group-header"><td colspan="${colSpan}">${esc(g)} (${items.length})</td></tr>`;
      bodyHtml += items.map(renderRow).join("");
    }
  }

  wrap.innerHTML = `<table class="data-table" id="tests-table"><thead><tr>${thead}</tr></thead><tbody>${bodyHtml || '<tr><td colspan="' + cols.length + '">No tests match filters</td></tr>'}</tbody></table>`;

  wrap.querySelectorAll("th[data-test-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.getAttribute("data-test-sort");
      if (!k) return;
      if (state.testsSort?.key === k) {
        state.testsSort.dir = state.testsSort.dir === "asc" ? "desc" : "asc";
      } else {
        state.testsSort = { key: k, dir: "asc" };
      }
      renderTestsTable();
      renderFilterCount();
    });
  });
}

function renderCompare() {
  const wrap = document.getElementById("compare-table-wrap");
  if (!wrap) return;
  if (!state.compareEnabled) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  renderCompareTable(wrap, state.compareViewA, state.compareViewB);
}

export function populateRunSelect(select, sources, currentId) {
  if (!select) return;
  select.innerHTML = sources
    .map((s) => {
      const label = s.label || s.id;
      const selected = s.id === currentId ? " selected" : "";
      return `<option value="${esc(s.id)}"${selected}>${esc(label)}</option>`;
    })
    .join("");
}
