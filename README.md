# Employee Review Workflow API

A Temporal.io-powered backend that orchestrates the full employee performance review lifecycle — from self-review submission through AI summary generation to lead approval — using durable, fault-tolerant workflows.

---

## Tech Stack

| Layer | Technology |
|---|---|
| API framework | FastAPI 0.115 + Uvicorn |
| Workflow engine | Temporal.io (Python SDK 1.7) |
| Database | PostgreSQL 16 + asyncpg |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic |
| Validation | Pydantic v2 |
| Infrastructure | Docker Compose |

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Compose                       │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────────────┐   │
│  │ postgres │   │ temporal │   │   temporal-ui    │   │
│  │  :5432   │   │  :7233   │   │     :8080        │   │
│  └────┬─────┘   └────┬─────┘   └──────────────────┘   │
│       │              │                                   │
│  ┌────▼──────────────▼──────────────────────────────┐  │
│  │                  api  :8000                       │  │
│  │   FastAPI + Alembic migrations on startup         │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌───────────────────────────────────────────────────┐  │
│  │                 worker                            │  │
│  │   Temporal worker — polls review-task-queue       │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

The `api` and `worker` containers share the same Docker image (`Dockerfile.api`) but run different commands. Alembic migrations run automatically inside the `api` container on every startup before Uvicorn is launched.

### Request → Response Flow

```
HTTP Request
  └─▶ FastAPI route  (app/api/routes/reviews.py)
        └─▶ WorkflowService  (app/services/workflow_service.py)
              ├─▶ PostgreSQL  via SQLAlchemy AsyncSession
              └─▶ Temporal    via temporalio.client.Client
                    └─▶ ApiResponse[T] envelope returned to client
```

### Workflow Execution Flow

```
POST /api/reviews/start
  └─▶ DB row created (status: INITIATED)
  └─▶ ReviewWorkflow started on Temporal

ReviewWorkflow.run()   [executes in worker container]
  1.  send_notification activity        → DB: WAITING_FORM
  2.  workflow.sleep(30s)               ← simulates days-long window
  3.  wait for form_submitted signal    ← blocks until employee submits
  4.  generate_ai_summary activity      → DB: FORM_SUBMITTED
  5.  _set_waiting_approval activity    → DB: WAITING_APPROVAL
  6.  workflow.sleep(10s)               ← simulates lead review period
  7.  wait for lead_approved signal     ← blocks until lead approves
  8.  send_completion_notification      → DB: APPROVED  (rating persisted)
  9.  _mark_completed activity          → DB: COMPLETED
```

If any step fails, `_mark_failed` sets the DB status to `FAILED` before re-raising.

### Review Lifecycle States

```
INITIATED → WAITING_FORM → FORM_SUBMITTED → WAITING_APPROVAL → APPROVED → COMPLETED
                                                                              ↑
                                                                           FAILED (reachable from any step)
```

---

## Project Structure

```
.
├── app/
│   ├── api/routes/
│   │   └── reviews.py          # 6 REST endpoints under /api/reviews
│   ├── constants/
│   │   ├── enums.py             # ReviewStatus enum
│   │   └── temporal.py          # Task queue name, signal names
│   ├── models/
│   │   └── review.py            # ReviewWorkflow ORM model
│   ├── schemas/
│   │   ├── response.py          # ApiResponse[T] envelope + helpers
│   │   └── review.py            # All request/response Pydantic schemas
│   ├── services/
│   │   └── workflow_service.py  # Business logic: DB + Temporal operations
│   ├── temporal/
│   │   ├── activities/
│   │   │   ├── ai_summary.py    # generate_ai_summary activity
│   │   │   └── notification.py  # send_notification, send_completion_notification
│   │   ├── workflows/
│   │   │   └── review_workflow.py  # ReviewWorkflow + status-transition activities
│   │   ├── client.py            # Shared Temporal client singleton
│   │   └── worker.py            # Worker process entrypoint
│   ├── config.py                # Pydantic settings (reads .env)
│   ├── database.py              # Async engine, session factory, get_db dep
│   └── main.py                  # FastAPI app factory, middleware, lifespan
├── alembic/
│   ├── versions/0001_initial.py # review_workflows table + updated_at trigger
│   └── env.py                   # Async-aware Alembic env
├── docker-compose.yml
├── Dockerfile.api               # Shared image for api + worker
├── requirements.txt
├── .env.example
├── CLAUDE.md                    # Guidance for Claude Code sessions
└── FRONTEND_INTEGRATION.md      # API contract for the Next.js frontend
```

