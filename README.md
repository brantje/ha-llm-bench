# Home Assistant + OpenRouter Conversational Test Harness

Automated conversational tests for Home Assistant using OpenRouter as the LLM backend.

## Quick Start

```bash
cp .env.example .env
# Set OPENROUTER_API_KEY (and optionally OPENROUTER_MANAGEMENT_KEY)

python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
docker compose up -d --wait
.venv/bin/python bootstrap.py
.venv/bin/pytest
```

Reports are written to `reports/results.json` (updated after each test), `reports/report.json`, and `reports/report.md`. Each finalized run is also archived under `reports/history/<run_id>/` with a manifest at `reports/history/index.json`.

### Results viewer (HTML)

Interactive benchmark dashboard in `docs/`:

```bash
# From repo root (required so fetch can load reports/)
python3 -m http.server 8080
# Open http://localhost:8080/docs/
```

The viewer loads:

- **Current report** — `reports/report.json` (final run)
- **Live results** — `reports/results.json` (updated after each test; optional 30s auto-refresh)
- **History** — past runs from `reports/history/index.json`

Features: model leaderboard, Chart.js charts, full test table with filters (outcome, model, test file, entity, flags, search, latency/cost), grouping, pricing tables, copy report JSON, and two-run model comparison. Filter state is stored in the URL hash for sharing.

### Run history (app)

Each completed pytest run is archived under `reports/history/<run_id>/report.json` with a manifest at `reports/history/index.json` (last 20 runs). The test plan uses medians from all archived runs (plus the current report) for cost and wall-time estimates.

```bash
# List archived runs
PYTHONPATH=src .venv/bin/python -m ha_test.history list

# Print one archived report
PYTHONPATH=src .venv/bin/python -m ha_test.history show '2026-05-20T07:38:23.015278+00:00'

# Or via bootstrap
PYTHONPATH=src .venv/bin/python bootstrap.py --history
```

## Entity Catalog (MVP)

| Entity | Example Command |
|---|---|
| `light.lamp_x` | turn lamp x off |
| `switch.tv_switch` | turn the tv switch on |
| `climate.living_room` | set living room temperature to 22 degrees |
| `timer.pizza` | start the pizza timer for 5 minutes |

## Model Filters

Configure via environment variables:

- `OPENROUTER_FREE_ONLY` — default `true`
- `OPENROUTER_MIN_CONTEXT` — default `8192`
- `OPENROUTER_ALLOWLIST` / `OPENROUTER_DENYLIST` — comma-separated model IDs
- `OPENROUTER_MAX_MODELS` — cap models per run (useful in CI)
- `OPENROUTER_MODEL` — comma-separated model IDs to test (leave empty to auto-discover free models)
- `OPENROUTER_RATE_LIMIT_MAX_RETRIES` — max retries when rate limited (default `8`)
- `OPENROUTER_RATE_LIMIT_BUFFER_SECONDS` — extra wait after header reset time (default `1`)
- `OPENROUTER_RATE_LIMIT_FALLBACK_SECONDS` — fallback wait if headers missing (default `30`)
- `OPENROUTER_USAGE_SETTLE_SECONDS` — wait after each test and while polling OpenRouter usage (default `12`)

`bootstrap.py` prints a test plan before configuring Home Assistant: models to run, test matrix size, estimated cost (from past report token medians or a conservative default), and estimated wall time.

## Reports

`reports/report.json` includes per-model:

- pass/fail counts
- latency (avg, p50, p95)
- **cost_usd** (via OpenRouter Activity API; requires `OPENROUTER_MANAGEMENT_KEY`)
- **avg_tokens_per_second** (completion tokens / total test latency)
- Per-test **tokens_per_second** in `models.<model>.tests[]`

## CI

[![Conversational Tests](https://github.com/OWNER/REPO/actions/workflows/tests.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/tests.yml)

GitHub Actions workflow: [`.github/workflows/tests.yml`](.github/workflows/tests.yml)

Runs on push/PR to `main`/`master` and via **Actions → Conversational Tests → Run workflow**.

### Configuration

CI does **not** use `.env`. All settings come from GitHub Actions environment variables.

**Secrets** (Settings → Secrets and variables → Actions → Secrets):

- `OPENROUTER_API_KEY` (required)
- `OPENROUTER_MANAGEMENT_KEY` (optional; recommended for cost/token stats)

**Variables** (Settings → Secrets and variables → Actions → Variables; all optional — workflow defaults apply if unset):

| Variable | Default in workflow |
|----------|---------------------|
| `OPENROUTER_FREE_ONLY` | `true` |
| `OPENROUTER_MAX_MODELS` | `2` |
| `OPENROUTER_MIN_CONTEXT` | `8192` |
| `OPENROUTER_MODEL` | (empty — auto-discover) |
| `OPENROUTER_ALLOWLIST` / `OPENROUTER_DENYLIST` | (empty) |
| `OPENROUTER_RATE_LIMIT_*` / `OPENROUTER_USAGE_SETTLE_SECONDS` | see `.env.example` |
| `HA_URL` | `http://localhost:8123` |
| `TZ` | `UTC` |

Bootstrap writes `HA_TOKEN` and `HA_CONVERSATION_AGENT_ID` to `$GITHUB_ENV` for the pytest step (not to `.env`).

**Troubleshooting: only one model (e.g. `openrouter/owl-alpha`) runs**

1. **`OPENROUTER_MODEL` overrides everything** — if this variable is set (even to a single model ID), allowlist and free-only filters are ignored. Leave it empty to use `OPENROUTER_ALLOWLIST` + discovery.
2. **`OPENROUTER_FREE_ONLY` must be `false` without quotes** — the workflow defaults to `true` when the variable is unset. With `true`, only free models in your allowlist are tested (often just `openrouter/owl-alpha`). Values like `'false'` are treated as “not false” and keep free-only on.
3. Check the **Print OpenRouter config** step in the Actions log — it shows the resolved model count before tests run.

### GitHub Pages (benchmark dashboard)

After each push to `main` or `master`, the workflow publishes the latest reports to GitHub Pages (even when tests fail).

1. **One-time setup**: **Settings → Pages → Build and deployment → Source** → **GitHub Actions**
2. **URL**: `https://<owner>.github.io/<repo>/` (project site)
3. **Contents**: `docs/` viewer plus `reports/` from the CI run (`report.json`, `results.json`, `history/`)

History on Pages is accumulated across deploys (Actions cache + merge from the previous live site). If a run in the dropdown returns 404, hard-refresh the page (stale `index.json` cache) or wait for the next main-branch deploy.

Pull requests run tests and upload a `benchmark-reports` artifact but do not deploy Pages.

Replace `OWNER/REPO` in the badge URL above with your GitHub org/user and repository name.

## Extending

Add helpers and template entities under `docker/packages/`, then add pytest cases that:

1. Reset helper state
2. Send a natural language command via `conversation(...)`
3. Assert entity state via `wait_and_assert(...)`
