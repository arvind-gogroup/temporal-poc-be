# Frontend Integration — Employee Review Workflow API

You are building a frontend application that integrates with the Employee Review Workflow backend API.
Use the specifications below to implement all API calls, types, and UI flows.

---

## Base URL

```
http://localhost:8000
```

Interactive API docs are available at `http://localhost:8000/docs` (Swagger UI).

---

## Universal Response Envelope

**Every** response from this API — success or error — is wrapped in this envelope.
Never access data directly; always unwrap via `payload`.

```ts
interface ApiResponse<T> {
  payload: T | null;
  status: {
    success: boolean;
    code: number;       // mirrors the HTTP status code
    message?: string;   // present on errors, absent on success
  };
  meta?: {              // only present on paginated list endpoints
    page: number;
    per_page: number;
    total_pages: number;
    total_records: number;
    filters?: Record<string, unknown>;
  } | null;
}
```

---

## Enums

```ts
type ReviewStatus =
  | "INITIATED"          // workflow just created
  | "WAITING_FORM"       // waiting for employee to submit self-review
  | "FORM_SUBMITTED"     // form received, AI summary being generated
  | "WAITING_APPROVAL"   // AI summary ready, waiting for lead to approve
  | "APPROVED"           // lead approved, workflow finalising
  | "COMPLETED"          // workflow finished successfully
  | "FAILED";            // workflow failed
```

---

## Endpoints & Schemas

### 1. Start a Review Workflow

```
POST /api/reviews/start
```

Starts a new Temporal-backed employee review workflow.

**Request body:**
```ts
{
  employee_id: string;   // min length 1, e.g. "emp-001"
  lead_id: string;       // min length 1, e.g. "lead-007"
}
```

**Response — HTTP 201 — `ApiResponse<StartReviewResponse>`**
```ts
interface StartReviewResponse {
  workflow_id: string;    // unique ID used in all subsequent calls
  employee_id: string;
  lead_id: string;
  status: ReviewStatus;   // always "INITIATED" on creation
  created_at: string;     // ISO 8601
}
```

**Example:**
```json
{
  "payload": {
    "workflow_id": "review-emp-001-1715789012",
    "employee_id": "emp-001",
    "lead_id": "lead-007",
    "status": "INITIATED",
    "created_at": "2026-05-15T10:30:00Z"
  },
  "status": { "success": true, "code": 201 },
  "meta": null
}
```

---

### 2. List Review Workflows

```
GET /api/reviews
```

Returns a paginated list of all workflows.

**Query parameters:**
| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `status` | `ReviewStatus` | — | Optional filter |
| `page` | `number` | `1` | Min: 1 |
| `per_page` | `number` | `20` | Range: 1–100 |

**Response — HTTP 200 — `ApiResponse<ReviewSummary[]>`**
```ts
interface ReviewSummary {
  workflow_id: string;
  employee_id: string;
  lead_id: string;
  status: ReviewStatus;
  created_at: string;   // ISO 8601
  updated_at: string;   // ISO 8601
}
```

**Example:**
```json
{
  "payload": [
    {
      "workflow_id": "review-emp-001-1715789012",
      "employee_id": "emp-001",
      "lead_id": "lead-007",
      "status": "WAITING_FORM",
      "created_at": "2026-05-15T10:30:00Z",
      "updated_at": "2026-05-15T10:30:05Z"
    }
  ],
  "status": { "success": true, "code": 200 },
  "meta": {
    "page": 1,
    "per_page": 20,
    "total_pages": 1,
    "total_records": 1,
    "filters": { "status": "WAITING_FORM" }
  }
}
```

---

### 3. Get Single Review

```
GET /api/reviews/{workflow_id}
```

Returns full detail including form data and AI summary.

**Path param:** `workflow_id` — the `workflow_id` returned from start.

**Response — HTTP 200 — `ApiResponse<ReviewDetail>`**
```ts
interface ReviewDetail {
  id: string;                                    // UUID (database row ID)
  workflow_id: string;
  employee_id: string;
  lead_id: string;
  status: ReviewStatus;
  form_data: Record<string, unknown> | null;     // employee self-review payload
  ai_summary: string | null;                     // LLM-generated summary text
  rating: string | null;                         // lead's rating (set after approval)
  created_at: string;                            // ISO 8601
  updated_at: string;                            // ISO 8601
}
```

