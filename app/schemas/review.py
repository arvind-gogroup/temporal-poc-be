"""Pydantic schemas for the reviews API.

Organised into three groups:
- **Request bodies** — validated on inbound requests.
- **Response payloads** — serialised as the ``payload`` field of ``ApiResponse``.
- **Sub-schemas** — building blocks used inside response payloads.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.enums import ReviewStatus


class StartReviewRequest(BaseModel):
    """Request body for ``POST /api/reviews/start``.

    Attributes:
        employee_id: Identifier of the employee to be reviewed. Min length 1.
        lead_id: Identifier of the lead who will approve the review. Min length 1.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": "emp-001",
                "lead_id": "lead-007",
            }
        }
    )

    employee_id: str = Field(..., min_length=1)
    lead_id: str = Field(..., min_length=1)


class FormSubmittedRequest(BaseModel):
    """Request body for ``POST /api/reviews/{workflow_id}/signal/form_submitted``.

    Attributes:
        form_data: Free-form JSON object representing the employee's self-review.
            Any valid JSON object is accepted; the shape is not enforced server-side.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "form_data": {
                    "self_assessment": "I achieved all my Q2 goals.",
                    "goals_met": True,
                    "comments": "Looking to grow into a senior role.",
                }
            }
        }
    )

    form_data: dict = Field(..., description="Employee self-review form payload")


class LeadApprovedRequest(BaseModel):
    """Request body for ``POST /api/reviews/{workflow_id}/signal/lead_approved``.

    Attributes:
        rating: The lead's assessment rating string.
            Suggested values: ``"exceeds_expectations"``, ``"meets_expectations"``,
            ``"needs_improvement"``.
    """

    model_config = ConfigDict(
        json_schema_extra={"example": {"rating": "exceeds_expectations"}}
    )

    rating: str = Field(..., min_length=1)


class ReviewSummary(BaseModel):
    """Lightweight review record returned by the list endpoint.

    Populated from the ORM model via ``from_attributes=True``.

    Attributes:
        workflow_id: Unique Temporal workflow identifier.
        employee_id: Employee under review.
        lead_id: Lead responsible for approval.
        status: Current lifecycle state.
        created_at: When the workflow was started.
        updated_at: When the workflow was last updated.
    """

    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    employee_id: str
    lead_id: str
    status: ReviewStatus
    created_at: datetime
    updated_at: datetime


class ReviewDetail(BaseModel):
    """Full review record returned by the single-item get endpoint.

    Includes all fields from :class:`ReviewSummary` plus the form payload,
    AI summary, and lead rating.

    Attributes:
        id: UUID database primary key.
        workflow_id: Unique Temporal workflow identifier.
        employee_id: Employee under review.
        lead_id: Lead responsible for approval.
        status: Current lifecycle state.
        form_data: Employee's self-review submission. ``None`` before submission.
        ai_summary: LLM-generated performance summary. ``None`` before generation.
        rating: Lead's rating. ``None`` before approval.
        created_at: When the workflow was started.
        updated_at: When the workflow was last updated.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: str
    employee_id: str
    lead_id: str
    status: ReviewStatus
    form_data: dict | None
    ai_summary: str | None
    rating: str | None
    created_at: datetime
    updated_at: datetime


class StartReviewResponse(BaseModel):
    """Response payload returned by ``POST /api/reviews/start`` (HTTP 201).

    Attributes:
        workflow_id: Generated Temporal workflow ID for subsequent API calls.
        employee_id: Employee identifier echoed from the request.
        lead_id: Lead identifier echoed from the request.
        status: Always ``INITIATED`` at creation time.
        created_at: Timestamp of row creation.
    """

    workflow_id: str
    employee_id: str
    lead_id: str
    status: ReviewStatus
    created_at: datetime


class SignalResponse(BaseModel):
    """Response payload returned after successfully sending a Temporal signal.

    Attributes:
        message: Confirmation string, always ``"Signal sent"``.
        workflow_id: The workflow ID the signal was delivered to.
    """

    message: str
    workflow_id: str


class StageEvent(BaseModel):
    """A single Temporal event within a workflow stage.

    Attributes:
        event_id: Sequential event identifier within the workflow execution.
        event_type: Raw Temporal event type string (e.g. ``"EVENT_TYPE_ACTIVITY_TASK_STARTED"``).
        label: Human-readable description of the event for display purposes.
        timestamp: ISO 8601 timestamp of when the event occurred.
    """

    event_id: int
    event_type: str
    label: str
    timestamp: str


class WorkflowStage(BaseModel):
    """A logical stage grouping related Temporal events.

    Maps to the six steps shown in the pipeline progress UI:
    ``INITIATED → WAITING_FORM → FORM_SUBMITTED → WAITING_APPROVAL → APPROVED → COMPLETED``.

    Attributes:
        name: Stage identifier matching ``ReviewStatus`` values (e.g. ``"WAITING_FORM"``).
        label: Short display label (e.g. ``"Waiting Form"``).
        description: Subtitle shown beneath the stage in the UI (e.g. ``"Self-review pending"``).
        status: One of ``"completed"``, ``"active"``, or ``"pending"``.
        started_at: ISO 8601 timestamp of the first event in this stage. ``None`` if not yet reached.
        completed_at: ISO 8601 timestamp of the last event in this stage. ``None`` if still active.
        event_count: Number of raw Temporal events grouped into this stage.
        key_event: Single-line summary of the most meaningful event in this stage.
        events: Ordered list of individual Temporal events within this stage.
    """

    name: str
    label: str
    description: str
    status: str
    started_at: str | None
    completed_at: str | None
    event_count: int
    key_event: str | None
    events: list[StageEvent]


class WorkflowHistoryResponse(BaseModel):
    """Response payload for ``GET /api/reviews/{workflow_id}/history``.

    Attributes:
        workflow_id: The queried workflow's identifier.
        total_events: Total number of raw Temporal events across all stages.
        stages: Ordered list of logical workflow stages, each containing grouped events.
    """

    workflow_id: str
    total_events: int
    stages: list[WorkflowStage]
