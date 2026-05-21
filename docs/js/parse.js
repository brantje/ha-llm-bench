/** @typedef {import('./store.js').ViewModel} ViewModel */

/**
 * Parse nodeid into test file path.
 * @param {string} nodeid
 */
export function parseTestFile(nodeid) {
  const match = nodeid.match(/^(tests\/[^:]+\.py)/);
  return match ? match[1] : nodeid.split("::")[0] || nodeid;
}

/**
 * Extract model id from nodeid parametrize segment.
 * @param {string} nodeid
 */
export function parseModelFromNodeid(nodeid) {
  const bracket = nodeid.match(/\[([^\]]+)\]/);
  if (!bracket) return null;
  const inner = bracket[1];
  const slash = inner.indexOf("/");
  if (slash >= 0) return inner.slice(0, inner.indexOf("-", slash) > 0 ? inner.length : inner.length);
  const parts = inner.split("-");
  if (parts.length >= 2 && parts[0].includes("/")) {
    const vendor = parts[0];
    const rest = parts.slice(1).join("-");
    const lastDash = rest.lastIndexOf("-");
    if (lastDash > 0 && !rest.slice(lastDash + 1).includes("/")) {
      return `${vendor}/${rest.slice(0, lastDash)}`;
    }
    return `${vendor}/${rest}`;
  }
  return inner;
}

/**
 * @param {string} nodeid
 * @param {Record<string, unknown>} models
 */
export function resolveModel(nodeid, models) {
  const parsed = parseModelFromNodeid(nodeid);
  if (parsed && models[parsed]) return parsed;
  const bracket = nodeid.match(/\[([^\]]+)\]/);
  if (!bracket) return null;
  const inner = bracket[1];
  for (const modelId of Object.keys(models)) {
    if (inner.startsWith(modelId)) return modelId;
  }
  const dashIdx = inner.lastIndexOf("-");
  if (dashIdx > 0) {
    const candidate = inner.slice(0, dashIdx);
    if (models[candidate]) return candidate;
  }
  return parsed;
}

/**
 * @param {object} report Raw report JSON
 * @returns {ViewModel}
 */
export function parseReport(report) {
  const models = report.models || {};
  const modelIds = Object.keys(models);
  const tests = [];
  let order = 0;

  for (const modelId of modelIds) {
    const stats = models[modelId];
    const modelTests = stats.tests || [];
    for (const t of modelTests) {
      tests.push({
        ...t,
        model: modelId,
        testFile: parseTestFile(t.nodeid),
        entityKey: t.entity_id ?? "(none)",
        _order: order++,
      });
    }
  }

  const modelRows = modelIds.map((id) => {
    const s = models[id];
    const total = s.tests_total || 0;
    const passed = s.tests_passed || 0;
    const failed = s.tests_failed || 0;
    const scored = passed + failed;
    return {
      id,
      testsTotal: total,
      testsPassed: passed,
      testsFailed: failed,
      testsSkipped: s.tests_skipped || 0,
      passRate: scored ? passed / scored : 0,
      latencyAvg: s.latency_ms?.avg ?? 0,
      latencyP50: s.latency_ms?.p50 ?? 0,
      latencyP95: s.latency_ms?.p95 ?? 0,
      costUsd: s.cost_usd,
      totalTokens: s.total_tokens,
      promptTokens: s.prompt_tokens,
      completionTokens: s.completion_tokens,
      avgTokensPerSecond: s.avg_tokens_per_second,
      hallucinationCount: s.hallucination_count ?? 0,
      clarificationCount: s.clarification_count ?? 0,
      incorrectEntityTargeting: s.incorrect_entity_targeting ?? 0,
      pricing: s.pricing || {},
      totalTestTimeSeconds: s.total_test_time_seconds,
    };
  });

  modelRows.sort((a, b) => {
    if (b.passRate !== a.passRate) return b.passRate - a.passRate;
    const costA = a.costUsd ?? Infinity;
    const costB = b.costUsd ?? Infinity;
    return costA - costB;
  });

  const testFiles = [...new Set(tests.map((t) => t.testFile))].sort();
  const entities = [...new Set(tests.map((t) => t.entityKey))].sort();

  return {
    raw: report,
    runId: report.run_id,
    startedAt: report.started_at,
    finishedAt: report.finished_at,
    haVersion: report.ha_version,
    summary: report.summary || {},
    isLive: !report.finished_at,
    models: modelRows,
    tests,
    testFiles,
    entities,
    modelIds,
  };
}

/**
 * @param {ViewModel} a
 * @param {ViewModel} b
 */
export function buildModelCompare(a, b) {
  const mapA = Object.fromEntries(a.models.map((m) => [m.id, m]));
  const mapB = Object.fromEntries(b.models.map((m) => [m.id, m]));
  const allIds = [...new Set([...Object.keys(mapA), ...Object.keys(mapB)])].sort();

  return allIds.map((id) => {
    const ma = mapA[id];
    const mb = mapB[id];
    return {
      id,
      inA: !!ma,
      inB: !!mb,
      passRateA: ma?.passRate ?? null,
      passRateB: mb?.passRate ?? null,
      passRateDelta:
        ma && mb ? (mb.passRate - ma.passRate) * 100 : null,
      costA: ma?.costUsd ?? null,
      costB: mb?.costUsd ?? null,
      costDelta: ma && mb && ma.costUsd != null && mb.costUsd != null
        ? mb.costUsd - ma.costUsd
        : null,
      latencyA: ma?.latencyAvg ?? null,
      latencyB: mb?.latencyAvg ?? null,
      latencyDelta:
        ma && mb ? mb.latencyAvg - ma.latencyAvg : null,
    };
  });
}
