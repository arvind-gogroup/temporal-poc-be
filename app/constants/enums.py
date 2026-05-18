"""Shared enumerations used across the application.

All enums are string-based so they serialise cleanly in JSON responses and
can be compared directly with the string values stored in the database.
"""

from enum import Enum


class ReviewStatus(str, Enum):
    """Lifecycle states for an employee review workflow.

    States progress in this order during the happy path:
        INITIATED → WAITING_FORM → FORM_SUBMITTED → WAITING_APPROVAL
        → APPROVED → COMPLETED

    FAILED is a terminal error state reachable from any step.

    Attributes:
        INITIATED: Workflow record created; Temporal execution not yet started.
        WAITING_FORM: Employee has been notified; waiting for self-review submission.
        FORM_SUBMITTED: Form received; AI summary generation is in progress.
        WAITING_APPROVAL: AI summary ready; waiting for lead to approve.
        APPROVED: Lead approved the review; workflow is finalising.
        COMPLETED: Workflow finished successfully; rating is persisted.
        FAILED: An unrecoverable error occurred during execution.
    """

    INITIATED = "INITIATED"
    WAITING_FORM = "WAITING_FORM"
    FORM_SUBMITTED = "FORM_SUBMITTED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
