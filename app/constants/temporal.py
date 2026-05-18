"""Temporal-specific constants shared between the API, worker, and workflow.

Centralising these here means a task-queue rename or new signal name only
requires a single change rather than updates scattered across modules.
"""

from app.config import settings

TASK_QUEUE: str = settings.TEMPORAL_TASK_QUEUE
"""Name of the Temporal task queue polled by the worker process."""

SIGNAL_FORM_SUBMITTED: str = "form_submitted"
"""Signal name sent when the employee submits their self-review form."""

SIGNAL_LEAD_APPROVED: str = "lead_approved"
"""Signal name sent when the lead approves the review with a rating."""

WORKFLOW_TYPE_REVIEW: str = "ReviewWorkflow"
"""Temporal workflow type name; matches the class decorated with @workflow.defn."""
