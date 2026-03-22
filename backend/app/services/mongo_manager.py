"""
database/mongo_manager.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Async MongoDB Connection Pool (Motor)
──────────────────────────────────────────────────────────────────────────────

RESPONSIBILITIES
────────────────
1. Owns the single Motor AsyncIOMotorClient singleton for the process.
2. Exposes the `live_flights` collection with a typed accessor.
3. Bootstraps all required indexes on first connect:
      - UNIQUE  on _id / flight_id           (document dedup — flight_id is _id)
      - COMPOUND on (route, departure_date)   (booking engine range queries)
      - SINGLE  on status                     (scheduled-flight filter)
      - COMPOUND on (origin, destination, departure_date) (OD-pair lookup)
      - TTL     on seeded_at (90 days)        (auto-expire completed cycles)
4. Provides `bulk_upsert_flights()` — idempotent, safe to re-run daily.
5. Provides typed query helpers for the booking and pricing engines.

CONFIGURATION (environment variables)
──────────────────────────────────────
    MONGO_URI       = "mongodb://localhost:27017"   (default)
    MONGO_DB_NAME   = "aerosync_india"              (default)
    MONGO_MAX_POOL  = 20                            (default)
    MONGO_MIN_POOL  = 5                             (default)
    MONGO_TLS       = "false"                       (default)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)
from pymongo import ASCENDING, IndexModel, UpdateOne
from pymongo.errors import BulkWriteError

logger = logging.getLogger("aerosync.mongo_manager")


# =============================================================================
# CONFIGURATION
# =============================================================================

MONGO_URI: str      = os.getenv("MONGO_URI",      "mongodb://localhost:27017")
MONGO_DB_NAME: str  = os.getenv("MONGO_DB_NAME",  "aerosync_india")
MONGO_MAX_POOL: int = int(os.getenv("MONGO_MAX_POOL", "20"))
MONGO_MIN_POOL: int = int(os.getenv("MONGO_MIN_POOL", "5"))
MONGO_TLS: bool     = os.getenv("MONGO_TLS", "false").lower() == "true"

COLLECTION_LIVE_FLIGHTS: str = "live_flights"

# Auto-expire seeded documents after 90 days (LANDED/CANCELLED cycles not needed longer)
_TTL_SECONDS: int = 90 * 24 * 60 * 60


# =============================================================================
# MongoManager
# =============================================================================

class MongoManager:
    """
    Process-wide singleton wrapping Motor's AsyncIOMotorClient.

    Never instantiate directly — use the classmethod API:
        await MongoManager.connect()
        col = MongoManager.live_flights()
        await MongoManager.disconnect()
    """

    _client: AsyncIOMotorClient | None   = None
    _db:     AsyncIOMotorDatabase | None = None

    # ─────────────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def connect(cls) -> None:
        """
        Create the Motor connection pool and bootstrap indexes.
        Idempotent — safe to call multiple times (subsequent calls are no-ops).
        """
        if cls._client is not None:
            logger.debug("MongoManager already connected — skipping.")
            return

        logger.info(
            "Connecting to MongoDB | uri=%s | db=%s | pool=%d-%d",
            MONGO_URI, MONGO_DB_NAME, MONGO_MIN_POOL, MONGO_MAX_POOL,
        )

        cls._client = AsyncIOMotorClient(
            MONGO_URI,
            maxPoolSize=MONGO_MAX_POOL,
            minPoolSize=MONGO_MIN_POOL,
            tls=MONGO_TLS,
            serverSelectionTimeoutMS=10_000,   # fail fast in CI/CD
            connectTimeoutMS=5_000,
            socketTimeoutMS=30_000,
            tz_aware=True,
        )
        cls._db = cls._client[MONGO_DB_NAME]

        try:
            await cls._client.admin.command("ping")
            logger.info("MongoDB ping OK.")
        except Exception as exc:
            cls._client = None
            cls._db     = None
            raise ConnectionError(
                f"Cannot connect to MongoDB at '{MONGO_URI}': {exc}"
            ) from exc

        await cls._ensure_indexes()

    @classmethod
    async def disconnect(cls) -> None:
        """Close the connection pool. Call at application / seeder shutdown."""
        if cls._client is not None:
            cls._client.close()
            cls._client = None
            cls._db     = None
            logger.info("MongoDB connection pool closed.")

    # ─────────────────────────────────────────────────────────────────────────
    # COLLECTION ACCESSORS
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    def db(cls) -> AsyncIOMotorDatabase:
        if cls._db is None:
            raise RuntimeError(
                "MongoManager is not connected. "
                "Call `await MongoManager.connect()` first."
            )
        return cls._db

    @classmethod
    def collection(cls, name: str) -> AsyncIOMotorCollection:
        return cls.db()[name]

    @classmethod
    def live_flights(cls) -> AsyncIOMotorCollection:
        """Typed shortcut to the `live_flights` collection."""
        return cls.collection(COLLECTION_LIVE_FLIGHTS)

    # ─────────────────────────────────────────────────────────────────────────
    # INDEX BOOTSTRAP
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def _ensure_indexes(cls) -> None:
        """
        Idempotent index bootstrap. Motor's create_indexes is safe to call
        on startup even if indexes already exist. background=True avoids
        blocking reads on large existing collections.
        """
        col = cls.live_flights()
        logger.info("Bootstrapping indexes on '%s'...", COLLECTION_LIVE_FLIGHTS)

        indexes = [
            # 1. COMPOUND: route + departure_date
            #    Booking engine: "all SCHEDULED DEL-BOM flights on 2026-10-16"
            IndexModel(
                [("route", ASCENDING), ("departure_date", ASCENDING)],
                name="idx_route_date",
                background=True,
            ),

            # 2. STATUS — filter for SCHEDULED inventory (pricing engine hot path)
            IndexModel(
                [("status", ASCENDING)],
                name="idx_status",
                background=True,
            ),

            # 3. DEPARTURE DATE — range scans: "next 7 days of flights"
            IndexModel(
                [("departure_date", ASCENDING)],
                name="idx_departure_date",
                background=True,
            ),

            # 4. OD-PAIR + DATE — airport pair inventory lookup
            IndexModel(
                [
                    ("origin", ASCENDING),
                    ("destination", ASCENDING),
                    ("departure_date", ASCENDING),
                ],
                name="idx_od_pair_date",
                background=True,
            ),

            # 5. TTL — auto-delete docs where seeded_at < (now - 90 days)
            #    Keeps the collection lean; LANDED/CANCELLED cycles are archived
            #    to a cold-storage collection by a separate archival job.
            IndexModel(
                [("seeded_at", ASCENDING)],
                name="idx_ttl_seeded_at",
                expireAfterSeconds=_TTL_SECONDS,
                background=True,
            ),
        ]

        await col.create_indexes(indexes)
        logger.info("Index bootstrap complete: %d indexes ensured.", len(indexes))

        # ── Bookings collection indexes ───────────────────────────────────────
        # UNIQUE on idempotency_key — MongoDB-level enforcement so even if the
        # application check in booking.py is bypassed under extreme concurrency,
        # the DB itself will reject a duplicate key insert with a WriteError.
        bookings_col = cls._db["bookings"]
        await bookings_col.create_index(
            [("idempotency_key", ASCENDING)],
            name="idx_bookings_idempotency_key",
            unique=True,
            background=True,
        )
        logger.info("Bookings unique index on idempotency_key ensured.")

    # ─────────────────────────────────────────────────────────────────────────
    # SEEDER UTILITY: Bulk Upsert
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def bulk_upsert_flights(
        cls,
        flight_dicts: list[dict[str, Any]],
        batch_size: int = 200,
    ) -> dict[str, int]:
        """
        Idempotent bulk upsert for the daily seeder.

        Mechanism: UpdateOne(filter={"_id": flight_id}, update={"$set": doc}, upsert=True)
        - If the flight_id does not exist  →  INSERT  (new flight)
        - If the flight_id already exists  →  UPDATE  (refresh physics/pricing)
        - Never creates duplicates, never fails on re-run.

        Batches writes in groups of `batch_size` to stay within Atlas write-concern
        limits and avoid overwhelming the driver on an M0 free tier.

        Args:
            flight_dicts : List of dicts from LiveFlight.to_mongo_dict()
            batch_size   : Documents per bulk_write call (default 200)

        Returns:
            {"upserted": N, "modified": N, "total": N}
        """
        if not flight_dicts:
            logger.warning("bulk_upsert_flights: empty list — nothing to write.")
            return {"upserted": 0, "modified": 0, "total": 0}

        col              = cls.live_flights()
        total_upserted   = 0
        total_modified   = 0
        total_errors     = 0

        num_batches = (len(flight_dicts) + batch_size - 1) // batch_size
        logger.info(
            "Starting bulk upsert: %d documents in %d batch(es) of %d.",
            len(flight_dicts), num_batches, batch_size,
        )

        for batch_idx in range(0, len(flight_dicts), batch_size):
            batch = flight_dicts[batch_idx : batch_idx + batch_size]

            operations = [
                UpdateOne(
                    filter={"_id": doc["_id"]},
                    update={"$set": doc},
                    upsert=True,
                )
                for doc in batch
            ]

            try:
                result = await col.bulk_write(operations, ordered=False)
                total_upserted += result.upserted_count
                total_modified  += result.modified_count
                logger.debug(
                    "Batch %d/%d — upserted=%d, modified=%d.",
                    batch_idx // batch_size + 1,
                    num_batches,
                    result.upserted_count,
                    result.modified_count,
                )
            except BulkWriteError as bwe:
                # Log and continue — partial success is acceptable for a seeder.
                # The next daily run will retry failed documents.
                write_errors = bwe.details.get("writeErrors", [])
                total_errors += len(write_errors)
                logger.error(
                    "BulkWriteError in batch %d: %d doc(s) failed. First: %s",
                    batch_idx // batch_size + 1,
                    len(write_errors),
                    write_errors[0] if write_errors else "unknown",
                )
                total_upserted += bwe.details.get("nUpserted", 0)
                total_modified  += bwe.details.get("nModified", 0)

        summary = {
            "upserted": total_upserted,
            "modified": total_modified,
            "errors":   total_errors,
            "total":    total_upserted + total_modified,
        }
        logger.info(
            "Bulk upsert complete — upserted=%d, modified=%d, errors=%d, "
            "total_processed=%d / %d submitted.",
            total_upserted, total_modified, total_errors,
            total_upserted + total_modified, len(flight_dicts),
        )
        return summary

    # ─────────────────────────────────────────────────────────────────────────
    # QUERY HELPERS  (used by the booking / pricing engines)
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def get_scheduled_flights(
        cls,
        route: str | None         = None,
        departure_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch SCHEDULED flights with optional route and date filters.
        Returns raw Motor dicts — callers hydrate with LiveFlight.from_mongo_dict().
        """
        query: dict[str, Any] = {"status": "scheduled"}
        if route:
            query["route"] = route
        if departure_date:
            query["departure_date"] = departure_date

        cursor = cls.live_flights().find(query).sort("departure_date", ASCENDING)
        return await cursor.to_list(length=None)

    @classmethod
    async def get_flight_by_id(cls, flight_id: str) -> dict[str, Any] | None:
        """Fetch a single flight document by its flight_id (_id key)."""
        return await cls.live_flights().find_one({"_id": flight_id})

    @classmethod
    async def update_flight_status(
        cls,
        flight_id: str,
        new_status: str,
    ) -> bool:
        """
        Update the status field of a single flight.
        Returns True if a document was matched and updated.
        """
        result = await cls.live_flights().update_one(
            {"_id": flight_id},
            {
                "$set": {
                    "status":       new_status,
                    "last_updated": datetime.now(tz=timezone.utc),
                }
            },
        )
        return result.matched_count == 1

    @classmethod
    async def increment_seats_sold(
        cls,
        flight_id: str,
        seats_purchased: int = 1,
    ) -> dict[str, Any] | None:
        """
        Atomically sell N seats on a SCHEDULED flight.
        Uses findOneAndUpdate with an availability guard to prevent oversell.
        Returns the updated document, or None if the flight is full / not found.
        """
        updated_doc = await cls.live_flights().find_one_and_update(
            {
                "_id":                       flight_id,
                "inventory.available":       {"$gte": seats_purchased},
                "status":                    "scheduled",
            },
            {
                "$inc": {
                    "inventory.sold":      seats_purchased,
                    "inventory.available": -seats_purchased,
                },
                "$set": {"last_updated": datetime.now(tz=timezone.utc)},
            },
            return_document=True,
        )
        if updated_doc is None:
            logger.warning(
                "increment_seats_sold: no update for flight_id='%s'. "
                "Flight may be full, not SCHEDULED, or not found.",
                flight_id,
            )
        return updated_doc

    # ─────────────────────────────────────────────────────────────────────────
    # HEALTH CHECK
    # ─────────────────────────────────────────────────────────────────────────

    @classmethod
    async def health_check(cls) -> dict[str, Any]:
        """
        Returns a health payload for the FastAPI /health endpoint.
        Reports round-trip latency and collection document counts.
        """
        try:
            t0 = datetime.now(tz=timezone.utc)
            await cls._client.admin.command("ping")
            latency_ms = (datetime.now(tz=timezone.utc) - t0).total_seconds() * 1000

            total_flights     = await cls.live_flights().count_documents({})
            scheduled_flights = await cls.live_flights().count_documents({"status": "scheduled"})

            return {
                "status":            "healthy",
                "mongo_uri":         MONGO_URI,
                "database":          MONGO_DB_NAME,
                "ping_latency_ms":   round(latency_ms, 2),
                "total_flights":     total_flights,
                "scheduled_flights": scheduled_flights,
            }
        except Exception as exc:
            return {"status": "unhealthy", "error": str(exc)}
