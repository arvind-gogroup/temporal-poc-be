from app.config import settings

TASK_QUEUE: str = settings.TEMPORAL_TASK_QUEUE

SIGNAL_FORM_SUBMITTED: str = "form_submitted"
SIGNAL_LEAD_APPROVED: str = "lead_approved"

WORKFLOW_TYPE_REVIEW: str = "ReviewWorkflow"
