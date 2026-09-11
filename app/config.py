"""
Application configuration loaded from environment variables / .env file.

Uses pydantic-settings so every value is validated at startup. If a required
var is missing, the app crashes immediately with a clear error rather than
failing mysteriously later.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/rethink"
    )

    # ── Codeforces API ────────────────────────────────────────────────────
    cf_api_base_url: str = "https://codeforces.com/api"
    cf_requests_per_second: float = 2.0

    # ── Sync ──────────────────────────────────────────────────────────────
    sync_lease_minutes: int = 15
    sync_page_size: int = 100

    # ── LLM Settings ──────────────────────────────────────────────────────
    llm_provider: str = "mock"  # "mock" | "gemini" | "openai"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-1.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"


# Singleton — import this everywhere
settings = Settings()
