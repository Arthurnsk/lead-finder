# Lead Finder

Multi-tenant SaaS that finds **fresh demand**: public posts from people who need a
service right now. It collects posts from several sources, filters out noise, and asks
an LLM to score each candidate against the business's ideal customer profile (ICP).

Русская версия: [README.ru.md](README.ru.md)

## How it works

```
web (React, nginx :3000) ──/api──▶ api (FastAPI :8000) ──▶ PostgreSQL
                                        ▲  SSE live log            ▲
                                   worker (job queue in Postgres, cron) ─┘
                                     ├─ sources: VK API · SearXNG · RSS · DuckDuckGo · Telegram
                                     └─ LLM: any OpenAI-compatible API (local model, Groq, …)
```

1. **Collect.** Search queries, RSS feeds, watched pages, public Telegram channels and
   government tenders, configured per niche in a YAML file.
2. **Filter.** Stop lists, freshness limits, regex demand signals, blocked hosts.
3. **Score.** An LLM rates each candidate against the niche's ICP using few-shot examples.
4. **Deliver.** Leads land in an inbox with a status pipeline and Telegram/webhook alerts.

## Features

- Multi-tenancy: every row is isolated by `organization_id`; roles owner / admin / manager / viewer.
- Security: argon2 password hashes, JWT in httpOnly cookies, CSRF double-submit,
  login rate limiting, integration secrets encrypted with Fernet.
- Background worker with a Postgres-based queue and live progress over Server-Sent Events.
- Niche = YAML config (offer, ICP, queries, sources, examples). A demo niche is in
  [`niches/land_agency_demo.yaml`](niches/land_agency_demo.yaml).
- Model evaluation: compare LLMs on labeled cases (`python -m app.eval`).
- Ops: Docker Compose, Alembic migrations, `deploy/backup.sh` with 14-day rotation.

## Stack

Python 3.12 · FastAPI · SQLAlchemy · Alembic · PostgreSQL · React + TypeScript · Nginx ·
Docker Compose · SearXNG · pytest

## Quick start

```bash
cp .env.example .env
docker compose run --rm api python manage.py gen-key     # prints SECRET_KEY and FERNET_KEY
docker compose up -d --build
docker compose exec api python manage.py create-superadmin --email you@example.com
docker compose exec api python manage.py create-org --name "Demo Land Agency" --slug demo --owner you@example.com
docker compose exec api python manage.py import-niche --org demo --file /seed/niches/land_agency_demo.yaml
```

UI: http://localhost:3000 · API docs: http://localhost:8000/api/docs (when `ENV=dev`).

## Tests

```bash
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

Tests run on in-memory SQLite by default (set `TEST_DATABASE_URL` to use Postgres).

## Notes

Pet project built with an AI-assisted workflow (Cursor, Claude Code): I wrote the
specifications, made the architecture decisions, reviewed and tested the code, and
handled deployment.

License: MIT
