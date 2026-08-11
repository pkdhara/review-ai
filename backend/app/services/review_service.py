"""
Review Service — orchestrates the review lifecycle.
Starts the LangGraph workflow as an async background task.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionError
from app.core.logging import get_logger
from app.db.models.models import ApprovalStatus, Review, ReviewStatus
from app.db.redis import publish_progress
from app.db.repositories import (
    AgentExecutionRepository,
    FindingRepository,
    ReviewRepository,
    SettingsRepository,
)
from app.schemas.schemas import (
    BulkActionResponse,
    FindingListResponse,
    FindingResponse,
    PendingPrItem,
    PendingPrsResponse,
    PublishResponse,
    ReviewListResponse,
    ReviewResponse,
    ReviewSummaryResponse,
    StartReviewRequest,
)
from app.services.bitbucket_service import BitbucketService
from app.services.encryption_service import EncryptionService
from app.services.jira_service import JiraService

log = get_logger(__name__)


class ReviewService:
    _active_tasks: Dict[uuid.UUID, asyncio.Task] = {}

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.reviews = ReviewRepository(db)
        self.findings = FindingRepository(db)
        self.settings = SettingsRepository(db)
        self.agent_execs = AgentExecutionRepository(db)

    # ── Start ────────────────────────────────────────────────────────────────

    async def start_review(
        self, request: StartReviewRequest, user_id: uuid.UUID
    ) -> ReviewResponse:
        # Parse PR URL if provided
        workspace, repo_slug, pr_number = self._parse_pr_url(request)

        # Resolve settings
        cfg = await self.settings.get(user_id)
        if cfg is None:
            cfg = await self.settings.get()  # fall back to global

        enc = EncryptionService()
        bb_token = enc.decrypt(cfg.bitbucket_access_token) if cfg and cfg.bitbucket_access_token else None

        # Fetch PR metadata from Bitbucket
        bb = BitbucketService(
            workspace=workspace,
            access_token=bb_token or "",
            email=cfg.jira_email if cfg else None,
        )
        try:
            pr_meta = await bb.get_pull_request(workspace, repo_slug, pr_number)
        except Exception as exc:
            log.error("bitbucket.pr_fetch_failed", error=str(exc))
            pr_meta = {}

        jira_key = request.jira_key_override
        if not jira_key and pr_meta:
            source_branch = pr_meta.get("source", {}).get("branch", {}).get("name", "")
            title = pr_meta.get("title", "")
            jira_key = (
                BitbucketService.extract_jira_key(source_branch)
                or BitbucketService.extract_jira_key(title)
            )

        author_name = (
            pr_meta.get("author", {}).get("display_name")
            or pr_meta.get("author", {}).get("nickname")
            or (pr_meta.get("author", {}).get("user") or {}).get("display_name")
        )

        # Persist review record
        review = await self.reviews.create(
            user_id=user_id,
            pr_number=pr_number,
            pr_title=pr_meta.get("title"),
            pr_url=pr_meta.get("links", {}).get("html", {}).get("href"),
            source_branch=pr_meta.get("source", {}).get("branch", {}).get("name"),
            target_branch=pr_meta.get("destination", {}).get("branch", {}).get("name"),
            pr_author=author_name,
            jira_key=jira_key,
            status=ReviewStatus.pending,
        )
        await self.db.commit()

        log.info("review.created", review_id=str(review.id), pr_number=pr_number)

        # Fire-and-forget background workflow
        task = asyncio.create_task(
            self._run_workflow(
                review_id=review.id,
                workspace=workspace,
                repo_slug=repo_slug,
                pr_number=pr_number,
                jira_key=jira_key,
                bb_token=bb_token or "",
                cfg=cfg,
                enc=enc,
            )
        )
        ReviewService._active_tasks[review.id] = task

        return ReviewResponse.model_validate(review)

    # ── Workflow Execution ────────────────────────────────────────────────────

    async def _run_workflow(
        self,
        review_id: uuid.UUID,
        workspace: str,
        repo_slug: str,
        pr_number: int,
        jira_key: Optional[str],
        bb_token: str,
        cfg,
        enc: EncryptionService,
    ) -> None:
        from app.db.database import db_session
        from app.agents.workflow import ReviewWorkflow

        ReviewService._active_tasks[review_id] = asyncio.current_task()

        try:
            async with db_session() as db:
                reviews = ReviewRepository(db)
                findings_repo = FindingRepository(db)

                await reviews.update_status(
                    review_id, ReviewStatus.running,
                    current_agent="pr_fetch", progress_percent=5,
                )
                await db.commit()
                await self._emit(review_id, "running", "pr_fetch", 5)

                from app.core.config import settings as app_settings

                # Resolve AI provider and API key with fallback to global settings
                ai_provider = (cfg.ai_provider if cfg and cfg.ai_provider else None) or getattr(app_settings, "AI_PROVIDER", "gemini")
                if ai_provider in ("gemini", "google"):
                    ai_key = (enc.decrypt(cfg.gemini_api_key) if cfg and getattr(cfg, "gemini_api_key", None) else "") or getattr(app_settings, "GEMINI_API_KEY", "") or getattr(app_settings, "GOOGLE_API_KEY", "")
                elif ai_provider == "anthropic":
                    ai_key = (enc.decrypt(cfg.anthropic_api_key) if cfg and cfg.anthropic_api_key else "") or getattr(app_settings, "ANTHROPIC_API_KEY", "")
                else:
                    ai_key = (enc.decrypt(cfg.openai_api_key) if cfg and cfg.openai_api_key else "") or getattr(app_settings, "OPENAI_API_KEY", "")

                jira_token = enc.decrypt(cfg.jira_api_token) if cfg and cfg.jira_api_token else ""
                jira_url = cfg.jira_base_url if cfg else ""
                jira_email = cfg.jira_email if cfg else ""

                workflow = ReviewWorkflow(
                    review_id=str(review_id),
                    workspace=workspace,
                    repo_slug=repo_slug,
                    pr_number=pr_number,
                    jira_key=jira_key,
                    bitbucket_token=bb_token,
                    jira_base_url=jira_url,
                    jira_email=jira_email,
                    jira_token=jira_token,
                    ai_provider=ai_provider,
                    ai_key=ai_key,
                    progress_callback=lambda state: asyncio.ensure_future(
                        self._on_progress(
                            review_id,
                            state.get("current_agent"),
                            state.get("progress_percent", 0),
                            state.get("logs", [])[-1] if state.get("logs") else None,
                        )
                    ),
                )

                result = await workflow.execute()

                # Persist findings (even partial ones if some agents failed)
                raw_findings = result.get("findings", [])
                if raw_findings:
                    await findings_repo.bulk_create(raw_findings)

                # Check if any agents failed
                agent_errors = result.get("agent_errors") or {}
                final_status = ReviewStatus.failed if agent_errors else ReviewStatus.completed
                error_summary = (
                    "; ".join(f"{a}: {e}" for a, e in agent_errors.items())
                    if agent_errors else None
                )

                # Update final state
                summary = result.get("summary", {})
                severity_counts = self._count_by_severity(raw_findings)
                await reviews.update_results(
                    review_id,
                    status=final_status,
                    progress_percent=100,
                    current_agent=None,
                    risk_score=summary.get("risk_score"),
                    overall_recommendation=summary.get("overall_recommendation"),
                    executive_summary=summary.get("executive_summary"),
                    total_findings=len(raw_findings),
                    completed_at=datetime.utcnow(),
                    error_message=error_summary,
                    **severity_counts,
                )
                await db.commit()

                if agent_errors:
                    log.warning("review.completed_with_errors", review_id=str(review_id), findings=len(raw_findings), agent_errors=agent_errors)
                    await self._emit(review_id, "failed", None, 100, summary=summary, error=error_summary)
                else:
                    await self._emit(review_id, "completed", None, 100, summary=summary)
                    log.info("review.completed", review_id=str(review_id), findings=len(raw_findings))

        except asyncio.CancelledError:
            log.info("review.cancelled", review_id=str(review_id))
            try:
                async with db_session() as db:
                    reviews = ReviewRepository(db)
                    await reviews.update_status(
                        review_id,
                        ReviewStatus.cancelled,
                        current_agent=None,
                        progress_percent=0,
                        error_message="Review cancelled by user",
                    )
                    await db.commit()
            except Exception as exc:
                log.warning("review.cancel_db_update_failed", review_id=str(review_id), error=str(exc))
            await self._emit(review_id, "cancelled", None, 0, error="Review cancelled by user")
        except Exception as exc:
            log.error("review.workflow_failed", review_id=str(review_id), error=str(exc))
            try:
                async with db_session() as db:
                    reviews = ReviewRepository(db)
                    await reviews.update_status(
                        review_id, ReviewStatus.failed,
                        error_message=str(exc),
                    )
                    await db.commit()
            except Exception:
                pass
            await self._emit(review_id, "failed", None, 0, error=str(exc))
        finally:
            ReviewService._active_tasks.pop(review_id, None)

    async def cancel_review(self, review_id: uuid.UUID) -> ReviewResponse:
        review = await self._assert_review_exists(review_id)

        # Cancel active background task if running
        task = ReviewService._active_tasks.get(review_id)
        if task and not task.done():
            task.cancel()

        await self.reviews.update_status(
            review_id,
            ReviewStatus.cancelled,
            current_agent=None,
            progress_percent=0,
            error_message="Review cancelled by user",
        )
        await self.db.commit()

        # Clean up git worktree if exists
        try:
            from app.services.git_worktree_service import git_worktree_manager
            _, repo_slug = self._extract_repo(review)
            await git_worktree_manager.cleanup_worktree(repo_slug, str(review_id))
        except Exception as exc:
            log.warning("review.worktree_cleanup_failed", review_id=str(review_id), error=str(exc))

        await self._emit(review_id, "cancelled", None, 0, error="Review cancelled by user")
        log.info("review.cancelled_by_user", review_id=str(review_id))

        updated_review = await self.reviews.get_by_id(review_id)
        return ReviewResponse.model_validate(updated_review)

    async def delete_review(self, review_id: uuid.UUID) -> Dict[str, Any]:
        review = await self._assert_review_exists(review_id)

        if review.status in (ReviewStatus.running, ReviewStatus.pending):
            try:
                await self.cancel_review(review_id)
            except Exception as exc:
                log.warning("review.cancel_before_delete_failed", review_id=str(review_id), error=str(exc))

        success = await self.reviews.delete(review_id)
        await self.db.commit()

        if not success:
            raise NotFoundError("Review", str(review_id))

        log.info("review.deleted", review_id=str(review_id))
        return {"message": "Review deleted successfully", "id": str(review_id)}

    async def _on_progress(
        self, review_id: uuid.UUID, agent: Optional[str], pct: int, log_entry: Optional[dict] = None
    ) -> None:
        from app.db.database import db_session
        try:
            async with db_session() as session:
                reviews = ReviewRepository(session)
                await reviews.update_status(review_id, ReviewStatus.running, current_agent=agent, progress_percent=pct)
                await session.commit()
        except Exception as exc:
            log.warning("review.progress_update_failed", review_id=str(review_id), error=str(exc))
        await self._emit(review_id, "running", agent, pct, log=log_entry)

    async def _emit(
        self,
        review_id: uuid.UUID,
        status: str,
        agent: Optional[str],
        pct: int,
        log: Optional[dict] = None,
        summary: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        payload: dict = {
            "review_id": str(review_id),
            "status": status,
            "current_agent": agent,
            "progress_percent": pct,
        }
        if log:
            payload["log"] = log
        if summary:
            payload["summary"] = summary
        if error:
            payload["error"] = error
        try:
            await publish_progress(str(review_id), payload)
        except Exception:
            pass  # non-critical

    # ── Query ────────────────────────────────────────────────────────────────

    async def get_review(self, review_id: uuid.UUID) -> ReviewResponse:
        review = await self.reviews.get_by_id(review_id)
        if not review:
            raise NotFoundError("Review", str(review_id))
        return ReviewResponse.model_validate(review)

    async def list_reviews(
        self, user_id: uuid.UUID, page: int = 1, page_size: int = 20
    ) -> ReviewListResponse:
        items, total = await self.reviews.list_reviews(user_id, page, page_size)
        return ReviewListResponse(
            items=[ReviewResponse.model_validate(r) for r in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_findings(
        self,
        review_id: uuid.UUID,
        severity: Optional[str] = None,
        category: Optional[str] = None,
        approval_status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> FindingListResponse:
        await self._assert_review_exists(review_id)
        items, total = await self.findings.list_by_review(
            review_id, severity, category, approval_status, page, page_size
        )
        return FindingListResponse(
            items=[FindingResponse.model_validate(f) for f in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def get_summary(self, review_id: uuid.UUID) -> ReviewSummaryResponse:
        from sqlalchemy import select, func
        from app.db.models.models import ReviewFinding, AgentExecution
        review = await self.reviews.get_by_id(review_id)
        if not review:
            raise NotFoundError("Review", str(review_id))

        # Severity breakdown
        sev_q = await self.db.execute(
            select(ReviewFinding.severity, func.count().label("cnt"))
            .where(ReviewFinding.review_id == review_id, ReviewFinding.deleted_at.is_(None))
            .group_by(ReviewFinding.severity)
        )
        by_severity = {row.severity: row.cnt for row in sev_q}

        # Category breakdown
        cat_q = await self.db.execute(
            select(ReviewFinding.category, func.count().label("cnt"))
            .where(ReviewFinding.review_id == review_id, ReviewFinding.deleted_at.is_(None))
            .group_by(ReviewFinding.category)
        )
        by_category = {row.category: row.cnt for row in cat_q}

        # Fallback: re-derive risk_score and recommendation from live findings if DB values are null
        stored_risk = float(review.risk_score) if review.risk_score is not None else None
        if stored_risk is None:
            _weights = {"critical": 25, "high": 10, "medium": 4, "low": 1, "info": 0}
            stored_risk = min(100.0, round(
                sum(_weights.get(sev, 0) * cnt for sev, cnt in by_severity.items()), 1
            ))

        stored_rec = review.overall_recommendation
        # Enforce deterministic override if DB has an incorrect APPROVE
        if by_severity.get("critical", 0) > 0 or by_severity.get("high", 0) > 0:
            if stored_rec != "REQUEST_CHANGES":
                stored_rec = "REQUEST_CHANGES"
        elif by_severity.get("medium", 0) > 0:
            if stored_rec == "APPROVE":
                stored_rec = "NEEDS_DISCUSSION"

        from app.schemas.schemas import AgentExecutionResponse
        return ReviewSummaryResponse(
            review_id=review_id,
            risk_score=stored_risk,
            overall_recommendation=stored_rec,
            executive_summary=review.executive_summary,
            total_findings=review.total_findings or sum(by_severity.values()),
            findings_by_severity=by_severity,
            findings_by_category=by_category,
            agent_executions=[AgentExecutionResponse.model_validate(e) for e in review.agent_executions],
        )

    # ── Approval ──────────────────────────────────────────────────────────────

    async def approve_comments(
        self, finding_ids: list[uuid.UUID], approved_by: str
    ) -> BulkActionResponse:
        affected = await self.findings.approve(finding_ids, approved_by)
        log.info("comments.approved", count=affected, by=approved_by)
        return BulkActionResponse(affected=affected, message=f"{affected} comment(s) approved.")

    async def reject_comments(
        self, finding_ids: list[uuid.UUID], reason: Optional[str]
    ) -> BulkActionResponse:
        affected = await self.findings.reject(finding_ids, reason)
        return BulkActionResponse(affected=affected, message=f"{affected} comment(s) rejected.")

    async def update_comment(
        self, finding_id: uuid.UUID, edited_comment: str
    ) -> FindingResponse:
        await self.findings.update_comment(finding_id, edited_comment)
        f = await self.findings.get_by_id(finding_id)
        if not f:
            raise NotFoundError("Finding", str(finding_id))
        return FindingResponse.model_validate(f)

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish_comments(
        self,
        finding_ids: list[uuid.UUID],
        user_id: uuid.UUID,
    ) -> PublishResponse:
        findings = await self.findings.get_by_ids(finding_ids)
        cfg = await self.settings.get(user_id) or await self.settings.get()
        enc = EncryptionService()
        bb_token = enc.decrypt(cfg.bitbucket_access_token) if cfg and cfg.bitbucket_access_token else ""

        published, failed, errors = 0, 0, []

        for f in findings:
            if f.approval_status != ApprovalStatus.approved:
                errors.append(f"Finding {f.id}: not approved — skipped.")
                failed += 1
                continue
            if f.published:
                errors.append(f"Finding {f.id}: already published.")
                failed += 1
                continue

            # Resolve review metadata for posting inline comment
            review = await self.reviews.get_by_id(f.review_id)
            if not review:
                failed += 1
                continue

            comment_text = f.edited_comment or f.review_comment

            try:
                # Extract workspace/slug from PR URL or review metadata
                workspace, repo_slug = self._extract_repo(review)
                bb = BitbucketService(workspace=workspace, access_token=bb_token, email=cfg.jira_email if cfg else None)
                result = await bb.post_pr_comment(
                    workspace=workspace,
                    repo_slug=repo_slug,
                    pr_number=review.pr_number,
                    comment_text=comment_text,
                    file_path=f.file_path,
                    line=f.line_number,
                )
                comment_id = result.get("id")
                await self.findings.mark_published(f.id, str(comment_id))
                published += 1
                log.info("comment.published", finding_id=str(f.id), comment_id=comment_id)
            except Exception as exc:
                errors.append(f"Finding {f.id}: {exc}")
                failed += 1
                log.error("comment.publish_failed", finding_id=str(f.id), error=str(exc))

        return PublishResponse(
            published_count=published,
            failed_count=failed,
            message=f"Published {published}, failed {failed}.",
            errors=errors,
        )

    # ── Pending PRs ───────────────────────────────────────────────────────────

    async def get_pending_prs(
        self,
        user_id: uuid.UUID,
        only_internal_review: bool = True,
    ) -> PendingPrsResponse:
        cfg = await self.settings.get(user_id)
        if not cfg:
            cfg = await self.settings.get()

        enc = EncryptionService()
        bb_token = enc.decrypt(cfg.bitbucket_access_token) if cfg and cfg.bitbucket_access_token else ""
        jira_token = enc.decrypt(cfg.jira_api_token) if cfg and cfg.jira_api_token else ""
        workspace = (cfg.bitbucket_workspace if cfg and cfg.bitbucket_workspace else "") or "freshconcepts"

        bb = BitbucketService(
            workspace=workspace,
            access_token=bb_token,
            email=cfg.jira_email if cfg else None,
        )

        base_jira_url = (cfg.jira_base_url if cfg and cfg.jira_base_url else "") or "https://freshconcepts.atlassian.net"
        if base_jira_url and not base_jira_url.startswith("http"):
            base_jira_url = f"https://{base_jira_url}"

        jira_service = None
        if jira_token and cfg and cfg.jira_email:
            try:
                jira_service = JiraService(
                    base_url=base_jira_url,
                    email=cfg.jira_email,
                    api_token=jira_token,
                )
            except Exception as exc:
                log.warning("jira.init_failed_in_pending_prs", error=str(exc))

        items: list[PendingPrItem] = []
        try:
            prs_data = await bb._get(f"/repositories/{workspace}/fc-angular/pullrequests", params={"state": "OPEN"})
            prs = prs_data.get("values", [])

            db_reviews, _ = await self.reviews.list_reviews(page=1, page_size=100)
            existing_by_pr = {r.pr_number: r for r in db_reviews if r.pr_number}

            for pr in prs:
                pr_num = pr.get("id")
                title = pr.get("title", "")
                source_branch = pr.get("source", {}).get("branch", {}).get("name", "")
                target_branch = pr.get("destination", {}).get("branch", {}).get("name", "")
                pr_url = pr.get("links", {}).get("html", {}).get("href", "")

                author_data = pr.get("author", {})
                author_name = (
                    author_data.get("display_name")
                    or author_data.get("nickname")
                    or (author_data.get("user") or {}).get("display_name")
                )

                jira_key = (
                    BitbucketService.extract_jira_key(source_branch)
                    or BitbucketService.extract_jira_key(title)
                )
                jira_url = f"{base_jira_url.rstrip('/')}/browse/{jira_key}" if jira_key else None
                existing = existing_by_pr.get(pr_num)

                jira_status = None
                if jira_key and jira_service:
                    try:
                        issue = await jira_service.get_issue(jira_key)
                        jira_status = (issue.get("fields") or {}).get("status", {}).get("name")
                    except Exception as e:
                        log.debug("jira.fetch_status_failed", key=jira_key, error=str(e))

                # Filter by Internal Review status if requested
                if only_internal_review:
                    if not jira_status:
                        continue
                    normalized_status = jira_status.lower().strip()
                    if "internal review" not in normalized_status and "in review" not in normalized_status:
                        continue

                items.append(
                    PendingPrItem(
                        pr_number=pr_num,
                        pr_title=title,
                        pr_url=pr_url,
                        pr_author=author_name,
                        source_branch=source_branch,
                        target_branch=target_branch,
                        jira_key=jira_key,
                        jira_url=jira_url,
                        jira_status=jira_status,
                        workspace=workspace,
                        repo_slug="fc-angular",
                        created_on=pr.get("created_on"),
                        updated_on=pr.get("updated_on"),
                        existing_review_id=str(existing.id) if existing else None,
                        existing_review_status=existing.status.value if existing else None,
                    )
                )
        except Exception as exc:
            log.error("bitbucket.fetch_pending_prs_failed", error=str(exc))

        return PendingPrsResponse(items=items, total=len(items))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _assert_review_exists(self, review_id: uuid.UUID) -> Review:
        r = await self.reviews.get_by_id(review_id)
        if not r:
            raise NotFoundError("Review", str(review_id))
        return r

    @staticmethod
    def _parse_pr_url(request: StartReviewRequest) -> tuple[str, str, int]:
        if request.pr_url:
            # https://bitbucket.org/{workspace}/{repo}/pull-requests/{number}
            parts = request.pr_url.rstrip("/").split("/")
            try:
                pr_idx = parts.index("pull-requests")
                return parts[pr_idx - 2], parts[pr_idx - 1], int(parts[pr_idx + 1])
            except (ValueError, IndexError):
                raise ConflictError(f"Cannot parse PR URL: {request.pr_url}")
        return (
            request.bitbucket_workspace,
            request.bitbucket_repo_slug,
            request.pr_number,
        )

    @staticmethod
    def _extract_repo(review: Review) -> tuple[str, str]:
        if review.pr_url:
            parts = review.pr_url.rstrip("/").split("/")
            try:
                idx = parts.index("pull-requests")
                return parts[idx - 2], parts[idx - 1]
            except (ValueError, IndexError):
                pass
        return "", ""

    @staticmethod
    def _count_by_severity(findings: list[dict]) -> dict:
        counts: dict = {"critical_count": 0, "high_count": 0, "medium_count": 0, "low_count": 0}
        for f in findings:
            sev = f.get("severity", "")
            if sev in counts:
                counts[f"{sev}_count"] = counts.get(f"{sev}_count", 0) + 1
        return counts
