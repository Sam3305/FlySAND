"""
test_disruption.py
──────────────────
Fires a FLIGHT_CANCELLED event to test the Disruption Coordinator.
Run this while disruption_coordinator.py is running in another terminal.

Usage:
  cd C:\AeroSync-India\backend
  python test_disruption.py
"""

import asyncio
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings
import redis.asyncio as aioredis
import pymongo


async def fire_cancellation():
    # Pick a real flight that has bookings
    db = pymongo.MongoClient(settings.MONGO_URI)[settings.MONGO_DB]

    # Find a flight with bookings that isn't sold out
    flight = None
    booking_counts = {}
    for bk in db["bookings"].find({}, {"flight_id": 1}):
        fid = bk.get("flight_id", "")
        booking_counts[fid] = booking_counts.get(fid, 0) + 1

    # Pick the flight with the most bookings (most interesting for reallocation)
    if booking_counts:
        best_fid = max(booking_counts, key=booking_counts.get)
        flight = db["live_flights"].find_one(
            {"_id": best_fid, "status": "scheduled"},
            {"_id": 1, "origin": 1, "destination": 1, "departure_date": 1}
        )

    if not flight:
        print("No suitable flight found. Run the swarm first to generate bookings.")
        return

    fid    = str(flight["_id"])
    route  = f"{flight.get('origin')}-{flight.get('destination')}"
    n_bks  = booking_counts.get(fid, 0)

    print(f"Firing cancellation for: {fid}")
    print(f"Route:    {route}")
    print(f"Bookings: {n_bks}")
    print()

    r = await aioredis.from_url(
        settings.REDIS_URI,
        encoding="utf-8",
        decode_responses=True,
    )

    event = {
        "event_type": "FLIGHT_CANCELLED",
        "flight_id":  fid,
        "route":      route,
        "reason":     "weather_severe",
        "severity":   0.9,
    }

    await r.publish("flight_cancelled", json.dumps(event))
    print(f"Published FLIGHT_CANCELLED to Redis channel 'flight_cancelled'")
    print("Watch the disruption_coordinator terminal for reallocation output.")
    await r.aclose()


if __name__ == "__main__":
    asyncio.run(fire_cancellation())
