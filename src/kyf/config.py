"""Application configuration loaded from environment variables with Pydantic validation."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Moltbook API
    moltbook_api_key: SecretStr
    moltbook_base_url: str = "https://www.moltbook.com/api/v1"

    # Groq
    groq_api_key: SecretStr
    groq_model: str = "llama-3.3-70b-versatile"

    # Agent behavior
    heartbeat_interval_hours: int = Field(default=4, ge=1, le=24)
    max_posts_per_day: int = Field(default=3, ge=1, le=10)
    max_comments_per_heartbeat: int = Field(default=10, ge=1, le=50)
    max_replies_per_heartbeat: int = Field(default=5, ge=1, le=20)

    # Logging
    log_level: str = "INFO"

    # Database
    db_path: str = "data/kyf_state.db"


def load_settings() -> Settings:
    """Load and validate settings from environment."""
    return Settings()