**Example:**
```json
{
  "payload": {
    "id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "workflow_id": "review-emp-001-1715789012",
    "employee_id": "emp-001",
    "lead_id": "lead-007",
    "status": "WAITING_APPROVAL",
    "form_data": {
      "self_assessment": "I achieved all my Q2 goals.",
      "goals_met": true,
      "comments": "Looking to grow into a senior role."
    },
    "ai_summary": "Employee demonstrates strong performance with consistent goal achievement...",
    "rating": null,
    "created_at": "2026-05-15T10:30:00Z",
    "updated_at": "2026-05-15T10:31:20Z"
  },
  "status": { "success": true, "code": 200 },
  "meta": null
}
```

---

### 4. Submit Employee Self-Review Form

```
POST /api/reviews/{workflow_id}/signal/form_submitted
```

Sends the employee's self-review form to the running workflow.
**Only valid when `status === "WAITING_FORM"`** — returns 409 otherwise.

**Request body:**
```ts
{
  form_data: Record<string, unknown>;  // any JSON object representing the form
}
```

**Example request body:**
```json
{
  "form_data": {
    "self_assessment": "I achieved all my Q2 goals.",
    "goals_met": true,
    "comments": "Looking to grow into a senior role."
  }
}
```

**Response — HTTP 200 — `ApiResponse<SignalResponse>`**
```ts
interface SignalResponse {
  message: string;      // "Signal sent"
  workflow_id: string;
}
```

---

### 5. Lead Approval

```
POST /api/reviews/{workflow_id}/signal/lead_approved
```

Sends the lead's approval and rating to the workflow.
**Only valid when `status === "WAITING_APPROVAL"`** — returns 409 otherwise.

**Request body:**
```ts
{
  rating: string;   // e.g. "exceeds_expectations" | "meets_expectations" | "needs_improvement"
}
```

**Response — HTTP 200 — `ApiResponse<SignalResponse>`**
```ts
interface SignalResponse {
  message: string;      // "Signal sent"
  workflow_id: string;
}
```

---

### 6. Get Workflow History

```
GET /api/reviews/{workflow_id}/history
```

Returns the Temporal execution history grouped into the six logical workflow stages.
Use for the pipeline timeline UI, audit trails, and debug views.

**Response — HTTP 200 — `ApiResponse<WorkflowHistoryResponse>`**
```ts
interface StageEvent {
  event_id: number;
  event_type: string;   // raw Temporal type, e.g. "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
  label: string;        // human-readable, e.g. "Send notification"
  timestamp: string;    // ISO 8601
}

interface WorkflowStage {
  name: string;             // matches ReviewStatus values, e.g. "WAITING_FORM"
  label: string;            // short display label, e.g. "Waiting Form"
  description: string;      // subtitle for the UI, e.g. "Notification sent, awaiting self-review"
  status: "completed" | "active" | "pending";
  started_at: string | null;    // ISO 8601 — null if stage not yet reached
  completed_at: string | null;  // ISO 8601 — null if stage still active or pending
  event_count: number;
  key_event: string | null;     // one-line summary of the most meaningful event
  events: StageEvent[];
}

interface WorkflowHistoryResponse {
  workflow_id: string;
  total_events: number;
  stages: WorkflowStage[];  // always 6 stages in execution order
}
```

**Stage `status` rules:**

| `status` | Meaning |
|---|---|
| `"completed"` | Stage fully done — both `started_at` and `completed_at` are set |
| `"active"` | Workflow is currently in this stage — `completed_at` is `null` |
| `"pending"` | Not yet reached — `started_at` and `completed_at` are both `null` |

