"""Notification activities for the employee review workflow.

Both activities are currently stub implementations that log instead of
calling real external services (Slack, email, etc.). Replace the log
statements with real API calls when integrating with a notification provider.

DB writes are performed inside each activity so they are retried by Temporal
on transient failures — never call these functions directly from application code.
"""

import logging
from dataclasses import dataclass

from temporalio import activity

from app.constants.enums import ReviewStatus
from app.database import AsyncSessionFactory
from app.models.review import ReviewWorkflow

logger = logging.getLogger(__name__)


@dataclass
class NotificationInput:
    """Input for the :func:`send_notification` activity.

    Attributes:
        workflow_id: Temporal workflow ID used to look up the DB row.
        employee_id: Employee to be notified about their upcoming review.
        lead_id: Lead who will approve the review.
    """

    workflow_id: str
    employee_id: str
    lead_id: str


@dataclass
class CompletionNotificationInput:
    """Input for the :func:`send_completion_notification` activity.

    Attributes:
        workflow_id: Temporal workflow ID used to look up the DB row.
        employee_id: Employee to be notified of the completed review.
        lead_id: Lead who approved the review.
        rating: The rating string submitted by the lead.
        ai_summary: The AI-generated performance summary.
    """

    workflow_id: str
    employee_id: str
    lead_id: str
    rating: str
    ai_summary: str


@activity.defn
async def send_notification(input: NotificationInput) -> str:
    """Notify the employee that their review has started; set status to WAITING_FORM.

    Stub implementation: logs the notification instead of calling Slack/email.
    Persists the ``WAITING_FORM`` status to the database.

    Args:
        input: Identifiers for the workflow, employee, and lead.

    Returns:
        A confirmation message string.
    """
    logger.info(
        "[SLACK DM] Sending review notification | employee=%s lead=%s workflow=%s",
        input.employee_id,
        input.lead_id,
        input.workflow_id,
    )

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        stmt = select(ReviewWorkflow).where(ReviewWorkflow.workflow_id == input.workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.WAITING_FORM
            await session.commit()

    logger.info(
        "[SLACK DM] Notification sent — status set to WAITING_FORM | workflow=%s",
        input.workflow_id,
    )
    return f"Notification sent to employee {input.employee_id} via lead {input.lead_id}"


@activity.defn
async def send_completion_notification(input: CompletionNotificationInput) -> str:
    """Notify the employee of review completion; persist rating and set status to APPROVED.

    Stub implementation: logs the notification instead of calling an email provider.
    Persists the ``APPROVED`` status and the lead's rating to the database.

    Args:
        input: Identifiers, rating, and AI summary for the completed review.

    Returns:
        A confirmation message string.
    """
    logger.info(
        "[EMAIL] Sending completion notification | employee=%s rating=%s workflow=%s",
        input.employee_id,
        input.rating,
        input.workflow_id,
    )

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        stmt = select(ReviewWorkflow).where(ReviewWorkflow.workflow_id == input.workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.status = ReviewStatus.APPROVED
            row.rating = input.rating
            await session.commit()

    logger.info(
        "[EMAIL] Completion notification sent | workflow=%s",
        input.workflow_id,
    )
    return f"Completion email sent to employee {input.employee_id} with rating {input.rating}"
