"""FastAPI dependency factories."""
import uuid

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.services.review_service import ReviewService


async def get_current_user_id(
    x_user_id: str = Header(default="00000000-0000-0000-0000-000000000001"),
) -> uuid.UUID:
    """
    Extracts user ID from X-User-Id header.
    In production: replace with JWT decode / OAuth2 validation.
    """
    try:
        return uuid.UUID(x_user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid X-User-Id header.",
        )


async def get_review_service(db: AsyncSession = Depends(get_db)) -> ReviewService:
    return ReviewService(db)
