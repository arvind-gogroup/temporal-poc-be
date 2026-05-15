import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.constants.enums import ReviewStatus


class StartReviewRequest(BaseModel):
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
    model_config = ConfigDict(
        json_schema_extra={"example": {"rating": "exceeds_expectations"}}
    )

    rating: str = Field(..., min_length=1)


class ReviewSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    workflow_id: str
    employee_id: str
    lead_id: str
    status: ReviewStatus
    created_at: datetime
    updated_at: datetime


class ReviewDetail(BaseModel):
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
    workflow_id: str
    employee_id: str
    lead_id: str
    status: ReviewStatus
    created_at: datetime


class SignalResponse(BaseModel):
    message: str
    workflow_id: str


class HistoryEvent(BaseModel):
    event_id: int
    event_type: str
    timestamp: str
    attributes: dict


class WorkflowHistoryResponse(BaseModel):
    workflow_id: str
    events: list[HistoryEvent]
