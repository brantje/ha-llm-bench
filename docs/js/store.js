/**
 * @typedef {object} ViewModel
 * @property {object} raw
 * @property {string} runId
 * @property {string} startedAt
 * @property {string|null} finishedAt
 * @property {string} haVersion
 * @property {object} summary
 * @property {boolean} isLive
 * @property {ModelRow[]} models
 * @property {TestRow[]} tests
 * @property {string[]} testFiles
 * @property {string[]} entities
 * @property {string[]} modelIds
 */

/**
 * @typedef {object} ModelRow
 * @property {string} id
 * @property {number} testsTotal
 * @property {number} testsPassed
 * @property {number} testsFailed
 * @property {number} passRate
 * @property {number} latencyAvg
 * @property {number} latencyP50
 * @property {number} latencyP95
 * @property {number|null} costUsd
 * @property {object} pricing
 */

/**
 * @typedef {object} Filters
 * @property {string} outcome
 * @property {string[]} models
 * @property {string} testFile
 * @property {string} entity
 * @property {string} search
 * @property {number|null} latencyMin
 * @property {number|null} latencyMax
 * @property {number|null} costMin
 * @property {number|null} costMax
 * @property {boolean} hallucination
 * @property {boolean} clarification
 * @property {boolean} wrongEntity
 * @property {boolean} flagAny
 */

/** @type {ViewModel|null} */
let viewModel = null;

/** @type {Filters} */
const defaultFilters = () => ({
  outcome: "all",
  models: [],
  testFile: "all",
  entity: "all",
  search: "",
  latencyMin: null,
  latencyMax: null,
  costMin: null,
  costMax: null,
  hallucination: false,
  clarification: false,
  wrongEntity: false,
  flagAny: false,
});

export const state = {
  viewModel: null,
  filters: defaultFilters(),
  groupBy: "none",
  selectedModelFilter: null,
  leaderboardSort: { key: "passRate", dir: "desc" },
  testsSort: null,
  compareEnabled: false,
  compareRunA: null,
  compareRunB: null,
  compareViewA: null,
  compareViewB: null,
  sourceId: "report",
  refreshInterval: null,
};

/** @type {Set<() => void>} */
const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function notify() {
  for (const fn of listeners) fn();
}

export function setViewModel(vm) {
  state.viewModel = vm;
  viewModel = vm;
  notify();
}

export function resetFilters() {
  state.filters = defaultFilters();
  state.selectedModelFilter = null;
  state.testsSort = null;
  notify();
}

export function setFilters(partial) {
  state.filters = { ...state.filters, ...partial };
  notify();
}

export function getViewModel() {
  return state.viewModel;
}
