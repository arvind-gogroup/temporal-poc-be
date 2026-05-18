"""AI summary generation activity for the employee review workflow.

When ``AI_SUMMARY_MOCK=true`` (the default), a deterministic template string
is returned without any external call. Set ``AI_SUMMARY_MOCK=false`` and wire
up a real LLM client inside the ``else`` branch to enable live summaries.

DB writes are performed inside the activity so they are retried by Temporal
on transient failures.
"""

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
    """Input for the :func:`generate_ai_summary` activity.

    Attributes:
        workflow_id: Temporal workflow ID used to look up and update the DB row.
        employee_id: Identifier of the employee whose form is being summarised.
        form_data: The raw self-review payload submitted by the employee.
    """

    workflow_id: str
    employee_id: str
    form_data: dict


@activity.defn
async def generate_ai_summary(input: AISummaryInput) -> str:
    """Generate an AI performance summary from the employee's self-review form.

    In mock mode (``AI_SUMMARY_MOCK=true``), constructs a template string using
    the ``goals_met`` and ``self_assessment`` fields from ``form_data``.

    After generating the summary, persists ``form_data``, ``ai_summary``, and
    sets the workflow status to ``FORM_SUBMITTED`` in the database.

    Args:
        input: Workflow ID, employee ID, and the submitted form data.

    Returns:
        The generated (or mocked) summary string.

    Raises:
        NotImplementedError: If ``AI_SUMMARY_MOCK=false`` and no LLM client
            has been wired up yet.
    """
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
