from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class StatusSchema(BaseModel):
    success: bool
    code: int
    message: str | None = None


class MetaSchema(BaseModel):
    page: int | None = None
    per_page: int | None = None
    total_pages: int | None = None
    total_records: int | None = None
    filters: dict | None = None


class ApiResponse(BaseModel, Generic[T]):
    payload: T | None
    status: StatusSchema
    meta: MetaSchema | None = None


def success_response(data: T, code: int = 200, meta: MetaSchema | None = None) -> ApiResponse[T]:
    return ApiResponse(
        payload=data,
        status=StatusSchema(success=True, code=code),
        meta=meta,
    )


def error_response(message: str, code: int = 400) -> ApiResponse[None]:
    return ApiResponse(
        payload=None,
        status=StatusSchema(success=False, code=code, message=message),
    )


def paginated_response(
    data: list,
    page: int,
    per_page: int,
    total_records: int,
    filters: dict | None = None,
) -> ApiResponse[list]:
    import math

    total_pages = math.ceil(total_records / per_page) if per_page > 0 else 0
    meta = MetaSchema(
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_records=total_records,
        filters=filters,
    )
    return success_response(data, code=200, meta=meta)
