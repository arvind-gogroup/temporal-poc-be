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


class HistoryEvent(BaseModel):
    """A single event from the Temporal workflow execution history.

    Attributes:
        event_id: Sequential event identifier within the workflow execution.
        event_type: Temporal event type name (e.g. ``"WorkflowExecutionStarted"``).
        timestamp: ISO 8601 timestamp of when the event occurred.
        attributes: Raw event attributes dict (currently empty; extend as needed).
    """

    event_id: int
    event_type: str
    timestamp: str
    attributes: dict


class WorkflowHistoryResponse(BaseModel):
    """Response payload for ``GET /api/reviews/{workflow_id}/history``.

    Attributes:
        workflow_id: The queried workflow's identifier.
        events: Ordered list of Temporal execution events for audit/debug use.
    """

    workflow_id: str
    events: list[HistoryEvent]
