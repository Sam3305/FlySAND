"""
app/api/routes/booking.py
POST /api/v1/book — atomic booking endpoint consumed by the Agent Swarm.

Flow:
  1. Validate Redis distributed lock (idempotency / race-condition guard).
  2. MongoDB findOneAndUpdate with $inc to atomically decrement seat inventory.
  3. Publish SEAT_SOLD event to the internal Redis bus (broadcast channel).
  4. Release the lock.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.db import get_database
from app.core.redis_client import acquire_lock, release_lock, publish

logger = logging.getLogger("orchestrator.booking")
router = APIRouter()


# ─── Request / Response models ───────────────────────────────────────────────

class BookingRequest(BaseModel):
    flight_id: str = Field(..., description="Target flight identifier")
    passenger_id: str = Field(..., description="Passenger / agent identifier")
    seats_requested: int = Field(1, ge=1, le=9, description="Number of seats to book")
    idempotency_key: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Client-supplied UUID; prevents double-booking on retries",
    )


class BookingResponse(BaseModel):
    booking_ref: str
    flight_id: str
    passenger_id: str
    seats_booked: int
    seats_remaining: int
    price_charged_usd: float
    booked_at_utc: str


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post(
    "/book",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book seats (Agent Swarm endpoint)",
    description=(
        "Atomically decrements seat inventory, enforces a Redis distributed lock "
        "per flight, and publishes a SEAT_SOLD event to the Redis broadcast bus."
    ),
)
async def book_flight(payload: BookingRequest) -> BookingResponse:

    lock_key = f"lock:booking:{payload.flight_id}"

    # ── 1. Acquire distributed lock ──────────────────────────────────────────
    acquired = await acquire_lock(lock_key, ttl=settings.REDIS_LOCK_TTL_SECONDS)
    if not acquired:
        logger.warning(
            "Lock contention on flight=%s for passenger=%s (idempotency_key=%s)",
            payload.flight_id,
            payload.passenger_id,
            payload.idempotency_key,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "LOCK_CONTENTION",
                "message": (
                    f"Flight {payload.flight_id!r} is currently being booked by another agent. "
                    "Retry after a short back-off."
                ),
                "flight_id": payload.flight_id,
            },
        )

    try:
        db = get_database()
        collection = db["live_flights"]

        # ── 1b. Idempotency check ─────────────────────────────────────────────
        # Before touching inventory, check if this idempotency_key was already
        # processed. If yes, return the original booking response — do not book
        # a second seat. This handles retries from network failures and the
        # double-submission scenario caught by Scenario 3 of the ACID stress test.
        existing = await db["bookings"].find_one(
            {"idempotency_key": payload.idempotency_key},
            {"_id": 0},
        )
        if existing:
            logger.info(
                "Idempotent replay — key=%s flight=%s ref=%s (no inventory change)",
                payload.idempotency_key,
                payload.flight_id,
                existing.get("booking_ref"),
            )
            return BookingResponse(
                booking_ref=existing["booking_ref"],
                flight_id=existing["flight_id"],
                passenger_id=existing["passenger_id"],
                seats_booked=existing["seats_booked"],
                seats_remaining=-1,
                price_charged_usd=0.0,
                booked_at_utc=existing.get("booked_at_utc", ""),
            )

        # ── 2. Atomic inventory decrement ────────────────────────────────────
        # Documents are stored with flight_id promoted to _id by to_mongo_dict().
        # Inventory fields live at inventory.sold / inventory.available (nested).
        # Status is stored as the enum value string "scheduled" (lowercase).
        updated_flight = await collection.find_one_and_update(
            filter={
                "_id": payload.flight_id,
                "inventory.available": {"$gte": payload.seats_requested},
                "status": {"$in": ["scheduled", "boarding"]},
            },
            update={
                "$inc": {
                    "inventory.available": -payload.seats_requested,
                    "inventory.sold":      payload.seats_requested,
                },
            },
            projection={"_id": 0},
            return_document=True,
        )

        if updated_flight is None:
            flight_check = await collection.find_one(
                {"_id": payload.flight_id},
                {"inventory.available": 1, "status": 1, "_id": 0}
            )
            if flight_check is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "FLIGHT_NOT_FOUND", "flight_id": payload.flight_id},
                )
            available = (flight_check.get("inventory") or {}).get("available", 0)
            flt_status = flight_check.get("status", "UNKNOWN")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "BOOKING_REJECTED",
                    "reason": (
                        f"Insufficient seats ({available} available, "
                        f"{payload.seats_requested} requested) or invalid flight status: {flt_status}"
                    ),
                    "seats_available": available,
                    "flight_status": flt_status,
                },
            )

        # ── 4. Emit SEAT_SOLD to Redis bus ────────────────────────────────────
        booking_ref = f"BK-{uuid.uuid4().hex[:10].upper()}"
        booked_at   = datetime.now(tz=timezone.utc).isoformat()

        inventory        = updated_flight.get("inventory") or {}
        seats_remaining  = inventory.get("available", 0)
        price_inr        = (updated_flight.get("current_pricing") or {}).get("ml_fare_inr", 0.0)
        price_charged    = price_inr * payload.seats_requested

        # Persist booking document
        await db["bookings"].insert_one(
            {
                "booking_ref":      booking_ref,
                "flight_id":        payload.flight_id,
                "passenger_id":     payload.passenger_id,
                "seats_booked":     payload.seats_requested,
                "price_charged_inr": price_charged,
                "idempotency_key":  payload.idempotency_key,
                "booked_at_utc":    booked_at,
            }
        )

        event = {
            "event_type":       "SEAT_SOLD",
            "booking_ref":      booking_ref,
            "flight_id":        payload.flight_id,
            "passenger_id":     payload.passenger_id,
            "seats_sold":       payload.seats_requested,
            "seats_remaining":  seats_remaining,
            "price_charged_inr": price_charged,
            "timestamp_utc":    booked_at,
        }
        await publish(settings.REDIS_BROADCAST_CHANNEL, event)
        logger.info(
            "SEAT_SOLD published — flight=%s ref=%s seats_remaining=%d",
            payload.flight_id,
            booking_ref,
            seats_remaining,
        )

        return BookingResponse(
            booking_ref=booking_ref,
            flight_id=payload.flight_id,
            passenger_id=payload.passenger_id,
            seats_booked=payload.seats_requested,
            seats_remaining=seats_remaining,
            price_charged_usd=round(price_charged / 84.0, 2),  # INR → USD display only
            booked_at_utc=booked_at,
        )

    except HTTPException:
        raise  # propagate 4xx unchanged

    except Exception as exc:
        logger.exception("Unexpected booking error for flight=%s: %s", payload.flight_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "INTERNAL_ERROR", "message": str(exc)},
        )

    finally:
        # ── Always release the lock ───────────────────────────────────────────
        await release_lock(lock_key)
        logger.debug("Lock released for flight=%s", payload.flight_id)
