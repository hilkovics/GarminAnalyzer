"""Application settings (pydantic-settings). Env vars are prefixed `TRAINING_`.

The Garmin token directory additionally honours the `GARMINTOKENS` variable used by garminconnect.
Only the garminconnect token file (`garmin_tokens.json`) is stored there – never the Garmin password
(CLAUDE.md rule 8).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRAINING_", env_file=".env", extra="ignore")

    db_path: Path = Field(default=PROJECT_ROOT / "data" / "training.db")
    garmin_tokens: Path = Field(
        default=Path("~/.garminconnect"),
        validation_alias=AliasChoices("TRAINING_GARMIN_TOKENS", "GARMINTOKENS"),
    )
    rate_limit_s: float = Field(default=0.7, ge=0.0, description="Pause between Garmin requests (s).")
    max_retries: int = Field(default=5, ge=1, description="Attempts per Garmin request on 429/5xx.")
    fixtures_dir: Path = Field(default=PROJECT_ROOT / "backend" / "tests" / "fixtures")
    # optional integrations (phase 7); secrets are SecretStr so they never show up in repr / logs
    telegram_token: SecretStr | None = Field(
        default=None, description="Telegram bot token (morning message)."
    )
    telegram_chat_id: str | None = Field(default=None, description="Telegram chat id of the morning message.")
    anthropic_api_key: SecretStr | None = Field(default=None, description="Enables the weekly AI report.")
    ai_model: str = Field(default="claude-opus-5-5", description="Model of the weekly AI report.")
    reports_dir: Path = Field(default=PROJECT_ROOT / "docs" / "reports")

    @property
    def tokens_dir(self) -> Path:
        """Token directory with `~` expanded."""
        return self.garmin_tokens.expanduser()

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.expanduser().resolve()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
