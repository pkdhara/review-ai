"""Repository layer — all DB access isolated here. No business logic."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.models import (
    AgentExecution,
    ApprovalStatus,
    Review,
    ReviewFinding,
    ReviewStatus,
    SystemSettings,
)


# ── Review Repository ────────────────────────────────────────────────────────

class ReviewRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, **kwargs) -> Review:
        review = Review(**kwargs)
        self.db.add(review)
        await self.db.flush()
        await self.db.refresh(review)
        return review

    async def get_by_id(self, review_id: uuid.UUID) -> Optional[Review]:
        result = await self.db.execute(
            select(Review)
            .where(Review.id == review_id, Review.deleted_at.is_(None))
            .options(selectinload(Review.agent_executions))
        )
        return result.scalar_one_or_none()

    async def list_reviews(
        self,
        user_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Review], int]:
        base_q = select(Review).where(Review.deleted_at.is_(None))
        if user_id:
            base_q = base_q.where(Review.user_id == user_id)

        count_result = await self.db.execute(
            select(func.count()).select_from(base_q.subquery())
        )
        total = count_result.scalar_one()

        result = await self.db.execute(
            base_q.order_by(Review.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), total

    async def update_status(
        self,
        review_id: uuid.UUID,
        status: ReviewStatus,
        current_agent: Optional[str] = None,
        progress_percent: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        values: dict = {"status": status}
        if current_agent is not None:
            values["current_agent"] = current_agent
        if progress_percent is not None:
            values["progress_percent"] = progress_percent
        if error_message is not None:
            values["error_message"] = error_message
        await self.db.execute(
            update(Review).where(Review.id == review_id).values(**values)
        )

    async def update_results(self, review_id: uuid.UUID, **kwargs) -> None:
        await self.db.execute(
            update(Review).where(Review.id == review_id).values(**kwargs)
        )

    async def delete(self, review_id: uuid.UUID) -> bool:
        from datetime import datetime
        result = await self.db.execute(
            update(Review)
            .where(Review.id == review_id, Review.deleted_at.is_(None))
            .values(deleted_at=datetime.utcnow())
        )
        return result.rowcount > 0


# ── Finding Repository ────────────────────────────────────────────────────────

class FindingRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def bulk_create(self, findings: list[dict]) -> list[ReviewFinding]:
        objs = [ReviewFinding(**f) for f in findings]
        self.db.add_all(objs)
        await self.db.flush()
        return objs

    async def get_by_id(self, finding_id: uuid.UUID) -> Optional[ReviewFinding]:
        result = await self.db.execute(
            select(ReviewFinding).where(
                ReviewFinding.id == finding_id,
                ReviewFinding.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_review(
        self,
        review_id: uuid.UUID,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        approval_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[ReviewFinding], int]:
        base_q = select(ReviewFinding).where(
            ReviewFinding.review_id == review_id,
            ReviewFinding.deleted_at.is_(None),
        )
        if severity:
            base_q = base_q.where(ReviewFinding.severity == severity)
        if category:
            base_q = base_q.where(ReviewFinding.category == category)
        if approval_status:
            base_q = base_q.where(ReviewFinding.approval_status == approval_status)

        count = await self.db.scalar(select(func.count()).select_from(base_q.subquery()))
        result = await self.db.execute(
            base_q.order_by(ReviewFinding.severity, ReviewFinding.created_at)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), count or 0

    async def get_by_ids(self, finding_ids: list[uuid.UUID]) -> list[ReviewFinding]:
        result = await self.db.execute(
            select(ReviewFinding).where(
                ReviewFinding.id.in_(finding_ids),
                ReviewFinding.deleted_at.is_(None),
            )
        )
        return result.scalars().all()

    async def approve(self, finding_ids: list[uuid.UUID], approved_by: str) -> int:
        from datetime import datetime, timezone
        result = await self.db.execute(
            update(ReviewFinding)
            .where(
                ReviewFinding.id.in_(finding_ids),
                ReviewFinding.deleted_at.is_(None),
            )
            .values(
                approval_status=ApprovalStatus.approved,
                approved_by=approved_by,
                approved_at=datetime.utcnow(),
            )
        )
        return result.rowcount

    async def reject(
        self, finding_ids: list[uuid.UUID], reason: Optional[str] = None
    ) -> int:
        result = await self.db.execute(
            update(ReviewFinding)
            .where(
                ReviewFinding.id.in_(finding_ids),
                ReviewFinding.deleted_at.is_(None),
            )
            .values(
                approval_status=ApprovalStatus.rejected,
                rejection_reason=reason,
            )
        )
        return result.rowcount

    async def mark_published(
        self, finding_id: uuid.UUID, bitbucket_comment_id: str
    ) -> None:
        from datetime import datetime, timezone
        await self.db.execute(
            update(ReviewFinding)
            .where(ReviewFinding.id == finding_id)
            .values(
                published=True,
                published_at=datetime.utcnow(),
                bitbucket_comment_id=bitbucket_comment_id,
            )
        )

    async def update_comment(self, finding_id: uuid.UUID, edited_comment: str) -> None:
        await self.db.execute(
            update(ReviewFinding)
            .where(ReviewFinding.id == finding_id)
            .values(edited_comment=edited_comment)
        )


# ── Settings Repository ───────────────────────────────────────────────────────

class SettingsRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, user_id: Optional[uuid.UUID] = None) -> Optional[SystemSettings]:
        q = select(SystemSettings)
        if user_id:
            q = q.where(SystemSettings.user_id == user_id)
        else:
            q = q.where(SystemSettings.user_id.is_(None), SystemSettings.project_id.is_(None))
        result = await self.db.execute(q)
        return result.scalar_one_or_none()

    async def upsert(self, user_id: Optional[uuid.UUID], **kwargs) -> SystemSettings:
        existing = await self.get(user_id)
        if existing:
            for k, v in kwargs.items():
                if v is not None:
                    setattr(existing, k, v)
            await self.db.flush()
            return existing
        obj = SystemSettings(user_id=user_id, **kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj


# ── Agent Execution Repository ────────────────────────────────────────────────

class AgentExecutionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create(self, **kwargs) -> AgentExecution:
        obj = AgentExecution(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def update(self, exec_id: uuid.UUID, **kwargs) -> None:
        await self.db.execute(
            update(AgentExecution)
            .where(AgentExecution.id == exec_id)
            .values(**kwargs)
        )
