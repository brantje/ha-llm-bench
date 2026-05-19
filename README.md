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

Reports are written to `reports/report.json` and `reports/report.md`.

## Entity Catalog (MVP)

| Entity | Example Command |
|---|---|
| `light.lamp_x` | turn lamp x off |
| `switch.fan_switch` | turn the fan switch on |
| `climate.living_room` | set living room temperature to 22 degrees |

## Model Filters

Configure via environment variables:

- `OPENROUTER_FREE_ONLY` — default `true`
- `OPENROUTER_MIN_CONTEXT` — default `8192`
- `OPENROUTER_ALLOWLIST` / `OPENROUTER_DENYLIST` — comma-separated model IDs
- `OPENROUTER_MAX_MODELS` — cap models per run (useful in CI)
- `OPENROUTER_MODEL` — run against a single model
- `OPENROUTER_RATE_LIMIT_MAX_RETRIES` — max retries when rate limited (default `8`)
- `OPENROUTER_RATE_LIMIT_BUFFER_SECONDS` — extra wait after header reset time (default `1`)
- `OPENROUTER_RATE_LIMIT_FALLBACK_SECONDS` — fallback wait if headers missing (default `30`)

## Reports

`reports/report.json` includes per-model:

- pass/fail counts
- latency (avg, p50, p95)
- **cost_usd** (via OpenRouter Activity API; requires `OPENROUTER_MANAGEMENT_KEY`)
- **avg_tokens_per_second** (completion tokens / total test latency)

## CI

GitHub Actions workflow: `.github/workflows/tests.yml`

Required secrets:

- `OPENROUTER_API_KEY`
- `OPENROUTER_MANAGEMENT_KEY` (optional but recommended for cost/token stats)

## Extending

Add helpers and template entities under `docker/packages/`, then add pytest cases that:

1. Reset helper state
2. Send a natural language command via `conversation(...)`
3. Assert entity state via `wait_and_assert(...)`
