"""Business logic layer bridging the FastAPI routes and the Temporal/DB backends.

``WorkflowService`` is instantiated per-request via the ``_get_service``
FastAPI dependency in ``app/api/routes/reviews.py``. It receives an injected
``AsyncSession`` (from ``get_db``) and the ``temporalio.client.Client``
stored on ``app.state.temporal_client``.

Error contract:
    - Raises ``LookupError`` when a ``workflow_id`` is not found → HTTP 404.
    - Raises ``ValueError`` when a signal is sent to a workflow in the wrong
      state → HTTP 409.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import temporalio.api.enums.v1
from temporalio.client import Client, WorkflowFailureError

from app.constants.enums import ReviewStatus
from app.constants.temporal import SIGNAL_FORM_SUBMITTED, SIGNAL_LEAD_APPROVED, TASK_QUEUE
from app.models.review import ReviewWorkflow
from app.schemas.review import (
    ReviewDetail,
    ReviewSummary,
    StageEvent,
    StartReviewResponse,
    WorkflowHistoryResponse,
    WorkflowStage,
)
from app.temporal.workflows.review_workflow import ReviewWorkflowInput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# History-grouping helpers (module-level so they are easy to unit-test)
# ---------------------------------------------------------------------------

_EVENT_LABELS: dict[str, str] = {
    "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED":   "Workflow execution started",
    "EVENT_TYPE_WORKFLOW_TASK_SCHEDULED":       "Workflow task scheduled",
    "EVENT_TYPE_WORKFLOW_TASK_STARTED":         "Workflow task started",
    "EVENT_TYPE_WORKFLOW_TASK_COMPLETED":       "Workflow task completed",
    "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":       "Activity scheduled",
    "EVENT_TYPE_ACTIVITY_TASK_STARTED":         "Activity started",
    "EVENT_TYPE_ACTIVITY_TASK_COMPLETED":       "Activity completed",
    "EVENT_TYPE_TIMER_STARTED":                 "Timer started",
    "EVENT_TYPE_TIMER_FIRED":                   "Timer elapsed",
    "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED":   "Signal received",
    "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED":  "Workflow completed",
    "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED":     "Workflow failed",
}

_ACTIVITY_FRIENDLY: dict[str, str] = {
    "send_notification":        "Send notification",
    "generate_ai_summary":      "Generate AI summary",
    "_set_waiting_approval":    "Set waiting approval",
    "send_completion_notification": "Send completion notification",
    "_mark_completed":          "Mark completed",
    "_mark_failed":             "Mark failed",
}

_SIGNAL_FRIENDLY: dict[str, str] = {
    "form_submitted":  "Employee submitted self-review form",
    "lead_approved":   "Lead submitted approval and rating",
}

_STAGE_KEY_EVENTS: dict[str, str] = {
    "INITIATED":        "Workflow execution started",
    "WAITING_FORM":     "Notification sent to employee and lead",
    "FORM_SUBMITTED":   "Self-review form received and AI summary generated",
    "WAITING_APPROVAL": "Status set to waiting approval, lead review timer started",
    "APPROVED":         "Lead approved the review and rating recorded",
    "COMPLETED":        "All activities complete, workflow closed",
}


def _activity_name(event) -> str | None:
    """Extract the activity type name from an ACTIVITY_TASK_SCHEDULED event."""
    try:
        return event.activity_task_scheduled_event_attributes.activity_type.name
    except Exception:
        return None


def _signal_name(event) -> str | None:
    """Extract the signal name from a WORKFLOW_EXECUTION_SIGNALED event."""
    try:
        return event.workflow_execution_signaled_event_attributes.signal_name
    except Exception:
        return None


def _event_label(event_type: str, event) -> str:
    """Build a human-readable label for a single Temporal event."""
    if event_type == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED":
        name = _activity_name(event)
        return _ACTIVITY_FRIENDLY.get(name, f"Activity: {name}") if name else "Activity scheduled"
    if event_type == "EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED":
        name = _signal_name(event)
        return _SIGNAL_FRIENDLY.get(name, f"Signal: {name}") if name else "Signal received"
    return _EVENT_LABELS.get(event_type, event_type)


def _key_event(stage_name: str, events: list) -> str | None:
    """Return a single-line summary for the stage, or None if the stage has no events."""
    if not events:
        return None
    return _STAGE_KEY_EVENTS.get(stage_name)


class WorkflowService:
    """Service class encapsulating all review workflow operations.

    Attributes:
        db: SQLAlchemy async session for database operations.
        temporal_client: Connected Temporal client for workflow management.
    """

    def __init__(self, db: AsyncSession, temporal_client: Client) -> None:
        self.db = db
        self.temporal_client = temporal_client

    async def start_review(self, employee_id: str, lead_id: str) -> StartReviewResponse:
        """Create a DB record and start a new Temporal review workflow.

        Generates a unique ``workflow_id`` in the format
        ``review-{employee_id}-{8-char hex}``, inserts the row with status
        ``INITIATED``, then starts the Temporal execution. The DB commit is
        deferred until after the Temporal call succeeds to ensure atomicity.

        Args:
            employee_id: Identifier of the employee under review.
            lead_id: Identifier of the approving lead.

        Returns:
            A :class:`~app.schemas.review.StartReviewResponse` with the new
            workflow ID and initial status.
        """
        workflow_id = f"review-{employee_id}-{uuid.uuid4().hex[:8]}"

        row = ReviewWorkflow(
            workflow_id=workflow_id,
            employee_id=employee_id,
            lead_id=lead_id,
            status=ReviewStatus.INITIATED,
        )
        self.db.add(row)
        await self.db.flush()

        from app.temporal.workflows.review_workflow import ReviewWorkflow as _ReviewWorkflow
        await self.temporal_client.start_workflow(
            _ReviewWorkflow.run,
            ReviewWorkflowInput(
                workflow_id=workflow_id,
                employee_id=employee_id,
                lead_id=lead_id,
            ),
            id=workflow_id,
            task_queue=TASK_QUEUE,
        )

        await self.db.commit()
        await self.db.refresh(row)
        logger.info("Started review workflow | workflow_id=%s", workflow_id)

        return StartReviewResponse(
            workflow_id=row.workflow_id,
            employee_id=row.employee_id,
            lead_id=row.lead_id,
            status=ReviewStatus(row.status),
            created_at=row.created_at,
        )

    async def list_reviews(
        self,
        status: ReviewStatus | None,
        page: int,
        per_page: int,
    ) -> tuple[list[ReviewSummary], int]:
        """Return a paginated list of review summaries, optionally filtered by status.

        Args:
            status: If provided, only workflows with this status are returned.
            page: Page number to return (1-indexed).
            per_page: Number of records per page.

        Returns:
            A tuple of ``(list of ReviewSummary, total record count)``.
        """
        stmt = select(ReviewWorkflow)
        count_stmt = select(func.count()).select_from(ReviewWorkflow)

        if status:
            stmt = stmt.where(ReviewWorkflow.status == status)
            count_stmt = count_stmt.where(ReviewWorkflow.status == status)

        total = (await self.db.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ReviewWorkflow.created_at.desc())
        stmt = stmt.offset((page - 1) * per_page).limit(per_page)
        rows = (await self.db.execute(stmt)).scalars().all()

        return [ReviewSummary.model_validate(r) for r in rows], total

    async def get_review(self, workflow_id: str) -> ReviewDetail:
        """Fetch a single review's full detail by workflow ID.

        Args:
            workflow_id: The unique Temporal workflow identifier.

        Returns:
            A fully populated :class:`~app.schemas.review.ReviewDetail`.

        Raises:
            LookupError: If no record with the given ``workflow_id`` exists.
        """
        row = await self._get_row_or_404(workflow_id)
        return ReviewDetail.model_validate(row)

    async def send_form_submitted_signal(self, workflow_id: str, form_data: dict) -> None:
        """Deliver the ``form_submitted`` signal to a waiting workflow.

        Validates that the workflow is in the ``WAITING_FORM`` state before
        sending the signal. The signal is delivered asynchronously to the
        running Temporal execution.

        Args:
            workflow_id: The target workflow identifier.
            form_data: The employee's self-review form payload.

        Raises:
            LookupError: If no workflow with the given ID exists.
            ValueError: If the workflow is not in ``WAITING_FORM`` state.
        """
        row = await self._get_row_or_404(workflow_id)
        if row.status != ReviewStatus.WAITING_FORM:
            raise ValueError(
                f"Workflow {workflow_id} is not awaiting a form (current status: {row.status})"
            )

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        await handle.signal(SIGNAL_FORM_SUBMITTED, form_data)
        logger.info("Sent form_submitted signal | workflow_id=%s", workflow_id)

    async def send_lead_approved_signal(self, workflow_id: str, rating: str) -> None:
        """Deliver the ``lead_approved`` signal to a workflow awaiting approval.

        Validates that the workflow is in the ``WAITING_APPROVAL`` state before
        sending the signal.

        Args:
            workflow_id: The target workflow identifier.
            rating: The lead's rating string (e.g. ``"meets_expectations"``).

        Raises:
            LookupError: If no workflow with the given ID exists.
            ValueError: If the workflow is not in ``WAITING_APPROVAL`` state.
        """
        row = await self._get_row_or_404(workflow_id)
        if row.status != ReviewStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Workflow {workflow_id} is not awaiting approval (current status: {row.status})"
            )

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        await handle.signal(SIGNAL_LEAD_APPROVED, rating)
        logger.info("Sent lead_approved signal | workflow_id=%s", workflow_id)

    async def get_workflow_history(self, workflow_id: str) -> WorkflowHistoryResponse:
        """Fetch and group the Temporal execution history into logical workflow stages.

        Parses raw Temporal events and buckets them into the six stages of the review
        lifecycle using activity type names and signal names as transition triggers.

        Stage transitions are detected by:
            - ``send_notification`` activity scheduled → enter WAITING_FORM
            - ``form_submitted`` signal received → enter FORM_SUBMITTED
            - ``_set_waiting_approval`` activity scheduled → enter WAITING_APPROVAL
            - ``lead_approved`` signal received → enter APPROVED
            - ``_mark_completed`` activity scheduled → enter COMPLETED

        Args:
            workflow_id: The target workflow identifier.

        Returns:
            A :class:`~app.schemas.review.WorkflowHistoryResponse` with stages,
            each containing grouped events, status, timestamps, and a key event summary.

        Raises:
            LookupError: If no workflow with the given ID exists in the DB.
        """
        await self._get_row_or_404(workflow_id)

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()

        # Stage definitions in execution order
        stage_defs = [
            ("INITIATED",         "Initiated",         "Workflow created"),
            ("WAITING_FORM",      "Waiting Form",      "Notification sent, awaiting self-review"),
            ("FORM_SUBMITTED",    "Form Submitted",     "Self-review received, AI summary generated"),
            ("WAITING_APPROVAL",  "Waiting Approval",  "AI summary ready, awaiting lead approval"),
            ("APPROVED",          "Approved",           "Lead approved, completion notification sent"),
            ("COMPLETED",         "Completed",          "Review process complete"),
        ]

        # Buckets: one list of StageEvent per stage
        buckets: list[list[StageEvent]] = [[] for _ in stage_defs]
        current = 0  # index into stage_defs

        for raw in history.events:
            event_type = temporalio.api.enums.v1.EventType.Name(raw.event_type)
            ts = raw.event_time.ToDatetime().isoformat() if raw.event_time else ""

            # Detect stage transition before assigning this event
            if current == 0 and _activity_name(raw) == "send_notification":
                current = 1
            elif current == 1 and _signal_name(raw) == SIGNAL_FORM_SUBMITTED:
                current = 2
            elif current == 2 and _activity_name(raw) == "_set_waiting_approval":
                current = 3
            elif current == 3 and _signal_name(raw) == SIGNAL_LEAD_APPROVED:
                current = 4
            elif current == 4 and _activity_name(raw) == "_mark_completed":
                current = 5

            buckets[current].append(
                StageEvent(
                    event_id=raw.event_id,
                    event_type=event_type,
                    label=_event_label(event_type, raw),
                    timestamp=ts,
                )
            )

        stages: list[WorkflowStage] = []
        for i, (name, label, description) in enumerate(stage_defs):
            evts = buckets[i]
            started_at = evts[0].timestamp if evts else None
            completed_at = evts[-1].timestamp if evts else None

            if not evts:
                status = "pending"
                completed_at = None
            elif i < current:
                status = "completed"
            elif i == current:
                # Last stage (COMPLETED) with WORKFLOW_EXECUTION_COMPLETED event → fully done
                last_type = evts[-1].event_type if evts else ""
                status = "completed" if last_type == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED" else "active"
                if status == "active":
                    completed_at = None
            else:
                status = "pending"
                started_at = None
                completed_at = None

            stages.append(
                WorkflowStage(
                    name=name,
                    label=label,
                    description=description,
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    event_count=len(evts),
                    key_event=_key_event(name, evts),
                    events=evts,
                )
            )

        return WorkflowHistoryResponse(
            workflow_id=workflow_id,
            total_events=len(history.events),
            stages=stages,
        )

    async def _get_row_or_404(self, workflow_id: str) -> ReviewWorkflow:
        """Fetch a workflow DB row by ID, raising ``LookupError`` if absent.

        Args:
            workflow_id: The unique workflow identifier to look up.

        Returns:
            The matching :class:`~app.models.review.ReviewWorkflow` ORM instance.

        Raises:
            LookupError: If no row with the given ``workflow_id`` exists.
                Mapped to HTTP 404 by the global exception handler in ``app/main.py``.
        """
        stmt = select(ReviewWorkflow).where(ReviewWorkflow.workflow_id == workflow_id)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Workflow {workflow_id} not found")
        return row
