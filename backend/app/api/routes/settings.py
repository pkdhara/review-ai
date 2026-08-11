"""
Settings routes.

GET /api/settings
PUT /api/settings
"""
import uuid

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user_id
from app.db.database import get_db
from app.db.repositories import SettingsRepository
from app.schemas.schemas import SettingsResponse, SettingsUpdateRequest
from app.services.encryption_service import EncryptionService
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db:      AsyncSession = Depends(get_db),
):
    repo = SettingsRepository(db)
    cfg = await repo.get(user_id) or await repo.get()
    if cfg is None:
        return SettingsResponse(
            bitbucket_workspace=None, jira_base_url=None, jira_email=None,
            ai_provider="gemini", max_findings_per_agent=10,
            agent_timeout_seconds=120,
            has_bitbucket_token=False, has_jira_token=False,
            has_anthropic_key=False, has_openai_key=False,
            has_gemini_key=False,
        )
    return SettingsResponse(
        bitbucket_workspace=cfg.bitbucket_workspace,
        jira_base_url=cfg.jira_base_url,
        jira_email=cfg.jira_email,
        ai_provider=cfg.ai_provider or "gemini",
        max_findings_per_agent=cfg.max_findings_per_agent or 10,
        agent_timeout_seconds=cfg.agent_timeout_seconds or 120,
        has_bitbucket_token=bool(cfg.bitbucket_access_token),
        has_jira_token=bool(cfg.jira_api_token),
        has_anthropic_key=bool(cfg.anthropic_api_key),
        has_openai_key=bool(cfg.openai_api_key),
        has_gemini_key=bool(getattr(cfg, "gemini_api_key", None)),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    body:    SettingsUpdateRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db:      AsyncSession = Depends(get_db),
):
    enc = EncryptionService()
    repo = SettingsRepository(db)

    updates: dict = {}
    if body.bitbucket_workspace is not None:
        updates["bitbucket_workspace"] = body.bitbucket_workspace
    if body.bitbucket_access_token:
        updates["bitbucket_access_token"] = enc.encrypt(body.bitbucket_access_token)
    if body.jira_base_url is not None:
        updates["jira_base_url"] = body.jira_base_url
    if body.jira_email is not None:
        updates["jira_email"] = body.jira_email
    if body.jira_api_token:
        updates["jira_api_token"] = enc.encrypt(body.jira_api_token)
    if body.ai_provider is not None:
        updates["ai_provider"] = body.ai_provider
    if body.anthropic_api_key:
        updates["anthropic_api_key"] = enc.encrypt(body.anthropic_api_key)
    if body.openai_api_key:
        updates["openai_api_key"] = enc.encrypt(body.openai_api_key)
    if body.gemini_api_key and hasattr(repo.model_class, "gemini_api_key"):
        updates["gemini_api_key"] = enc.encrypt(body.gemini_api_key)
    if body.max_findings_per_agent is not None:
        updates["max_findings_per_agent"] = body.max_findings_per_agent
    if body.agent_timeout_seconds is not None:
        updates["agent_timeout_seconds"] = body.agent_timeout_seconds

    cfg = await repo.upsert(user_id, **updates)
    return SettingsResponse(
        bitbucket_workspace=cfg.bitbucket_workspace,
        jira_base_url=cfg.jira_base_url,
        jira_email=cfg.jira_email,
        ai_provider=cfg.ai_provider or "gemini",
        max_findings_per_agent=cfg.max_findings_per_agent or 10,
        agent_timeout_seconds=cfg.agent_timeout_seconds or 120,
        has_bitbucket_token=bool(cfg.bitbucket_access_token),
        has_jira_token=bool(cfg.jira_api_token),
        has_anthropic_key=bool(cfg.anthropic_api_key),
        has_openai_key=bool(cfg.openai_api_key),
        has_gemini_key=bool(getattr(cfg, "gemini_api_key", None)),
    )
