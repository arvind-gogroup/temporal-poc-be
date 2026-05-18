"""Universal response envelope used by every API endpoint.

All responses — success or error — share the same top-level structure so the
frontend can always unwrap via ``response.payload``:

    {
        "payload": <data> | null,
        "status": { "success": bool, "code": int, "message"?: str },
        "meta": { "page": int, ... } | null   # paginated lists only
    }

Use the helper functions rather than constructing ``ApiResponse`` directly.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class StatusSchema(BaseModel):
    """Status block present in every API response.

    Attributes:
        success: ``True`` for 2xx responses, ``False`` for errors.
        code: HTTP status code mirrored from the response (e.g. 200, 404).
        message: Human-readable error detail. Absent on successful responses.
    """

    success: bool
    code: int
    message: str | None = None


class MetaSchema(BaseModel):
    """Pagination metadata returned on list endpoints.

    Attributes:
        page: Current page number (1-indexed).
        per_page: Number of records requested per page.
        total_pages: Total number of pages given the current ``per_page``.
        total_records: Total number of matching records across all pages.
        filters: Active query filters applied to the list, if any.
    """

    page: int | None = None
    per_page: int | None = None
    total_pages: int | None = None
    total_records: int | None = None
    filters: dict | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Generic response envelope wrapping every API payload.

    Type parameter ``T`` is the shape of the ``payload`` field.

    Attributes:
        payload: The response data, or ``None`` on error.
        status: Success/error metadata including the HTTP code.
        meta: Pagination info, present only on paginated list responses.
    """

    payload: T | None
    status: StatusSchema
    meta: MetaSchema | None = None


def success_response(data: T, code: int = 200, meta: MetaSchema | None = None) -> ApiResponse[T]:
    """Build a successful ``ApiResponse`` wrapping ``data``.

    Args:
        data: The response payload to wrap.
        code: HTTP status code to embed (default 200).
        meta: Optional pagination metadata for list responses.

    Returns:
        A fully constructed ``ApiResponse`` with ``status.success = True``.
    """
    return ApiResponse(
        payload=data,
        status=StatusSchema(success=True, code=code),
        meta=meta,
    )


def error_response(message: str, code: int = 400) -> ApiResponse[None]:
    """Build an error ``ApiResponse`` with ``payload: null``.

    Args:
        message: Human-readable error description surfaced to the client.
        code: HTTP status code to embed (default 400).

    Returns:
        An ``ApiResponse`` with ``payload=None`` and ``status.success = False``.
    """
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
    """Build a paginated ``ApiResponse`` for list endpoints.

    Calculates ``total_pages`` automatically from ``total_records`` and
    ``per_page``, then delegates to :func:`success_response`.

    Args:
        data: The current page of records.
        page: Current page number (1-indexed).
        per_page: Number of records per page.
        total_records: Total number of matching records across all pages.
        filters: Active filters to echo back in the ``meta`` block.

    Returns:
        An ``ApiResponse`` with a populated ``meta`` pagination block.
    """
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
