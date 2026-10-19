"""The one typed settings object. Secrets come from the environment only."""

import sys
from pathlib import Path

from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
_DATASET = REPO_ROOT / "data" / "meridian_dataset"

# A model slug is the same name the provider uses.
AGENT_MODEL_DEFAULT = "google/gemini-3-flash-preview-20251217"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # Required: the app refuses to start without them.
    OPENROUTER_API_KEY: SecretStr
    ADMIN_TOKEN: SecretStr
    SCHEDULING_DB_PATH: Path
    APP_DB_PATH: Path
    INDEX_PATH: Path

    # Defaulted.
    SEED_DB_PATH: Path = _DATASET / "scheduling_db" / "meridian_scheduling.sqlite"
    KB_DIR: Path = _DATASET / "knowledge_base"
    REFERENCE_DATE: str = "2026-10-16"
    REFERENCE_TIME: str = "12:00"
    AGENT_MODEL: str = AGENT_MODEL_DEFAULT
    SAFETY_MODEL: str = "google/gemini-3.1-flash-lite"
    CALLER_MODEL: str = AGENT_MODEL_DEFAULT
    JUDGE_MODEL: str = AGENT_MODEL_DEFAULT
    EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    MODEL_PRICES: dict[str, dict[str, float]] = {}
    OPENAI_API_KEY: SecretStr | None = None
    TURN_DEADLINE: int = 15
    IDLE_CLOSE_MINUTES: int = 30
    SPEND_ALERT_USD: float = 100
    PUBLIC_URL: str = ""
    OPENAI_SPEND_USD: float = 0
    LANGFUSE_BASE_URL: str = "https://us.cloud.langfuse.com"
    LANGFUSE_PUBLIC_KEY: SecretStr | None = None
    LANGFUSE_SECRET_KEY: SecretStr | None = None
    DEMO_FAULT_INJECTION: bool = False

    # Rate and size caps (far above PF-3's 12 turns and the eval's 8).
    NEW_CONVERSATIONS_PER_HOUR: int = 60
    MESSAGES_PER_MINUTE: int = 30
    BUSINESS_WRITES_PER_MINUTE: int = 30
    TURN_CAP: int = 40
    MESSAGE_MAX_CHARS: int = 2000


def load_settings_or_exit() -> Settings:
    """Load settings; on a missing or invalid one print its name (never a value) and exit 1."""
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as error:
        missing: list[str] = []
        invalid: list[str] = []
        for item in error.errors():
            name = str(item["loc"][0]) if item["loc"] else "?"
            (missing if item["type"] == "missing" else invalid).append(name)
        if missing:
            sys.stderr.write(f"Missing required setting(s): {', '.join(missing)}\n")
        if invalid:
            sys.stderr.write(f"Invalid setting(s): {', '.join(invalid)}\n")
        raise SystemExit(1) from None
