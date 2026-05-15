import logging
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.constants.enums import ReviewStatus
    from app.constants.temporal import SIGNAL_FORM_SUBMITTED, SIGNAL_LEAD_APPROVED
    from app.temporal.activities.ai_summary import AISummaryInput, generate_ai_summary
    from app.temporal.activities.notification import (
        CompletionNotificationInput,
        NotificationInput,
        send_completion_notification,
        send_notification,
    )

logger = logging.getLogger(__name__)

_ACTIVITY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)


@dataclass
class ReviewWorkflowInput:
    workflow_id: str
    employee_id: str
    lead_id: str


@dataclass
class ReviewWorkflowResult:
    workflow_id: str
    status: str


@workflow.defn
class ReviewWorkflow:
    def __init__(self) -> None:
        self._form_data: dict | None = None
        self._rating: str | None = None

    @workflow.signal(name=SIGNAL_FORM_SUBMITTED)
    async def handle_form_submitted(self, form_data: dict) -> None:
        self._form_data = form_data

    @workflow.signal(name=SIGNAL_LEAD_APPROVED)
    async def handle_lead_approved(self, rating: str) -> None:
        self._rating = rating

    @workflow.run
    async def run(self, input: ReviewWorkflowInput) -> ReviewWorkflowResult:
        try:
            # Step 1 — send initial notification, sets DB status → WAITING_FORM
            await workflow.execute_activity(
                send_notification,
                NotificationInput(
                    workflow_id=input.workflow_id,
                    employee_id=input.employee_id,
                    lead_id=input.lead_id,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_ACTIVITY_RETRY,
            )

            # Step 2 — wait for form window (30s simulates days)
            await workflow.sleep(timedelta(seconds=30))

            # Step 3 — wait for form_submitted signal
            await workflow.wait_condition(lambda: self._form_data is not None)

            # Step 4 — generate AI summary, sets DB status → FORM_SUBMITTED
            ai_summary: str = await workflow.execute_activity(
                generate_ai_summary,
                AISummaryInput(
                    workflow_id=input.workflow_id,
                    employee_id=input.employee_id,
                    form_data=self._form_data,  # type: ignore[arg-type]
                ),
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=_ACTIVITY_RETRY,
            )

            # Step 5 — set status to WAITING_APPROVAL then sleep (10s simulates lead review period)
            await workflow.execute_activity(
                _set_waiting_approval,
                input.workflow_id,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_ACTIVITY_RETRY,
            )
            await workflow.sleep(timedelta(seconds=10))

            # Step 6 — wait for lead_approved signal
            await workflow.wait_condition(lambda: self._rating is not None)

            # Step 7 — send completion notification, sets DB status → APPROVED
            await workflow.execute_activity(
                send_completion_notification,
                CompletionNotificationInput(
                    workflow_id=input.workflow_id,
                    employee_id=input.employee_id,
                    lead_id=input.lead_id,
                    rating=self._rating,  # type: ignore[arg-type]
                    ai_summary=ai_summary,
                ),
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=_ACTIVITY_RETRY,
            )

            # Step 8 — mark COMPLETED
            await workflow.execute_activity(
                _mark_completed,
                input.workflow_id,
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=_ACTIVITY_RETRY,
            )

            return ReviewWorkflowResult(workflow_id=input.workflow_id, status=ReviewStatus.COMPLETED)

        except Exception as exc:
            await workflow.execute_activity(
                _mark_failed,
                input.workflow_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
            raise exc


# Lightweight status-transition activities kept here to avoid circular imports
# and to keep DB writes deterministic and retryable from within the workflow.

from temporalio import activity  # noqa: E402


@activity.defn
async def _set_waiting_approval(workflow_id: str) -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionFactory
    from app.models.review import ReviewWorkflow as _ReviewWorkflow

    async with AsyncSessionFactory() as session:
        stmt = select(_ReviewWorkflow).where(_ReviewWorkflow.workflow_id == workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.WAITING_APPROVAL
            await session.commit()


@activity.defn
async def _mark_completed(workflow_id: str) -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionFactory
    from app.models.review import ReviewWorkflow as _ReviewWorkflow

    async with AsyncSessionFactory() as session:
        stmt = select(_ReviewWorkflow).where(_ReviewWorkflow.workflow_id == workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.COMPLETED
            await session.commit()


@activity.defn
async def _mark_failed(workflow_id: str) -> None:
    from sqlalchemy import select
    from app.database import AsyncSessionFactory
    from app.models.review import ReviewWorkflow as _ReviewWorkflow

    async with AsyncSessionFactory() as session:
        stmt = select(_ReviewWorkflow).where(_ReviewWorkflow.workflow_id == workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.FAILED
            await session.commit()