---

## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running

### 1. Configure environment

```bash
cp .env.example .env
```

The defaults in `.env.example` work out of the box with Docker Compose. The only value you should change for local development is `POSTGRES_PASSWORD`.

### 2. Start all services

```bash
docker compose up -d
```

This starts five containers in dependency order: `postgres` → `temporal` → `temporal-ui`, `api`, `worker`. The `api` container runs `alembic upgrade head` automatically before starting Uvicorn.

### 3. Verify everything is running

```bash
docker compose ps
```

| Service | URL |
|---|---|
| REST API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| Temporal UI | http://localhost:8080 |

### 4. Try the health check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## API Overview

All responses use a universal envelope:

```json
{
  "payload": { ... },
  "status": { "success": true, "code": 200 },
  "meta": null
}
```

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/reviews/start` | Start a new review workflow |
| `GET` | `/api/reviews` | List workflows (paginated, filterable by status) |
| `GET` | `/api/reviews/{workflow_id}` | Get full detail of a single workflow |
| `POST` | `/api/reviews/{workflow_id}/signal/form_submitted` | Submit employee self-review form |
| `POST` | `/api/reviews/{workflow_id}/signal/lead_approved` | Submit lead approval + rating |
| `GET` | `/api/reviews/{workflow_id}/history` | Raw Temporal execution event history |

See [`FRONTEND_INTEGRATION.md`](./FRONTEND_INTEGRATION.md) for the full TypeScript types, request/response examples, and the happy-path integration guide.

---

## Local Development (without Docker)

Start only the infrastructure:

```bash
docker compose up -d postgres temporal temporal-ui
```

Then run the API and worker in separate terminals:

```bash
# Terminal 1 — API
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Terminal 2 — Worker
python -m app.temporal.worker
```

> **Note:** Update your `.env` to point at `localhost` instead of the Docker service names:
> ```
> POSTGRES_HOST=localhost
> TEMPORAL_HOST=localhost
> ```

---

## Common Commands

```bash
# View logs for a specific service
docker compose logs -f api
docker compose logs -f worker

# Restart a service after a code change
docker compose restart api
docker compose restart worker

# Create a new Alembic migration
alembic revision --autogenerate -m "describe_your_change"

# Apply migrations manually
alembic upgrade head

# Tear down everything (preserves the postgres volume)
docker compose down

# Tear down and wipe the database
docker compose down -v
```

---

## Configuration Reference

All settings are read from environment variables or a `.env` file. `DATABASE_URL` is built automatically from the `POSTGRES_*` vars if not set explicitly.

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_HOST` | `postgres` | PostgreSQL hostname |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `review_db` | Database name |
| `POSTGRES_USER` | `review_user` | Database user |
| `POSTGRES_PASSWORD` | `review_pass` | Database password |
| `TEMPORAL_HOST` | `temporal` | Temporal server hostname |
| `TEMPORAL_PORT` | `7233` | Temporal gRPC port |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | `review-task-queue` | Worker task queue name |
| `APP_ENV` | `development` | Set to `production` to disable `/docs` |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `AI_SUMMARY_MOCK` | `true` | Use mock AI summary (no LLM call) |
| `OPENAI_API_KEY` | — | Required only when `AI_SUMMARY_MOCK=false` |

---

## Enabling Live AI Summaries

By default, `AI_SUMMARY_MOCK=true` generates a template summary string. To wire up a real LLM:

1. Set `AI_SUMMARY_MOCK=false` in your `.env`.
2. Set `OPENAI_API_KEY=sk-...`.
3. Replace the `NotImplementedError` placeholder in `app/temporal/activities/ai_summary.py` with your LLM client call.

---

## Frontend Integration

The frontend team should use [`FRONTEND_INTEGRATION.md`](./FRONTEND_INTEGRATION.md) as the complete API contract. It includes:
- TypeScript interfaces for all request and response shapes
- JSON examples for every endpoint
- The happy-path flow from workflow start to completion
