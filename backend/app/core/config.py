"""
backend/app/core/config.py
==========================
Central configuration for the application.

All values are read from environment variables (or a .env file).
This means:
  - No secrets ever appear in source code.
  - Switching between dev / staging / production is just a .env swap.

Usage anywhere in the app:
    from app.core.config import settings
    print(settings.database_url)
"""

from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Each field here maps to an environment variable of the same name
    (case-insensitive).  Default values are for local development only.
    """

    # --- Application ---
    app_name: str = "Liberia Public Data Intelligence"
    app_version: str = "1.0.0"
    app_env: str = "development"          # development | staging | production
    debug: bool = False

    # --- Server ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- Database ---
    # Full PostgreSQL connection string.
    # Format: postgresql://USER:PASSWORD@HOST:PORT/DATABASE
    database_url: str = "postgresql://postgres:postgres@localhost:5432/liberia_data"

    # --- Logging ---
    log_level: str = "INFO"               # DEBUG | INFO | WARNING | ERROR

    # --- AI / External APIs (optional — not used in v1 skeleton) ---
    # Set these only when you are ready to enable the AI query feature.
    anthropic_api_key: str = ""           # Leave blank to disable AI layer

    # ---------------------------------------------------------------
    # Heroku compatibility fix
    # ---------------------------------------------------------------
    # Heroku Postgres sets DATABASE_URL with the prefix "postgres://"
    # but SQLAlchemy 1.4+ requires "postgresql://".
    # This validator rewrites the prefix automatically at startup.
    @field_validator("database_url", mode="before")
    @classmethod
    def fix_heroku_postgres_url(cls, v: str) -> str:
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    class Config:
        # Tell pydantic-settings to read from a .env file
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Allow extra environment variables without error
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    Using @lru_cache means the .env file is only read once per process,
    not on every request.  This is the standard FastAPI pattern.
    """
    return Settings()


# Convenience alias — use this in route files and services
settings = get_settings()
