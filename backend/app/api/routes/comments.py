"""
API routes — comments (approve / reject / edit / publish).

PUT  /api/comments/{id}
POST /api/comments/approve
POST /api/comments/reject
POST /api/comments/publish
"""
import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user_id, get_review_service
from app.schemas.schemas import (
    ApproveCommentsRequest,
    BulkActionResponse,
    FindingResponse,
    PublishRequest,
    PublishResponse,
    RejectCommentsRequest,
    UpdateCommentRequest,
)
from app.services.review_service import ReviewService

router = APIRouter(prefix="/comments", tags=["Comments"])


@router.put("/{finding_id}", response_model=FindingResponse)
async def update_comment(
    finding_id: uuid.UUID,
    body:       UpdateCommentRequest,
    service:    ReviewService = Depends(get_review_service),
):
    """Edit the text of an AI-generated comment before approving."""
    return await service.update_comment(finding_id, body.edited_comment)


@router.post("/approve", response_model=BulkActionResponse)
async def approve_comments(
    body:    ApproveCommentsRequest,
    service: ReviewService = Depends(get_review_service),
):
    """
    Approve a batch of findings for publication.
    Human-in-the-loop gate — nothing reaches Bitbucket without approval.
    """
    return await service.approve_comments(body.finding_ids, body.approved_by)


@router.post("/reject", response_model=BulkActionResponse)
async def reject_comments(
    body:    RejectCommentsRequest,
    service: ReviewService = Depends(get_review_service),
):
    """Reject findings — they will be excluded from publication."""
    return await service.reject_comments(body.finding_ids, body.rejection_reason)


@router.post("/publish", response_model=PublishResponse)
async def publish_comments(
    body:    PublishRequest,
    service: ReviewService = Depends(get_review_service),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """
    Publish approved findings as inline comments on the Bitbucket PR.
    Only findings with approval_status='approved' are posted.
    """
    return await service.publish_comments(body.finding_ids, user_id)
