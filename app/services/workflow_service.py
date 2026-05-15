import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
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
    def __init__(self, db: AsyncSession, temporal_client: Client) -> None:
        self.db = db
        self.temporal_client = temporal_client

    async def start_review(self, employee_id: str, lead_id: str) -> StartReviewResponse:
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
        row = await self._get_row_or_404(workflow_id)
        return ReviewDetail.model_validate(row)

    async def send_form_submitted_signal(self, workflow_id: str, form_data: dict) -> None:
        row = await self._get_row_or_404(workflow_id)
        if row.status != ReviewStatus.WAITING_FORM:
            raise ValueError(
                f"Workflow {workflow_id} is not awaiting a form (current status: {row.status})"
            )

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        await handle.signal(SIGNAL_FORM_SUBMITTED, form_data)
        logger.info("Sent form_submitted signal | workflow_id=%s", workflow_id)

    async def send_lead_approved_signal(self, workflow_id: str, rating: str) -> None:
        row = await self._get_row_or_404(workflow_id)
        if row.status != ReviewStatus.WAITING_APPROVAL:
            raise ValueError(
                f"Workflow {workflow_id} is not awaiting approval (current status: {row.status})"
            )

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        await handle.signal(SIGNAL_LEAD_APPROVED, rating)
        logger.info("Sent lead_approved signal | workflow_id=%s", workflow_id)

    async def get_workflow_history(self, workflow_id: str) -> WorkflowHistoryResponse:
        await self._get_row_or_404(workflow_id)

        handle = self.temporal_client.get_workflow_handle(workflow_id)
        history = await handle.fetch_history()

        events: list[HistoryEvent] = []
        for event in history.events:
            events.append(
                HistoryEvent(
                    event_id=event.event_id,
                    event_type=event.event_type.name,
                    timestamp=event.event_time.isoformat() if event.event_time else "",
                    attributes={},
                )
            )

        return WorkflowHistoryResponse(workflow_id=workflow_id, events=events)

    async def _get_row_or_404(self, workflow_id: str) -> ReviewWorkflow:
        stmt = select(ReviewWorkflow).where(ReviewWorkflow.workflow_id == workflow_id)
        row = (await self.db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Workflow {workflow_id} not found")
        return row
