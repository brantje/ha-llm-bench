/** @type {Record<string, import('chart.js').Chart|undefined>} */
const charts = {};

const chartColors = {
  primary: "rgba(3, 169, 244, 0.75)",
  border: "#03a9f4",
};

/**
 * @param {string} canvasId
 * @param {string} label
 * @param {string[]} labels
 * @param {number[]} data
 * @param {string} [ySuffix]
 */
function upsertChart(canvasId, label, labels, data, ySuffix = "") {
  const canvas = /** @type {HTMLCanvasElement|null} */ (document.getElementById(canvasId));
  if (!canvas || typeof Chart === "undefined") return;

  if (charts[canvasId]) {
    charts[canvasId].destroy();
  }

  charts[canvasId] = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label,
          data,
          backgroundColor: chartColors.primary,
          borderColor: chartColors.border,
          borderWidth: 1,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              const v = ctx.parsed.y;
              return `${label}: ${formatVal(v)}${ySuffix}`;
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: "#9e9e9e", maxRotation: 45, minRotation: 0, font: { size: 10 } },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
        y: {
          ticks: { color: "#9e9e9e" },
          grid: { color: "rgba(255,255,255,0.06)" },
        },
      },
    },
  });
}

/**
 * @param {number} v
 */
function formatVal(v) {
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 0.01) return v.toFixed(6);
  if (Math.abs(v) < 1) return v.toFixed(4);
  return v.toFixed(2);
}

/**
 * @param {import('./store.js').ViewModel['models']} models
 */
export function updateCharts(models) {
  const shortLabels = models.map((m) => {
    const parts = m.id.split("/");
    return parts.length > 1 ? parts[1] : m.id;
  });

  upsertChart(
    "chart-pass-rate",
    "Pass rate %",
    shortLabels,
    models.map((m) => m.passRate * 100),
    "%",
  );
  upsertChart(
    "chart-latency",
    "Avg latency (ms)",
    shortLabels,
    models.map((m) => m.latencyAvg),
    " ms",
  );
  upsertChart(
    "chart-cost",
    "Cost USD",
    shortLabels,
    models.map((m) => m.costUsd ?? 0),
  );
}

export function destroyCharts() {
  for (const id of Object.keys(charts)) {
    charts[id]?.destroy();
    delete charts[id];
  }
}
