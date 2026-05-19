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
    HistoryEvent,
    ReviewDetail,
    ReviewSummary,
    StartReviewResponse,
    WorkflowHistoryResponse,
)
from app.temporal.workflows.review_workflow import ReviewWorkflowInput

logger = logging.getLogger(__name__)


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
        """Fetch the raw Temporal execution event history for a workflow.

        Validates existence via the DB before calling the Temporal API so that
        a missing workflow returns a 404 rather than a Temporal SDK error.

        Args:
            workflow_id: The target workflow identifier.

        Returns:
            A :class:`~app.schemas.review.WorkflowHistoryResponse` containing
            the ordered list of Temporal execution events.

        Raises:
            LookupError: If no workflow with the given ID exists in the DB.
        """
        await self._get_row_or_404(workflow_id)

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()

        events: list[HistoryEvent] = []
        for event in history.events:
            events.append(
                HistoryEvent(
                    event_id=event.event_id,
                    event_type=temporalio.api.enums.v1.EventType.Name(event.event_type),
                    timestamp=event.event_time.ToDatetime().isoformat() if event.event_time else "",
                    attributes={},
                )
            )

        return WorkflowHistoryResponse(workflow_id=workflow_id, events=events)

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
