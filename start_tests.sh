docker compose up -d --wait
set -a && source .env && set +a
.venv/bin/python bootstrap.py
.venv/bin/pytest tests/ -v