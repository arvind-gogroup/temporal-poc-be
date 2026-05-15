import logging
from dataclasses import dataclass
from datetime import datetime

from temporalio import activity

from app.config import settings
from app.constants.enums import ReviewStatus
from app.database import AsyncSessionFactory
from app.models.review import ReviewWorkflow

logger = logging.getLogger(__name__)


@dataclass
class AISummaryInput:
    workflow_id: str
    employee_id: str
    form_data: dict


@activity.defn
async def generate_ai_summary(input: AISummaryInput) -> str:
    logger.info(
        "[AI] Generating summary | employee=%s workflow=%s",
        input.employee_id,
        input.workflow_id,
    )

    if settings.AI_SUMMARY_MOCK:
        quarter = (datetime.now().month - 1) // 3 + 1
        goals_met = input.form_data.get("goals_met", False)
        assessment = input.form_data.get("self_assessment", "")
        summary = (
            f"Performance summary for employee {input.employee_id} (Q{quarter}): "
            f"Goals {'met' if goals_met else 'partially met'}. "
            f"Self-assessment highlights: \"{assessment[:100]}\". "
            f"Overall trajectory appears positive based on submitted review data."
        )
    else:
        # Replace with real LLM call
        raise NotImplementedError("Live AI summary not yet wired up — set AI_SUMMARY_MOCK=true")

    async with AsyncSessionFactory() as session:
        from sqlalchemy import select
        stmt = select(ReviewWorkflow).where(ReviewWorkflow.workflow_id == input.workflow_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row:
            row.form_data = input.form_data
            row.ai_summary = summary
            row.status = ReviewStatus.FORM_SUBMITTED
            await session.commit()

    logger.info("[AI] Summary generated and persisted | workflow=%s", input.workflow_id)
    return summary
