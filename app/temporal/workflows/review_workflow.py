"""Temporal workflow definition for the employee review lifecycle.

The workflow is started by ``WorkflowService.start_review()`` and progresses
through its states by executing activities and waiting for external signals.

Signal flow:
    1. ``form_submitted`` — sent by the employee via ``POST …/signal/form_submitted``
    2. ``lead_approved``  — sent by the lead via ``POST …/signal/lead_approved``

Status-transition activities (``_set_waiting_approval``, ``_mark_completed``,
``_mark_failed``) are defined at the bottom of this module rather than in
``activities/`` to avoid circular imports while still keeping DB writes
retryable by Temporal.

Activity imports are wrapped in ``workflow.unsafe.imports_passed_through()``
to bypass Temporal's determinism sandbox, which would otherwise block I/O-
capable imports inside the workflow execution context.
"""

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
    """Input passed to :class:`ReviewWorkflow` when the execution is started.

    Attributes:
        workflow_id: Unique ID used as both the Temporal workflow ID and the
            database ``workflow_id`` foreign key.
        employee_id: Employee under review.
        lead_id: Lead who will approve the review.
    """

    workflow_id: str
    employee_id: str
    lead_id: str


@dataclass
class ReviewWorkflowResult:
    """Value returned when the workflow execution completes.

    Attributes:
        workflow_id: The completed workflow's identifier.
        status: Terminal status string (``"COMPLETED"`` or propagated exception).
    """

    workflow_id: str
    status: str


@workflow.defn
class ReviewWorkflow:
    """Durable Temporal workflow orchestrating the full employee review lifecycle.

    State is held in instance variables that are populated by inbound signals.
    All I/O (DB writes, notifications, AI calls) is delegated to activities so
    that failures are retried automatically without re-running workflow logic.
    """

    def __init__(self) -> None:
        self._form_data: dict | None = None
        self._rating: str | None = None

    @workflow.signal(name=SIGNAL_FORM_SUBMITTED)
    async def handle_form_submitted(self, form_data: dict) -> None:
        """Receive the employee's self-review form via Temporal signal.

        Sets ``_form_data``, which unblocks the ``wait_condition`` in :meth:`run`.

        Args:
            form_data: The free-form JSON payload submitted by the employee.
        """
        self._form_data = form_data

    @workflow.signal(name=SIGNAL_LEAD_APPROVED)
    async def handle_lead_approved(self, rating: str) -> None:
        """Receive the lead's approval and rating via Temporal signal.

        Sets ``_rating``, which unblocks the ``wait_condition`` in :meth:`run`.

        Args:
            rating: The lead's rating string (e.g. ``"exceeds_expectations"``).
        """
        self._rating = rating

    @workflow.run
    async def run(self, input: ReviewWorkflowInput) -> ReviewWorkflowResult:
        """Execute the review workflow from start to completion.

        Step sequence:
            1. ``send_notification`` activity — sets DB status to ``WAITING_FORM``.
            2. ``workflow.sleep(30s)`` — simulates a real-world waiting period.
            3. Wait for the ``form_submitted`` signal (blocks indefinitely).
            4. ``generate_ai_summary`` activity — persists form data and AI summary;
               sets DB status to ``FORM_SUBMITTED``.
            5. ``_set_waiting_approval`` activity — sets DB status to ``WAITING_APPROVAL``.
            6. ``workflow.sleep(10s)`` — simulates the lead review period.
            7. Wait for the ``lead_approved`` signal (blocks indefinitely).
            8. ``send_completion_notification`` activity — persists rating;
               sets DB status to ``APPROVED``.
            9. ``_mark_completed`` activity — sets DB status to ``COMPLETED``.

        If any step raises an unhandled exception, ``_mark_failed`` is called
        before re-raising so the DB row always reflects the terminal error state.

        Args:
            input: Workflow identifiers required by the activities.

        Returns:
            A :class:`ReviewWorkflowResult` with ``status="COMPLETED"``.

        Raises:
            Exception: Re-raises any activity exception after marking the
                workflow as ``FAILED`` in the database.
        """
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
    """Set the workflow DB status to ``WAITING_APPROVAL``.

    Called after the AI summary has been generated and the lead review period
    sleep has elapsed.

    Args:
        workflow_id: Temporal workflow ID used to locate the DB row.
    """
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
    """Set the workflow DB status to ``COMPLETED``.

    Called as the final step of the happy-path execution after the completion
    notification has been sent.

    Args:
        workflow_id: Temporal workflow ID used to locate the DB row.
    """
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
    """Set the workflow DB status to ``FAILED``.

    Called inside the ``except`` block of :meth:`ReviewWorkflow.run` to ensure
    the DB row always reflects a terminal error state when execution fails.

    Args:
        workflow_id: Temporal workflow ID used to locate the DB row.
    """
    from sqlalchemy import select
    from app.database import AsyncSessionFactory
    from app.models.review import ReviewWorkflow as _ReviewWorkflow

    async with AsyncSessionFactory() as session:
        stmt = select(_ReviewWorkflow).where(_ReviewWorkflow.workflow_id == workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.FAILED
            await session.commit()
