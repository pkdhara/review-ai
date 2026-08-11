"""
Configuration — reads from environment / .env file via Pydantic Settings v2.
"""
from functools import lru_cache
from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    APP_ENV:        str  = Field(default="development")
    APP_NAME:       str  = Field(default="ReviewAI")
    APP_VERSION:    str  = Field(default="1.0.0")
    APP_SECRET_KEY: str  = Field(default="change-me-in-production")
    APP_PORT:       int  = Field(default=8000)
    DEBUG:          bool = Field(default=False)

    # CORS
    ALLOWED_ORIGINS: list[str] | str = Field(
        default=["http://localhost:4200", "http://localhost"]
    )

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def parse_allowed_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            if v.startswith("["):
                import json
                return json.loads(v)
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://reviewai:reviewai_pass@localhost:5432/reviewai"
    )
    DATABASE_POOL_SIZE:     int = Field(default=10)
    DATABASE_MAX_OVERFLOW:  int = Field(default=20)
    DATABASE_POOL_TIMEOUT:  int = Field(default=30)

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # AI
    AI_PROVIDER:       str = Field(default="gemini")
    ANTHROPIC_API_KEY: str = Field(default="")
    OPENAI_API_KEY:    str = Field(default="")
    GEMINI_API_KEY:    str = Field(default="")
    GOOGLE_API_KEY:    str = Field(default="")
    OPENAI_MODEL:      str = Field(default="gpt-4o")
    ANTHROPIC_MODEL:   str = Field(default="claude-3-5-sonnet-20241022")
    GEMINI_MODEL:      str = Field(default="gemini-3.5-flash")

    # Integrations
    BITBUCKET_USERNAME:     str = Field(default="")
    BITBUCKET_ACCESS_TOKEN: str = Field(default="")
    JIRA_BASE_URL:          str = Field(default="")
    JIRA_EMAIL:             str = Field(default="")
    JIRA_API_TOKEN:         str = Field(default="")

    # Security — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = Field(default="")

    # Agent tuning
    AGENT_TIMEOUT_SECONDS:  int = Field(default=120)
    MAX_CONCURRENT_REVIEWS: int = Field(default=5)

    # Local Repo & Worktree Configuration
    LOCAL_REPO_BASE_DIR: str = Field(default="/home/pradeep/fc")
    WORKTREE_BASE_DIR:   str = Field(default="/tmp/reviewai/worktrees")

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def resolve_repo_path(self, repo_slug: str) -> str | None:
        """
        Resolves the local repository filesystem path for a given repo slug.
        Checks:
        1. Environment variables (e.g., ANGULAR_REPO, angular_repo, JSP_REPO, etc.)
        2. Exact subfolder inside LOCAL_REPO_BASE_DIR
        3. Common local fallback paths (/home/pradeep/fc/<repo_slug>)
        """
        import os
        from pathlib import Path

        if not repo_slug:
            return None

        slug_clean = repo_slug.strip().lower()

        # Check explicit env variable mappings (e.g. angular_repo, jsp_repo, fc-angular, etc.)
        env_candidates = [
            f"{slug_clean.replace('-', '_')}_repo",
            f"{slug_clean.replace('-', '_')}",
            f"{slug_clean}_repo",
            f"{slug_clean}",
            "angular_repo" if "angular" in slug_clean else None,
            "jsp_repo" if "freshconcepts" in slug_clean and "integration" not in slug_clean else None,
            "integration_repo" if "integration" in slug_clean else None,
            "mobile_repo" if "mobile" in slug_clean else None,
        ]

        # Check under LOCAL_REPO_BASE_DIR first (supports isolated test settings)
        base_dir = Path(self.LOCAL_REPO_BASE_DIR)
        candidate = base_dir / repo_slug
        if candidate.exists():
            return str(candidate.resolve())

        for env_key in env_candidates:
            if not env_key:
                continue
            val = os.getenv(env_key) or os.getenv(env_key.upper()) or os.getenv(env_key.lower())
            if val and Path(val).exists():
                return str(Path(val).resolve())

        # Build dynamic known_mappings from environment variables / .env settings
        known_mappings = {
            "fc-angular": os.getenv("angular_repo") or os.getenv("ANGULAR_REPO") or str(base_dir / "fc-angular"),
            "freshconcepts": os.getenv("jsp_repo") or os.getenv("JSP_REPO") or str(base_dir / "freshconcepts"),
            "freshconcepts-integration": os.getenv("integration_repo") or os.getenv("INTEGRATION_REPO") or str(base_dir / "freshconcepts-integration"),
            "fc-mobile-app": os.getenv("mobile_repo") or os.getenv("MOBILE_REPO") or str(base_dir / "fc-mobile-app"),
        }
        if repo_slug in known_mappings:
            path_val = known_mappings[repo_slug]
            if path_val and Path(path_val).exists():
                return str(Path(path_val).resolve())

        return None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
