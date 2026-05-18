"""FastAPI route handlers for the /api/reviews resource.

All handlers follow the same pattern:
    1. Delegate to ``WorkflowService`` for business logic.
    2. Return an ``ApiResponse[T]`` envelope.
    3. Let ``LookupError`` / ``ValueError`` propagate to the global exception
       handlers in ``app/main.py`` (HTTP 404 / 409 respectively).

The ``_get_service`` dependency constructs a per-request ``WorkflowService``
injecting the DB session and Temporal client stored on ``app.state``.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.enums import ReviewStatus
from app.database import get_db
from app.schemas.response import ApiResponse, error_response, paginated_response, success_response
from app.schemas.review import (
    FormSubmittedRequest,
    LeadApprovedRequest,
    ReviewDetail,
    ReviewSummary,
    SignalResponse,
    StartReviewRequest,
    StartReviewResponse,
    WorkflowHistoryResponse,
)
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


def _get_service(request: Request, db: AsyncSession = Depends(get_db)) -> WorkflowService:
    """FastAPI dependency that builds a ``WorkflowService`` for the current request.

    Args:
        request: The active FastAPI request; provides access to ``app.state``.
        db: Injected async database session from ``get_db``.

    Returns:
        A ``WorkflowService`` wired with the session and Temporal client.
    """
    return WorkflowService(db=db, temporal_client=request.app.state.temporal_client)


@router.post(
    "/start",
    status_code=status.HTTP_201_CREATED,
    summary="Start a new employee review workflow",
    response_model=ApiResponse[StartReviewResponse],
)
async def start_review(
    body: StartReviewRequest,
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[StartReviewResponse]:
    """Start a new Temporal-backed employee review workflow.

    Creates a ``review_workflows`` DB row with status ``INITIATED`` and
    starts the Temporal execution. Returns HTTP 201 with the new workflow ID.

    Args:
        body: ``employee_id`` and ``lead_id`` for the review.
        service: Injected ``WorkflowService``.

    Returns:
        ``ApiResponse`` containing the new workflow details.
    """
    try:
        data = await service.start_review(body.employee_id, body.lead_id)
        return success_response(data, code=201)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "",
    summary="List all review workflows",
    response_model=ApiResponse[list[ReviewSummary]],
)
async def list_reviews(
    filter_status: ReviewStatus | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[list[ReviewSummary]]:
    """Return a paginated list of all review workflows.

    Args:
        filter_status: Optional status filter (maps to the ``status`` query param).
        page: Page number to return (min 1, default 1).
        per_page: Records per page (range 1–100, default 20).
        service: Injected ``WorkflowService``.

    Returns:
        Paginated ``ApiResponse`` with a list of :class:`~app.schemas.review.ReviewSummary`.
    """
    rows, total = await service.list_reviews(filter_status, page, per_page)
    filters = {"status": filter_status} if filter_status else None
    return paginated_response(rows, page=page, per_page=per_page, total_records=total, filters=filters)


@router.get(
    "/{workflow_id}",
    summary="Get a single review workflow",
    response_model=ApiResponse[ReviewDetail],
)
async def get_review(
    workflow_id: str,
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[ReviewDetail]:
    """Return the full detail of a single review workflow.

    Includes form data, AI summary, and rating once they become available.

    Args:
        workflow_id: The unique Temporal workflow identifier.
        service: Injected ``WorkflowService``.

    Returns:
        ``ApiResponse`` containing a :class:`~app.schemas.review.ReviewDetail`.

    Raises:
        HTTPException: 404 if ``workflow_id`` is not found.
    """
    try:
        data = await service.get_review(workflow_id)
        return success_response(data)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{workflow_id}/signal/form_submitted",
    summary="Send form_submitted signal to a waiting workflow",
    response_model=ApiResponse[SignalResponse],
)
async def signal_form_submitted(
    workflow_id: str,
    body: FormSubmittedRequest,
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[SignalResponse]:
    """Deliver the employee's self-review form to a waiting workflow.

    Only valid when the workflow status is ``WAITING_FORM``. Returns 409 if
    the workflow is in any other state.

    Args:
        workflow_id: The target workflow identifier.
        body: The employee's self-review form payload.
        service: Injected ``WorkflowService``.

    Returns:
        ``ApiResponse`` with a confirmation :class:`~app.schemas.review.SignalResponse`.

    Raises:
        HTTPException: 404 if not found; 409 if status is not ``WAITING_FORM``.
    """
    try:
        await service.send_form_submitted_signal(workflow_id, body.form_data)
        return success_response(SignalResponse(message="Signal sent", workflow_id=workflow_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{workflow_id}/signal/lead_approved",
    summary="Send lead_approved signal to a waiting workflow",
    response_model=ApiResponse[SignalResponse],
)
async def signal_lead_approved(
    workflow_id: str,
    body: LeadApprovedRequest,
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[SignalResponse]:
    """Deliver the lead's approval and rating to a workflow awaiting approval.

    Only valid when the workflow status is ``WAITING_APPROVAL``. Returns 409
    if the workflow is in any other state.

    Args:
        workflow_id: The target workflow identifier.
        body: The lead's rating string.
        service: Injected ``WorkflowService``.

    Returns:
        ``ApiResponse`` with a confirmation :class:`~app.schemas.review.SignalResponse`.

    Raises:
        HTTPException: 404 if not found; 409 if status is not ``WAITING_APPROVAL``.
    """
    try:
        await service.send_lead_approved_signal(workflow_id, body.rating)
        return success_response(SignalResponse(message="Signal sent", workflow_id=workflow_id))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{workflow_id}/history",
    summary="Get Temporal execution history for a workflow",
    response_model=ApiResponse[WorkflowHistoryResponse],
)
async def get_workflow_history(
    workflow_id: str,
    service: WorkflowService = Depends(_get_service),
) -> ApiResponse[WorkflowHistoryResponse]:
    """Return the raw Temporal execution event history for audit or debug use.

    Args:
        workflow_id: The target workflow identifier.
        service: Injected ``WorkflowService``.

    Returns:
        ``ApiResponse`` containing a :class:`~app.schemas.review.WorkflowHistoryResponse`
        with an ordered list of Temporal execution events.

    Raises:
        HTTPException: 404 if ``workflow_id`` is not found.
    """
    try:
        data = await service.get_workflow_history(workflow_id)
        return success_response(data)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
