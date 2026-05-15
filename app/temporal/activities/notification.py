import logging
from dataclasses import dataclass

from temporalio import activity

from app.constants.enums import ReviewStatus
from app.database import AsyncSessionFactory
from app.models.review import ReviewWorkflow

logger = logging.getLogger(__name__)


@dataclass
class NotificationInput:
    workflow_id: str
    employee_id: str
    lead_id: str


@dataclass
class CompletionNotificationInput:
    workflow_id: str
    employee_id: str
    lead_id: str
    rating: str
    ai_summary: str


@activity.defn
async def send_notification(input: NotificationInput) -> str:
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
