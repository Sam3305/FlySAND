"""
app/core/config.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Centralised Settings (pydantic-settings v2)
──────────────────────────────────────────────────────────────────────────────

Reads from environment variables and/or a .env file at the repo root.
All downstream modules import the `settings` singleton; never instantiate
Settings() directly outside this module.

Usage:
    from app.core.config import settings
    print(settings.MONGO_URI)
──────────────────────────────────────────────────────────────────────────────
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    AeroSync-India runtime configuration.

    Precedence (highest → lowest):
        1. Actual environment variables
        2. Variables defined in the .env file
        3. Field default values defined below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,          # MONGO_URI != mongo_uri
        extra="ignore",               # ignore unrecognised env vars silently
    )

    # ── MongoDB ───────────────────────────────────────────────────────────────
    MONGO_URI: str
    """Motor connection string, e.g. 'mongodb://localhost:27017'."""

    MONGO_DB: str
    """Target database name, e.g. 'flight_ops'."""

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URI: str
    """Redis connection URL, e.g. 'redis://localhost:6379/0'."""

    REDIS_BROADCAST_CHANNEL: str
    """
    Pub/Sub channel for fan-out events (SEAT_SOLD, PRICE_UPDATE, DISRUPTION_ALERT).
    WebSocket bridge and booking engine both publish here.
    """

    REDIS_CHANNEL_WEATHER_SEVERE: str
    """
    Pub/Sub channel exclusively for WEATHER_SEVERE events.
    The game_loop task subscribes here to trigger repricing pipelines.
    """

    # ── Distributed Locking ───────────────────────────────────────────────────
    REDIS_LOCK_TTL_SECONDS: int = 5
    """
    TTL (seconds) for SETNX-based booking locks.
    Default of 5 s is sufficient for one booking round-trip; increase only
    if p99 latency to MongoDB exceeds ~2 s under load.
    """

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]
    """
    Allowed CORS origins for the FastAPI CORSMiddleware.
    Override via CORS_ORIGINS='["https://app.aerosync.in"]' in .env.
    """


# ---------------------------------------------------------------------------
# Module-level singleton — import this everywhere.
# ---------------------------------------------------------------------------
settings = Settings()
