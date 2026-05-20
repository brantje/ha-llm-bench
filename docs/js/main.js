import { parseReport } from "./parse.js";
import {
  state,
  setViewModel,
  subscribe,
  notify,
  resetFilters,
} from "./store.js";
import {
  loadFiltersFromHash,
  syncFiltersToHash,
} from "./filters.js";
import { renderAll, populateRunSelect } from "./render.js";
import { destroyCharts } from "./charts.js";

/** Reports base: local dev serves /docs/ from repo root; Pages serves docs as site root. */
function reportsBase() {
  return window.location.pathname.includes("/docs") ? "../reports/" : "reports/";
}

function reportPath(relative) {
  return `${reportsBase()}${relative}`;
}

const paths = () => ({
  report: reportPath("report.json"),
  results: reportPath("results.json"),
  historyIndex: reportPath("history/index.json"),
});

/** @type {{ id: string, label: string, url: string }[]} */
let runSources = [];

/** @type {Map<string, object>} */
const reportCache = new Map();

/**
 * @param {string} url
 */
async function fetchJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} — ${url}`);
  return res.json();
}

/**
 * @param {string} sourceId
 */
async function loadSource(sourceId) {
  const src = runSources.find((s) => s.id === sourceId);
  if (!src) throw new Error(`Unknown source: ${sourceId}`);
  if (reportCache.has(src.url)) {
    return reportCache.get(src.url);
  }
  const data = await fetchJson(src.url);
  reportCache.set(src.url, data);
  return data;
}

async function buildRunSources() {
  const PATHS = paths();
  const sources = [
    { id: "report", label: "Current report", url: PATHS.report },
    { id: "results", label: "Live results", url: PATHS.results },
  ];

  try {
    const index = await fetchJson(PATHS.historyIndex);
    if (Array.isArray(index)) {
      for (const entry of index) {
        const path =
          entry.path ||
          `history/${sanitizeRunId(entry.run_id)}/report.json`;
        const url = path.startsWith("../") || path.startsWith("reports/")
          ? path
          : reportPath(path);
        const started = entry.started_at
          ? new Date(entry.started_at).toLocaleString()
          : entry.run_id;
        sources.push({
          id: `history:${entry.run_id}`,
          label: `History · ${started}`,
          url,
        });
      }
    }
  } catch {
    /* no history manifest yet */
  }

  runSources = sources;
  return sources;
}

/**
 * @param {string} runId
 */
function sanitizeRunId(runId) {
  return runId.replace(/[:.]/g, "-").replace(/\+/g, "_");
}

async function selectRun(sourceId) {
  state.sourceId = sourceId;
  const errEl = document.getElementById("load-error");
  try {
    if (errEl) errEl.classList.add("hidden");
    const raw = await loadSource(sourceId);
    const vm = parseReport(raw);
    setViewModel(vm);
    reportCache.set(
      runSources.find((s) => s.id === sourceId)?.url ?? "",
      raw,
    );
  } catch (e) {
    if (errEl) {
      errEl.textContent = `Failed to load: ${e.message}. Local: python3 -m http.server 8080 from repo root → http://localhost:8080/docs/ — or open the GitHub Pages URL after a main-branch deploy.`;
      errEl.classList.remove("hidden");
    }
    setViewModel(null);
  }
}

function setupRefresh() {
  if (state.refreshInterval) {
    clearInterval(state.refreshInterval);
    state.refreshInterval = null;
  }
  const cb = document.getElementById("live-refresh");
  if (!cb?.checked || state.sourceId !== "results") return;
  state.refreshInterval = setInterval(async () => {
    reportCache.delete(paths().results);
    await selectRun("results");
  }, 30000);
}

function wireFilters() {
  const bind = (id, handler) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("change", handler);
    el.addEventListener("input", handler);
  };

  bind("filter-outcome", () => {
    state.filters.outcome =
      document.getElementById("filter-outcome")?.value ?? "all";
    syncFiltersToHash();
    notify();
  });

  bind("filter-model", () => {
    const sel = document.getElementById("filter-model");
    state.filters.models = sel
      ? [...sel.selectedOptions].map((o) => o.value)
      : [];
    syncFiltersToHash();
    notify();
  });

  bind("filter-test-file", () => {
    state.filters.testFile =
      document.getElementById("filter-test-file")?.value ?? "all";
    syncFiltersToHash();
    notify();
  });

  bind("filter-entity", () => {
    state.filters.entity =
      document.getElementById("filter-entity")?.value ?? "all";
    syncFiltersToHash();
    notify();
  });

  bind("filter-search", () => {
    state.filters.search =
      document.getElementById("filter-search")?.value ?? "";
    syncFiltersToHash();
    notify();
  });

  const numFilter = (id, key) => {
    bind(id, () => {
      const v = document.getElementById(id)?.value;
      state.filters[key] = v === "" || v == null ? null : Number(v);
      syncFiltersToHash();
      notify();
    });
  };
  numFilter("filter-latency-min", "latencyMin");
  numFilter("filter-latency-max", "latencyMax");
  numFilter("filter-cost-min", "costMin");
  numFilter("filter-cost-max", "costMax");

  for (const id of [
    "filter-hallucination",
    "filter-clarification",
    "filter-wrong-entity",
    "filter-flag-any",
  ]) {
    bind(id, () => {
      const el = document.getElementById(id);
      if (!el) return;
      if (id === "filter-hallucination") state.filters.hallucination = el.checked;
      if (id === "filter-clarification") state.filters.clarification = el.checked;
      if (id === "filter-wrong-entity") state.filters.wrongEntity = el.checked;
      if (id === "filter-flag-any") state.filters.flagAny = el.checked;
      syncFiltersToHash();
      notify();
    });
  }

  document.getElementById("filter-clear")?.addEventListener("click", () => {
    resetFilters();
    loadFiltersFromHash();
    syncFiltersToHash();
    notify();
  });

  document.querySelectorAll('input[name="group-by"]').forEach((r) => {
    r.addEventListener("change", () => {
      if (r.checked) {
        state.groupBy = r.value;
        syncFiltersToHash();
        notify();
      }
    });
  });

  document.getElementById("clear-model-filter")?.addEventListener("click", () => {
    state.selectedModelFilter = null;
    document.getElementById("clear-model-filter")?.classList.add("hidden");
    syncFiltersToHash();
    notify();
  });
}

