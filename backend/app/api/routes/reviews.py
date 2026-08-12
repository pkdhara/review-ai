"""
API routes — reviews.

POST /api/reviews/start
GET  /api/reviews
GET  /api/reviews/{id}
GET  /api/reviews/{id}/findings
GET  /api/reviews/{id}/summary
GET  /api/reviews/{id}/stream   (SSE)
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user_id, get_review_service
from app.db.database import get_db
from app.db.redis import stream_progress
from app.schemas.schemas import (
    FindingListResponse,
    PendingPrsResponse,
    ReviewListResponse,
    ReviewResponse,
    ReviewSummaryResponse,
    StartReviewRequest,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/reviews", tags=["Reviews"])


@router.post("/start", response_model=ReviewResponse, status_code=202)
async def start_review(
    body: StartReviewRequest,
    service: ReviewService = Depends(get_review_service),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Start an AI review of a Bitbucket pull request.
    Returns immediately with status=pending; poll /stream for live updates.
    """
    return await service.start_review(body, user_id)


@router.get("", response_model=ReviewListResponse)
async def list_reviews(
    page:      int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    service:   ReviewService = Depends(get_review_service),
    user_id:   uuid.UUID = Depends(get_current_user_id),
):
    """List all reviews for the current user, newest first."""
    return await service.list_reviews(user_id, page, page_size)


@router.get("/pending-prs", response_model=PendingPrsResponse)
async def get_pending_prs(
    only_internal_review: bool = Query(True),
    author_only: bool = Query(False),
    service: ReviewService = Depends(get_review_service),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Fetch open pull requests from Bitbucket available to review, filtered by Jira Internal Review status by default."""
    return await service.get_pending_prs(user_id, only_internal_review=only_internal_review, author_only=author_only)


@router.get("/{review_id}", response_model=ReviewResponse)
async def get_review(
    review_id: uuid.UUID,
    service:   ReviewService = Depends(get_review_service),
):
    """Get review status and metadata."""
    return await service.get_review(review_id)


@router.get("/{review_id}/findings", response_model=FindingListResponse)
async def get_findings(
    review_id:       uuid.UUID,
    severity:        Optional[str] = Query(None),
    category:        Optional[str] = Query(None),
    approval_status: Optional[str] = Query(None),
    page:            int = Query(1, ge=1),
    page_size:       int = Query(50, ge=1, le=200),
    service:         ReviewService = Depends(get_review_service),
):
    """Get AI-generated findings for a review, with optional filters."""
    return await service.get_findings(
        review_id, severity, category, approval_status, page, page_size
    )


@router.get("/{review_id}/summary", response_model=ReviewSummaryResponse)
async def get_summary(
    review_id: uuid.UUID,
    service:   ReviewService = Depends(get_review_service),
):
    """Get risk score, recommendation, and findings breakdown."""
    return await service.get_summary(review_id)


@router.post("/{review_id}/cancel", response_model=ReviewResponse)
async def cancel_review(
    review_id: uuid.UUID,
    service:   ReviewService = Depends(get_review_service),
):
    """Stop/cancel an ongoing PR review process."""
    return await service.cancel_review(review_id)


@router.delete("/{review_id}")
async def delete_review(
    review_id: uuid.UUID,
    service:   ReviewService = Depends(get_review_service),
):
    """Delete a review and remove it from review list."""
    return await service.delete_review(review_id)


@router.get("/{review_id}/stream")
async def stream_review_progress(review_id: uuid.UUID):
    """
    Server-Sent Events (SSE) endpoint.
    Subscribe to real-time agent progress for a running review.
    Each event: data: {"status", "current_agent", "progress_percent", "log?"}
    """
    return StreamingResponse(
        stream_progress(str(review_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",     # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )
