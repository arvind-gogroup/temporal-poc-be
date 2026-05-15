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
    try:
        data = await service.get_workflow_history(workflow_id)
        return success_response(data)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
