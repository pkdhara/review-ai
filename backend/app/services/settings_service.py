"""
Settings service — stores credentials encrypted at rest.
"""

from typing import Any, Dict, Optional

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models.models import UserSettings

logger = get_logger(__name__)


def _get_fernet() -> Optional[Fernet]:
    key = settings.encryption_key
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        return None


def _encrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    f = _get_fernet()
    if not f:
        return value  # No encryption configured — store raw
    return f.encrypt(value.encode()).decode()


def _decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    f = _get_fernet()
    if not f:
        return value
    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        return None


class SettingsService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_settings(self, user_id: Optional[str]) -> Optional[UserSettings]:
        if not user_id:
            return None
        stmt = select(UserSettings).where(UserSettings.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_decrypted_settings(self, user_id: Optional[str]) -> Dict[str, Any]:
        """Return decrypted settings dict for use by agents."""
        s = await self.get_settings(user_id)
        if not s:
            # Fall back to env settings
            return {
                "bitbucket_access_token": settings.bitbucket_access_token,
                "bitbucket_workspace": settings.bitbucket_workspace,
                "jira_base_url": settings.jira_base_url,
                "jira_email": settings.jira_email,
                "jira_api_token": settings.jira_api_token,
                "openai_api_key": settings.openai_api_key,
                "anthropic_api_key": settings.anthropic_api_key,
                "gemini_api_key": settings.gemini_api_key or settings.google_api_key,
                "ai_provider": settings.ai_provider or "gemini",
            }
        return {
            "bitbucket_access_token": _decrypt(s.bitbucket_access_token),
            "bitbucket_workspace": s.bitbucket_workspace,
            "jira_base_url": s.jira_base_url,
            "jira_email": s.jira_email,
            "jira_api_token": _decrypt(s.jira_api_token),
            "openai_api_key": _decrypt(s.openai_api_key),
            "anthropic_api_key": _decrypt(s.anthropic_api_key),
            "gemini_api_key": _decrypt(getattr(s, "gemini_api_key", None)),
            "ai_provider": s.ai_provider or "gemini",
        }

    async def upsert_settings(self, user_id: str, data: Dict[str, Any]) -> UserSettings:
        s = await self.get_settings(user_id)
        if not s:
            s = UserSettings(user_id=user_id)
            self.db.add(s)

        if "bitbucket_access_token" in data:
            s.bitbucket_access_token = _encrypt(data["bitbucket_access_token"])
        if "bitbucket_workspace" in data:
            s.bitbucket_workspace = data["bitbucket_workspace"]
        if "jira_base_url" in data:
            s.jira_base_url = data["jira_base_url"]
        if "jira_email" in data:
            s.jira_email = data["jira_email"]
        if "jira_api_token" in data:
            s.jira_api_token = _encrypt(data["jira_api_token"])
        if "openai_api_key" in data:
            s.openai_api_key = _encrypt(data["openai_api_key"])
        if "anthropic_api_key" in data:
            s.anthropic_api_key = _encrypt(data["anthropic_api_key"])
        if "gemini_api_key" in data and hasattr(s, "gemini_api_key"):
            s.gemini_api_key = _encrypt(data["gemini_api_key"])
        if "ai_provider" in data:
            s.ai_provider = data["ai_provider"]

        await self.db.commit()
        return s