**Example response:**
```json
{
  "payload": {
    "workflow_id": "review-EMP1-001-3c6ac9cf",
    "total_events": 53,
    "stages": [
      {
        "name": "INITIATED",
        "label": "Initiated",
        "description": "Workflow created",
        "status": "completed",
        "started_at": "2026-05-19T06:46:05.771806",
        "completed_at": "2026-05-19T06:46:05.796694",
        "event_count": 4,
        "key_event": "Workflow execution started",
        "events": [
          {
            "event_id": 1,
            "event_type": "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED",
            "label": "Workflow execution started",
            "timestamp": "2026-05-19T06:46:05.771806"
          }
        ]
      },
      {
        "name": "WAITING_FORM",
        "label": "Waiting Form",
        "description": "Notification sent, awaiting self-review",
        "status": "completed",
        "started_at": "2026-05-19T06:46:05.796694",
        "completed_at": "2026-05-19T06:46:35.863995",
        "event_count": 11,
        "key_event": "Notification sent to employee and lead",
        "events": [
          {
            "event_id": 5,
            "event_type": "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED",
            "label": "Send notification",
            "timestamp": "2026-05-19T06:46:05.796694"
          }
        ]
      },
      {
        "name": "FORM_SUBMITTED",
        "label": "Form Submitted",
        "description": "Self-review received, AI summary generated",
        "status": "completed",
        "started_at": "2026-05-19T06:57:14.544289",
        "completed_at": "2026-05-19T06:57:14.579395",
        "event_count": 10,
        "key_event": "Self-review form received and AI summary generated",
        "events": []
      },
      {
        "name": "WAITING_APPROVAL",
        "label": "Waiting Approval",
        "description": "AI summary ready, awaiting lead approval",
        "status": "completed",
        "started_at": "2026-05-19T06:57:14.579395",
        "completed_at": "2026-05-19T06:58:35.242713",
        "event_count": 11,
        "key_event": "Status set to waiting approval, lead review timer started",
        "events": []
      },
      {
        "name": "APPROVED",
        "label": "Approved",
        "description": "Lead approved, completion notification sent",
        "status": "completed",
        "started_at": "2026-05-19T06:58:35.242713",
        "completed_at": "2026-05-19T06:58:35.279949",
        "event_count": 10,
        "key_event": "Lead approved the review and rating recorded",
        "events": []
      },
      {
        "name": "COMPLETED",
        "label": "Completed",
        "description": "Review process complete",
        "status": "completed",
        "started_at": "2026-05-19T06:58:35.279949",
        "completed_at": "2026-05-19T06:58:35.310000",
        "event_count": 7,
        "key_event": "All activities complete, workflow closed",
        "events": []
      }
    ]
  },
  "status": { "success": true, "code": 200 },
  "meta": null
}
```

---

## Error Responses

All errors follow the same envelope with `payload: null`.

| HTTP Code | When |
|-----------|------|
| `400` | Validation error on request body |
| `404` | `workflow_id` not found |
| `409` | Conflict — signal sent to a workflow in the wrong state |
| `500` | Unexpected server error |

**Example 404:**
```json
{
  "payload": null,
  "status": {
    "success": false,
    "code": 404,
    "message": "Workflow review-emp-001-xyz not found"
  },
  "meta": null
}
```

**Example 409 (wrong state):**
```json
{
  "payload": null,
  "status": {
    "success": false,
    "code": 409,
    "message": "Workflow is not in WAITING_FORM state"
  },
  "meta": null
}
```

---

## Happy-Path Flow

Implement the UI to guide users through these steps in order:

```
Step 1 — HR / Admin starts a review:
  POST /api/reviews/start
  → workflow created, status becomes "WAITING_FORM"

Step 2 — Poll or display status:
  GET /api/reviews/{workflow_id}
  → wait until status === "WAITING_FORM" before showing the form to the employee

Step 3 — Employee submits self-review form:
  POST /api/reviews/{workflow_id}/signal/form_submitted
  → status transitions: FORM_SUBMITTED → (AI processing) → WAITING_APPROVAL

Step 4 — Poll for AI summary:
  GET /api/reviews/{workflow_id}
  → wait until status === "WAITING_APPROVAL"
  → ai_summary is now populated; display it to the lead

Step 5 — Lead approves with a rating:
  POST /api/reviews/{workflow_id}/signal/lead_approved
  → status transitions: APPROVED → COMPLETED

Step 6 — Final state:
  GET /api/reviews/{workflow_id}
  → status === "COMPLETED", rating is populated
```

---

## Health Check

```
GET /health
→ { "status": "ok" }
```

Use this to check if the backend is reachable before making other calls.