function wireCompare() {
  const toggle = document.getElementById("compare-toggle");
  const controls = document.getElementById("compare-controls");
  const wrap = document.getElementById("compare-table-wrap");

  toggle?.addEventListener("click", () => {
    state.compareEnabled = !state.compareEnabled;
    toggle.textContent = state.compareEnabled ? "Disable compare" : "Enable compare";
    controls?.classList.toggle("hidden", !state.compareEnabled);
    wrap?.classList.toggle("hidden", !state.compareEnabled);
    if (state.compareEnabled) loadCompareRuns();
    notify();
  });

  const onCompareChange = async () => {
    const a = document.getElementById("compare-run-a")?.value;
    const b = document.getElementById("compare-run-b")?.value;
    state.compareRunA = a ?? null;
    state.compareRunB = b ?? null;
    if (a) {
      const raw = await loadSource(a);
      state.compareViewA = parseReport(raw);
    } else state.compareViewA = null;
    if (b) {
      const raw = await loadSource(b);
      state.compareViewB = parseReport(raw);
    } else state.compareViewB = null;
    notify();
  };

  document.getElementById("compare-run-a")?.addEventListener("change", onCompareChange);
  document.getElementById("compare-run-b")?.addEventListener("change", onCompareChange);
}

async function loadCompareRuns() {
  populateRunSelect(
    document.getElementById("compare-run-a"),
    runSources,
    state.compareRunA ?? "report",
  );
  populateRunSelect(
    document.getElementById("compare-run-b"),
    runSources,
    state.compareRunB ?? "results",
  );
  const a = document.getElementById("compare-run-a")?.value;
  const b = document.getElementById("compare-run-b")?.value;
  if (a) state.compareViewA = parseReport(await loadSource(a));
  if (b) state.compareViewB = parseReport(await loadSource(b));
}

async function init() {
  loadFiltersFromHash();
  const sources = await buildRunSources();
  const runSelect = document.getElementById("run-select");
  const hashRun = new URLSearchParams(location.hash.slice(1)).get("run");
  const initial = hashRun && sources.some((s) => s.id === hashRun) ? hashRun : "report";
  populateRunSelect(runSelect, sources, initial);

  runSelect?.addEventListener("change", async () => {
    const id = runSelect.value;
    state.sourceId = id;
    const params = new URLSearchParams(location.hash.slice(1));
    params.set("run", id);
    location.hash = params.toString() ? `#${params.toString()}` : "#run=" + id;
    reportCache.delete(runSources.find((s) => s.id === id)?.url ?? "");
    await selectRun(id);
    setupRefresh();
  });

  document.getElementById("live-refresh")?.addEventListener("change", setupRefresh);

  document.getElementById("copy-json")?.addEventListener("click", async () => {
    const raw = state.viewModel?.raw;
    if (!raw) return;
    await navigator.clipboard.writeText(JSON.stringify(raw, null, 2));
    const btn = document.getElementById("copy-json");
    if (btn) {
      const prev = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => {
        btn.textContent = prev;
      }, 2000);
    }
  });

  document.getElementById("pricing-toggle")?.addEventListener("click", () => {
    const wrap = document.getElementById("pricing-wrap");
    const btn = document.getElementById("pricing-toggle");
    if (!wrap || !btn) return;
    const isHidden = wrap.classList.toggle("hidden");
    btn.setAttribute("aria-expanded", String(!isHidden));
    btn.textContent = isHidden ? "Show pricing" : "Hide pricing";
    if (!isHidden) renderAll();
  });

  wireFilters();
  wireCompare();

  subscribe(() => renderAll());

  await selectRun(initial);
  setupRefresh();
}

window.addEventListener("hashchange", () => {
  loadFiltersFromHash();
  const params = new URLSearchParams(location.hash.slice(1));
  const run = params.get("run");
  if (run && run !== state.sourceId) {
    const sel = document.getElementById("run-select");
    if (sel) sel.value = run;
    selectRun(run);
  } else {
    notify();
  }
});

init().catch((e) => {
  const errEl = document.getElementById("load-error");
  if (errEl) {
    errEl.textContent = String(e);
    errEl.classList.remove("hidden");
  }
});

window.addEventListener("beforeunload", () => {
  destroyCharts();
  if (state.refreshInterval) clearInterval(state.refreshInterval);
});
