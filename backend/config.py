"""Environment-backed application settings for RoboArm AI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "roboarm.db"


def _split_origins(value: str) -> tuple[str, ...]:
    return tuple(origin.strip() for origin in value.split(",") if origin.strip())


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated runtime settings loaded once during process startup."""

    app_name: str
    app_version: str
    allowed_origins: tuple[str, ...]
    database_path: Path
    static_directory: Path | None
    telemetry_log_interval: int


def load_settings() -> Settings:
    """Load and validate supported environment variables."""
    static_value = os.getenv("ROBOARM_STATIC_DIR", "").strip()
    return Settings(
        app_name="RoboArm AI API",
        app_version="1.2.0",
        allowed_origins=_split_origins(
            os.getenv(
                "ROBOARM_ALLOWED_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            )
        ),
        database_path=Path(
            os.getenv("ROBOARM_DB_PATH", str(DEFAULT_DATABASE_PATH))
        ).expanduser().resolve(),
        static_directory=(Path(static_value).expanduser().resolve() if static_value else None),
        telemetry_log_interval=_positive_int("ROBOARM_TELEMETRY_LOG_INTERVAL", 8),
    )


settings = load_settings()
