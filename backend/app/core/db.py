"""
app/core/db.py
Motor (async MongoDB) client — singleton pattern.
"""

import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger("orchestrator.db")

_client: AsyncIOMotorClient | None = None


async def connect_mongo() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.MONGO_URI)
    # Force a connection ping so we fail fast on bad config
    await _client.admin.command("ping")
    logger.info("Motor client connected to %s", settings.MONGO_URI)


async def close_mongo() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Motor client closed")


def get_database() -> AsyncIOMotorDatabase:
    if _client is None:
        raise RuntimeError("MongoDB client is not initialised — call connect_mongo() first.")
    return _client[settings.MONGO_DB]
