import { state } from "./store.js";

/**
 * @param {import('./parse.js').parseReport extends (r: object) => infer V ? V : never} test
 */
export function matchesFilters(test) {
  const f = state.filters;
  if (state.selectedModelFilter && test.model !== state.selectedModelFilter) {
    return false;
  }
  if (f.outcome !== "all" && test.outcome !== f.outcome) return false;
  if (f.models.length && !f.models.includes(test.model)) return false;
  if (f.testFile !== "all" && test.testFile !== f.testFile) return false;
  if (f.entity !== "all" && test.entityKey !== f.entity) return false;

  if (f.hallucination && !test.hallucination) return false;
  if (f.clarification && !test.clarification) return false;
  if (f.wrongEntity && !test.incorrect_entity_targeting) return false;
  if (f.flagAny && !(test.hallucination || test.clarification || test.incorrect_entity_targeting)) {
    return false;
  }

  if (f.latencyMin != null && test.latency_ms < f.latencyMin) return false;
  if (f.latencyMax != null && test.latency_ms > f.latencyMax) return false;
  if (f.costMin != null && (test.cost_usd ?? 0) < f.costMin) return false;
  if (f.costMax != null && (test.cost_usd ?? 0) > f.costMax) return false;

  if (f.search.trim()) {
    const q = f.search.trim().toLowerCase();
    const hay = [
      test.nodeid,
      test.command,
      test.response_speech,
      test.failure_reason,
      test.entity_id,
      test.model,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!hay.includes(q)) return false;
  }

  return true;
}

/**
 * @returns {import('./store.js').ViewModel['tests']}
 */
export function getFilteredTests() {
  const vm = state.viewModel;
  if (!vm) return [];
  let list = vm.tests.filter(matchesFilters);

  if (state.testsSort) {
    const { key, dir } = state.testsSort;
    const mul = dir === "asc" ? 1 : -1;
    list = [...list].sort((a, b) => {
      const va = a[key];
      const vb = b[key];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") {
        return (va - vb) * mul;
      }
      return String(va).localeCompare(String(vb)) * mul;
    });
  }

  return list;
}

/**
 * @returns {import('./store.js').ViewModel['models']}
 */
export function getFilteredModels() {
  const vm = state.viewModel;
  if (!vm) return [];
  const f = state.filters;
  if (!f.models.length) return vm.models;
  return vm.models.filter((m) => f.models.includes(m.id));
}

/**
 * @param {string} key
 * @param {unknown} val
 */
function hashSet(key, val) {
  const params = new URLSearchParams(location.hash.slice(1));
  if (val === null || val === "" || val === "all" || (Array.isArray(val) && !val.length)) {
    params.delete(key);
  } else if (Array.isArray(val)) {
    params.set(key, val.join(","));
  } else {
    params.set(key, String(val));
  }
  const s = params.toString();
  location.hash = s ? `#${s}` : "";
}

export function syncFiltersToHash() {
  const f = state.filters;
  hashSet("outcome", f.outcome === "all" ? null : f.outcome);
  hashSet("models", f.models.length ? f.models : null);
  hashSet("testFile", f.testFile === "all" ? null : f.testFile);
  hashSet("entity", f.entity === "all" ? null : f.entity);
  hashSet("search", f.search || null);
  hashSet("groupBy", state.groupBy === "none" ? null : state.groupBy);
  hashSet("modelFilter", state.selectedModelFilter);
  if (f.latencyMin != null) hashSet("latMin", f.latencyMin);
  else hashSet("latMin", null);
  if (f.latencyMax != null) hashSet("latMax", f.latencyMax);
  else hashSet("latMax", null);
  if (f.costMin != null) hashSet("costMin", f.costMin);
  else hashSet("costMin", null);
  if (f.costMax != null) hashSet("costMax", f.costMax);
  else hashSet("costMax", null);
}

export function loadFiltersFromHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.toString()) return;

  const models = params.get("models");
  state.filters.outcome = params.get("outcome") || "all";
  state.filters.models = models ? models.split(",") : [];
  state.filters.testFile = params.get("testFile") || "all";
  state.filters.entity = params.get("entity") || "all";
  state.filters.search = params.get("search") || "";
  const latMin = params.get("latMin");
  const latMax = params.get("latMax");
  const costMin = params.get("costMin");
  const costMax = params.get("costMax");
  state.filters.latencyMin = latMin != null ? Number(latMin) : null;
  state.filters.latencyMax = latMax != null ? Number(latMax) : null;
  state.filters.costMin = costMin != null ? Number(costMin) : null;
  state.filters.costMax = costMax != null ? Number(costMax) : null;
  state.groupBy = params.get("groupBy") || "none";
  state.selectedModelFilter = params.get("modelFilter");
}
