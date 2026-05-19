# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Running the Stack

All services run via Docker Compose. The single `Dockerfile.api` image is shared by both the `api` and `worker` containers.

```bash
# Start everything (postgres → temporal → api + worker)
docker compose up -d

# Start only infrastructure (useful during local dev)
docker compose up -d postgres temporal temporal-ui

# Run the API locally (after infra is up)
uvicorn app.main:app --reload --port 8000

# Run the worker locally
python -m app.temporal.worker

# Apply migrations
alembic upgrade head

# Create a new migration
alembic revision --autogenerate -m "describe_change"

# Restart a single service (e.g. after a code change in Docker)
docker compose restart api
docker compose restart worker
```

**Service URLs:**
- API: `http://localhost:8000` — Swagger UI at `/docs`, ReDoc at `/redoc`
- Temporal UI: `http://localhost:8080`
- Temporal gRPC: `localhost:7233`
- PostgreSQL: `localhost:5432`

**Environment:** Copy `.env.example` → `.env`. The `DATABASE_URL` is auto-constructed from individual `POSTGRES_*` vars in `app/config.py` unless you override it directly.

---

## Architecture

### Request → Response Flow

```
HTTP Request
  → FastAPI route (app/api/routes/reviews.py)
  → WorkflowService (app/services/workflow_service.py)
      ├── DB reads/writes via SQLAlchemy AsyncSession
      └── Temporal signals/queries via temporalio.client.Client
  → ApiResponse[T] envelope (app/schemas/response.py)
```

`WorkflowService` receives both `db: AsyncSession` (from FastAPI dependency `get_db`) and `temporal_client: Client` (from `request.app.state.temporal_client`, set during lifespan startup in `app/main.py`).

### Workflow Execution Flow

```
WorkflowService.start_review()
  → inserts DB row (status=INITIATED)
  → starts ReviewWorkflow via Temporal client

ReviewWorkflow.run()  [executes in worker container]
  1. send_notification activity   → DB: WAITING_FORM
  2. workflow.sleep(30s)
  3. wait_condition(form_data received via signal)
  4. generate_ai_summary activity → DB: FORM_SUBMITTED
  5. _set_waiting_approval activity → DB: WAITING_APPROVAL
  6. workflow.sleep(10s)
  7. wait_condition(rating received via signal)
  8. send_completion_notification activity → DB: APPROVED
  9. _mark_completed activity → DB: COMPLETED
```

Signals (`form_submitted`, `lead_approved`) are sent from `WorkflowService` to the running Temporal workflow via `handle.signal(...)`.

### Activity DB Access Pattern

Activities access the database directly via `AsyncSessionFactory` (not via FastAPI's `get_db`). This is intentional — activities run in the worker process which has no FastAPI context. Example:

```python
async with AsyncSessionFactory() as session:
    row = (await session.execute(stmt)).scalar_one_or_none()
    row.status = ReviewStatus.WAITING_FORM
    await session.commit()
```

### Status-Transition Activities in the Workflow File

The lightweight `_set_waiting_approval`, `_mark_completed`, and `_mark_failed` activity functions live in `app/temporal/workflows/review_workflow.py` (not in the `activities/` folder). This avoids circular imports while keeping DB status transitions retryable by Temporal. They are imported by the worker in `app/temporal/worker.py`.

### Temporal Import Sandbox

Activity imports inside the workflow file are wrapped in `workflow.unsafe.imports_passed_through()` to prevent Temporal's determinism sandbox from blocking them:

```python
with workflow.unsafe.imports_passed_through():
    from app.temporal.activities.ai_summary import generate_ai_summary
    ...
```

---

## Key Conventions

### Documentation Style

All modules, classes, and public functions are documented with **Google-style docstrings**:

```python
def my_function(arg: str) -> bool:
    """One-line summary.

    Optional longer description paragraph.

    Args:
        arg: Description of the parameter.

    Returns:
        Description of the return value.

    Raises:
        ValueError: When and why this is raised.
    """
```

Module-level docstrings describe the file's purpose, note important design decisions
(e.g. why activities are co-located with the workflow), and include usage examples where helpful.

### Response Envelope

Every endpoint returns `ApiResponse[T]` from `app/schemas/response.py`. Use the helpers:

```python
success_response(data, code=200)          # single item
paginated_response(rows, page, per_page, total_records, filters)  # list
error_response("message", code=404)       # error
```

### Error Handling

- `LookupError` → 404 (workflow not found)
- `ValueError` → 409 (signal sent to wrong workflow state)
- All other exceptions → 500 (caught by global handler in `app/main.py`)

These are raised by `WorkflowService` and mapped by exception handlers in `app/main.py`.

### Constants & Enums

- `app/constants/enums.py` — `ReviewStatus` enum
- `app/constants/temporal.py` — task queue name, signal names, workflow type
- `app/constants/__init__.py` — re-exports all of the above for single-import access

Always import from `app.constants` rather than from sub-modules directly.

### Alembic Migrations

Migrations are async-aware (`alembic/env.py` uses `asyncio.run()`). The `api` container runs `alembic upgrade head` automatically on startup before launching uvicorn.

---

## Frontend Integration Contract

`FRONTEND_INTEGRATION.md` is the source of truth for the API contract consumed by the frontend.

**Always update `FRONTEND_INTEGRATION.md` whenever you:**
- Add, remove, or rename an endpoint
- Change a request body or query parameter
- Change a response schema (field names, types, nesting, new/removed fields)
- Change an enum value in `app/constants/enums.py`
- Change error behaviour (new status codes, changed error messages)

Update the doc in the same commit as the code change — never leave them out of sync.

---

## Live AI Summary

`AI_SUMMARY_MOCK=true` (default) returns a template string. To wire up a real LLM, set `AI_SUMMARY_MOCK=false` and implement the call inside `app/temporal/activities/ai_summary.py` — the `NotImplementedError` placeholder is already there.

---

## Frontend Integration

See `FRONTEND_INTEGRATION.md` for the complete API contract (TypeScript types, request/response examples, happy-path flow). Feed this file to the frontend Claude Code session.
