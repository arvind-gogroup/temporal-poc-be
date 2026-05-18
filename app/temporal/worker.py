"""Temporal worker process entrypoint.

Registers all workflows and activities on the ``review-task-queue`` task queue
and polls Temporal for work. Run directly via Docker Compose (``worker`` service)
or locally with:

    python -m app.temporal.worker

The worker shares the same Docker image as the API (``Dockerfile.api``) but
runs a different command and maintains its own Temporal client connection.
"""

import asyncio
import logging

from temporalio.worker import Worker

from app.config import settings
from app.constants.temporal import TASK_QUEUE
from app.temporal.activities.ai_summary import generate_ai_summary
from app.temporal.activities.notification import send_completion_notification, send_notification
from app.temporal.client import get_temporal_client
from app.temporal.workflows.review_workflow import (
    ReviewWorkflow,
    _mark_completed,
    _mark_failed,
    _set_waiting_approval,
)

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Initialise the Temporal worker and poll indefinitely.

    Connects to Temporal using the shared client helper, registers all six
    activities and the :class:`~app.temporal.workflows.review_workflow.ReviewWorkflow`
    workflow, then blocks until the process is terminated.

    Concurrency limits:
        - ``max_concurrent_activities=10``
        - ``max_concurrent_workflow_tasks=5``
    """
    client = await get_temporal_client()
    logger.info("Worker connecting to task queue '%s'", TASK_QUEUE)

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ReviewWorkflow],
        activities=[
            send_notification,
            generate_ai_summary,
            send_completion_notification,
            _set_waiting_approval,
            _mark_completed,
            _mark_failed,
        ],
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=5,
    )

    logger.info("Worker started — polling task queue '%s'", TASK_QUEUE)
    async with worker:
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
