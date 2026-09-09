"""Reusable pagination primitives shared by every list endpoint."""
import math
from dataclasses import dataclass

from fastapi import Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.responses import PaginatedData


@dataclass
class PageParams:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def pagination_params(
    page: int = Query(1, ge=1, description="1-indexed page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def paginate(db: Session, base_stmt, params: PageParams) -> PaginatedData:
    """
    Apply LIMIT/OFFSET to a SQLAlchemy select() statement and return a
    PaginatedData envelope. `base_stmt` should already have its filters
    (including tenant/gym_id scoping) applied.
    """
    total = db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0
    items = db.scalars(base_stmt.offset(params.offset).limit(params.page_size)).all()
    total_pages = math.ceil(total / params.page_size) if total else 0
    return PaginatedData(
        items=list(items),
        total=total,
        page=params.page,
        page_size=params.page_size,
        total_pages=total_pages,
    )
