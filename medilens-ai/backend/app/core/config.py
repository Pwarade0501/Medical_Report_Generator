"""Application configuration, loaded from environment variables / .env file."""
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ directory (config.py lives in backend/app/core/)
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    APP_NAME: str = "MediLens AI"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    HOST: str = "127.0.0.1"
    PORT: int = 8000

    API_V1_PREFIX: str = "/api/v1"

    # Comma-separated list in .env, e.g. http://localhost:3000,http://localhost:5173
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- Report upload (Phase 2) ---
    # Single source of truth for the upload size limit.
    MAX_UPLOAD_SIZE_MB: int = Field(default=10, gt=0)
    # Relative paths are resolved against the backend/ directory, not the CWD.
    REPORT_STORAGE_PATH: str = "storage/reports"
    TESSERACT_CMD: str = ""

    # Phase 6: optional remote explanation provider. Disabled until a key is set.
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-6-luna"
    OPENAI_TIMEOUT_SECONDS: int = Field(default=20, gt=0, le=120)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            value = value.strip()
            if value.startswith("["):
                return value  # let pydantic parse JSON list
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("DEBUG", mode="before")
    @classmethod
    def _normalize_debug(cls, value):
        # Accept common log-level values found in existing local .env files.
        if isinstance(value, str) and value.strip().upper() in {"WARN", "WARNING", "INFO", "ERROR", "CRITICAL"}:
            return False
        if isinstance(value, str) and value.strip().upper() == "DEBUG":
            return True
        return value


    @property
    def max_upload_size_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def report_storage_dir(self) -> Path:
        path = Path(self.REPORT_STORAGE_PATH).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
