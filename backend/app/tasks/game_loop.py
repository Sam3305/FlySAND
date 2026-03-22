"""
app/tasks/game_loop.py
Background game-loop task.

Listens for WEATHER_SEVERE events on the Redis bus.
On each event:
  1. Calls economics_engine.recalculate_floor() to get the new price floor.
  2. Calls ml_pricing_model.predict_price()    to get the ML-adjusted price.
  3. Atomically writes both values to MongoDB `live_flights`.
  4. Publishes a PRICE_UPDATE event so WebSocket clients receive the change.
"""

import asyncio
import json
import logging

from app.core.config import settings
from app.core.db import get_database
from app.core.redis_client import create_pubsub, publish
from app.engines.economics_engine import recalculate_floor
from app.engines.ml_pricing_model import predict_price

logger = logging.getLogger("orchestrator.game_loop")

RECONNECT_DELAY = 3  # seconds between reconnect attempts after errors


async def _handle_weather_severe(event: dict) -> None:
    """
    Core handler: runs the pricing pipeline for every flight impacted by the
    weather event and persists + broadcasts the updated prices.
    """
    affected_flights: list[str] = event.get("affected_flight_ids", [])
    weather_severity: float = float(event.get("severity", 1.0))  # 0.0 – 1.0 scale
    region: str = event.get("region", "UNKNOWN")

    if not affected_flights:
        logger.warning("WEATHER_SEVERE event carries no affected_flight_ids — skipping")
        return

    logger.info(
        "⛈  WEATHER_SEVERE: region=%s severity=%.2f flights=%s",
        region,
        weather_severity,
        affected_flights,
    )

    db = get_database()
    collection = db["live_flights"]

    for flight_id in affected_flights:
        try:
            flight_doc = await collection.find_one(
                {"flight_id": flight_id}, {"_id": 0}
            )
            if flight_doc is None:
                logger.warning("Flight %r not found in DB — skipping repricing", flight_id)
                continue

            current_price: float = flight_doc.get("current_price_usd", 0.0)
            seats_available: int = flight_doc.get("seats_available", 0)
            total_seats: int = flight_doc.get("total_seats", 100)

            # ── Step 1: Economics engine → new floor price ────────────────
            new_floor = await asyncio.to_thread(
                recalculate_floor,
                flight_id=flight_id,
                current_price=current_price,
                severity=weather_severity,
                region=region,
            )

            # ── Step 2: ML model → optimised price above the floor ────────
            new_price = await asyncio.to_thread(
                predict_price,
                flight_id=flight_id,
                floor_price=new_floor,
                seats_available=seats_available,
                total_seats=total_seats,
                severity=weather_severity,
            )

            # Enforce the floor as a hard lower bound
            final_price = max(new_floor, new_price)

            # ── Step 3: Atomic MongoDB update ─────────────────────────────
            await collection.update_one(
                {"flight_id": flight_id},
                {
                    "$set": {
                        "current_price_usd": round(final_price, 2),
                        "price_floor_usd": round(new_floor, 2),
                        "last_repriced_by": "game_loop:WEATHER_SEVERE",
                    }
                },
            )

            # ── Step 4: Publish PRICE_UPDATE event ────────────────────────
            price_event = {
                "event_type": "PRICE_UPDATE",
                "flight_id": flight_id,
                "previous_price_usd": round(current_price, 2),
                "new_price_usd": round(final_price, 2),
                "price_floor_usd": round(new_floor, 2),
                "trigger": "WEATHER_SEVERE",
                "region": region,
                "severity": weather_severity,
            }
            await publish(settings.REDIS_BROADCAST_CHANNEL, price_event)

            logger.info(
                "💰  Repriced flight=%s  $%.2f → $%.2f  (floor=$%.2f)",
                flight_id,
                current_price,
                final_price,
                new_floor,
            )

        except Exception as exc:
            # Log and continue — one flight's failure must not stall the loop
            logger.exception("Error repricing flight=%s: %s", flight_id, exc)


# ─── Main loop ────────────────────────────────────────────────────────────────

async def start_game_loop() -> None:
    """
    Entry-point for the background game-loop coroutine.
    Subscribes to REDIS_CHANNEL_WEATHER_SEVERE and drives the pricing pipeline.
    Reconnects automatically on transient errors.
    """
    while True:
        pubsub = None
        try:
            pubsub = await create_pubsub()
            await pubsub.subscribe(settings.REDIS_CHANNEL_WEATHER_SEVERE)
            logger.info(
                "Game-loop subscribed to channel '%s'",
                settings.REDIS_CHANNEL_WEATHER_SEVERE,
            )

            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue

                data: str = raw_message.get("data", "")
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON on WEATHER_SEVERE channel: %r", data)
                    continue

                # Fire the handler as a separate task so the subscription loop
                # is never blocked by a slow repricing pipeline.
                asyncio.create_task(_handle_weather_severe(event))

        except asyncio.CancelledError:
            logger.info("Game-loop task cancelled — shutting down cleanly")
            break

        except Exception as exc:
            logger.error(
                "Game-loop error: %s — reconnecting in %ds …",
                exc,
                RECONNECT_DELAY,
            )
            await asyncio.sleep(RECONNECT_DELAY)

        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(settings.REDIS_CHANNEL_WEATHER_SEVERE)
                    await pubsub.aclose()
                except Exception:
                    pass
