"""
backend/agents/disruption_coordinator.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  AI Disruption Coordinator
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
Listens on Redis for FLIGHT_CANCELLED events (published by the Disruption
Generator or manually). When a cancellation is detected:

  1. Finds all affected bookings from MongoDB
  2. Finds alternative flights on the same route with available seats
  3. Sends a reallocation brief to Claude
  4. Claude decides the optimal reallocation plan — who gets which flight,
     priority order, and what to do with passengers who can't be rebooked
  5. Executes the reallocation: updates bookings + inventory in MongoDB
  6. Publishes DISRUPTION_RESOLVED event to Redis

CLAUDE'S DECISION CRITERIA
───────────────────────────
  - Business travellers reallocated first (time-sensitive)
  - Passengers with fewest days-to-original-flight get priority
  - Prefer same-day alternatives, then next-day
  - If no alternative exists → flag for manual handling + issue voucher

HOW TO FIRE A TEST DISRUPTION
───────────────────────────────
  Open a new terminal:
    python -m agents.disruption_generator

  Or fire manually:
    python test_disruption.py

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.disruption_coordinator
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import motor.motor_asyncio
import redis.asyncio as aioredis

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aerosync.disruption")

ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
MODEL              = "claude-sonnet-4-20250514"
CANCELLATION_CH    = "flight_cancelled"    # channel this agent listens on
DRY_RUN            = os.getenv("DRY_RUN", "false").lower() == "true"


def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


async def get_redis():
    return await aioredis.from_url(
        settings.REDIS_URI,
        encoding="utf-8",
        decode_responses=True,
    )


# =============================================================================
# STEP 1 — FIND AFFECTED BOOKINGS + ALTERNATIVES
# =============================================================================

async def fetch_disruption_context(db, flight_id: str) -> dict | None:
    """
    Given a cancelled flight_id, fetch:
      - The cancelled flight document
      - All bookings on that flight
      - Alternative flights (same route, future dates, available seats)
    """
    # Cancelled flight
    cancelled = await db["live_flights"].find_one({"_id": flight_id})
    if not cancelled:
        log.warning("Cancelled flight %s not found in DB", flight_id)
        return None

    origin = cancelled.get("origin", "")
    dest   = cancelled.get("destination", "")

    # Affected bookings
    bookings = []
    async for bk in db["bookings"].find({"flight_id": flight_id}):
        bookings.append({
            "booking_ref":   bk.get("booking_ref", ""),
            "passenger_id":  bk.get("passenger_id", ""),
            "agent_type":    bk.get("agent_type", bk.get("passenger_id","").split("_")[0]),
            "seats_booked":  bk.get("seats_booked", 1),
            "price_paid":    bk.get("price_per_seat_inr", 0),
        })

    if not bookings:
        log.info("No bookings on cancelled flight %s — nothing to reallocate", flight_id)
        return None

    # Alternative flights: same route, scheduled, has available seats, departs soon
    today     = date.today()
    alts      = []
    async for fl in db["live_flights"].find(
        {
            "origin":      origin,
            "destination": dest,
            "status":      "scheduled",
            "_id":         {"$ne": flight_id},
        },
        {"_id":1, "departure_date":1, "slot":1, "inventory":1, "current_pricing":1}
    ):
        inv = fl.get("inventory") or {}
        avail = inv.get("available", 0)
        if avail < 1:
            continue

        dep_raw = fl.get("departure_date")
        try:
            if isinstance(dep_raw, datetime):
                dep_date = dep_raw.date()
            elif isinstance(dep_raw, date):
                dep_date = dep_raw
            else:
                dep_date = date.fromisoformat(str(dep_raw)[:10])
            days_out = (dep_date - today).days
        except Exception:
            continue

        if days_out < 0 or days_out > 7:  # only alternatives within 7 days
            continue

        cp = fl.get("current_pricing") or {}
        alts.append({
            "flight_id":     str(fl["_id"]),
            "departure":     dep_date.isoformat(),
            "days_out":      days_out,
            "slot":          fl.get("slot", "B"),
            "seats_available": avail,
            "fare_inr":      round(cp.get("ml_fare_inr", 0), 0),
        })

    alts.sort(key=lambda x: (x["days_out"], x["slot"]))

    return {
        "cancelled_flight_id": flight_id,
        "route":    f"{origin}-{dest}",
        "origin":   origin,
        "dest":     dest,
        "bookings": bookings,
        "alternatives": alts[:10],  # top 10 closest alternatives
    }


# =============================================================================
# STEP 2 — BUILD BRIEF FOR CLAUDE
# =============================================================================

def build_brief(ctx: dict) -> str:
    bk_rows = []
    for b in ctx["bookings"]:
        bk_rows.append(
            f"  {b['booking_ref']:<12} | {b['passenger_id']:<25} | "
            f"type: {b['agent_type']:<8} | seats: {b['seats_booked']} | "
            f"paid: ₹{b['price_paid']:,.0f}/seat"
        )

    alt_rows = []
    for a in ctx["alternatives"]:
        alt_rows.append(
            f"  {a['flight_id'][:28]:<28} | {a['departure']} | "
            f"D+{a['days_out']:02d} | slot: {a['slot']} | "
            f"avail: {a['seats_available']} seats | fare: ₹{a['fare_inr']:,.0f}"
        )

    total_pax = sum(b["seats_booked"] for b in ctx["bookings"])

    return f"""You are the AI Disruption Coordinator for AeroSync-India.

## SITUATION
Flight {ctx['cancelled_flight_id']} on route {ctx['route']} has been CANCELLED.
{len(ctx['bookings'])} bookings ({total_pax} passengers) need reallocation.

## AFFECTED PASSENGERS
{chr(10).join(bk_rows)}

## AVAILABLE ALTERNATIVE FLIGHTS (same route, next 7 days)
{chr(10).join(alt_rows) if alt_rows else "  NONE — no alternatives available on this route."}

## REALLOCATION RULES
1. BUSINESS passengers reallocated first — they have time-sensitive commitments
2. Then LEISURE, then STUDENT
3. Prefer same-day alternatives (D+0 or D+1) when available
4. Never put more passengers on a flight than seats_available
5. If no alternative fits → mark as VOUCHER (full refund + ₹1,500 compensation)
6. Each passenger gets exactly ONE alternative or VOUCHER

## RESPONSE FORMAT
Respond with ONLY a JSON object. No explanation, no markdown.
{{
  "reallocation_plan": [
    {{
      "booking_ref":    "BK-XXXX",
      "passenger_id":   "...",
      "action":         "REBOOK" | "VOUCHER",
      "new_flight_id":  "..." (if REBOOK, else null),
      "new_departure":  "YYYY-MM-DD" (if REBOOK, else null),
      "reason":         "one sentence"
    }}
  ],
  "summary": "one paragraph summary of the reallocation plan",
  "unresolved_count": number
}}"""


# =============================================================================
# STEP 3 — CALL CLAUDE
# =============================================================================

async def call_claude(brief: str) -> dict | None:
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set")
        return None
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      MODEL,
                    "max_tokens": 2048,
                    "messages":   [{"role": "user", "content": brief}],
                },
            )
            resp.raise_for_status()
            raw = resp.json()["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"): raw = raw[4:]
            return json.loads(raw.strip())
    except Exception as e:
        log.error("Claude call failed: %s", e)
        return None


# =============================================================================
# STEP 4 — EXECUTE REALLOCATION
# =============================================================================

async def execute_reallocation(db, ctx: dict, plan: dict) -> None:
    actions    = plan.get("reallocation_plan", [])
    rebooked   = 0
    vouchered  = 0

    # Track how many seats we've allocated to each alternative
    seat_usage: dict[str, int] = {}

    for action in actions:
        ref        = action.get("booking_ref", "")
        act        = action.get("action", "VOUCHER")
        new_fid    = action.get("new_flight_id")
        passenger  = action.get("passenger_id", "")
        reason     = action.get("reason", "")

        # Find original booking to get seats_booked
        orig_bk = next(
            (b for b in ctx["bookings"] if b["booking_ref"] == ref), None
        )
        seats = orig_bk["seats_booked"] if orig_bk else 1

        if act == "REBOOK" and new_fid:
            # Validate seat availability hasn't been exhausted
            used  = seat_usage.get(new_fid, 0)
            alt   = next((a for a in ctx["alternatives"] if a["flight_id"] == new_fid), None)
            avail = alt["seats_available"] if alt else 0

            if used + seats > avail:
                log.warning(
                    "Seat overflow on %s for %s — downgrading to VOUCHER",
                    new_fid, ref
                )
                act = "VOUCHER"
            else:
                seat_usage[new_fid] = used + seats

        log.info(
            "%-8s  %s  →  %s  (%s)",
            act, ref, new_fid or "VOUCHER", reason[:60]
        )

        if DRY_RUN:
            continue

        if act == "REBOOK" and new_fid:
            # Update booking record
            await db["bookings"].update_one(
                {"booking_ref": ref},
                {"$set": {
                    "flight_id":        new_fid,
                    "rebooked_from":    ctx["cancelled_flight_id"],
                    "rebooked_at_utc":  datetime.now(tz=timezone.utc),
                    "rebook_reason":    reason,
                    "status":           "rebooked",
                }}
            )
            # Decrement inventory on new flight
            await db["live_flights"].update_one(
                {"_id": new_fid},
                {"$inc": {
                    "inventory.sold":      seats,
                    "inventory.available": -seats,
                }}
            )
            rebooked += 1

        else:
            # Mark as voucher
            await db["bookings"].update_one(
                {"booking_ref": ref},
                {"$set": {
                    "status":           "voucher",
                    "voucher_amount":   (orig_bk["price_paid"] if orig_bk else 0) + 1500,
                    "voucher_reason":   reason,
                    "vouchered_at_utc": datetime.now(tz=timezone.utc),
                }}
            )
            vouchered += 1

    # Mark cancelled flight
    if not DRY_RUN:
        await db["live_flights"].update_one(
            {"_id": ctx["cancelled_flight_id"]},
            {"$set": {"status": "cancelled"}}
        )

    log.info(
        "Reallocation complete — rebooked: %d  vouchers: %d  unresolved: %d",
        rebooked, vouchered, plan.get("unresolved_count", 0)
    )
    log.info("Summary: %s", plan.get("summary", ""))


# =============================================================================
# STEP 5 — PUBLISH RESOLUTION EVENT
# =============================================================================

async def publish_resolution(r, ctx: dict, plan: dict) -> None:
    try:
        await r.publish(
            settings.REDIS_BROADCAST_CHANNEL,
            json.dumps({
                "event_type":         "DISRUPTION_RESOLVED",
                "cancelled_flight":   ctx["cancelled_flight_id"],
                "route":              ctx["route"],
                "affected_bookings":  len(ctx["bookings"]),
                "rebooked":           sum(1 for a in plan.get("reallocation_plan",[]) if a.get("action")=="REBOOK"),
                "vouchered":          sum(1 for a in plan.get("reallocation_plan",[]) if a.get("action")=="VOUCHER"),
                "summary":            plan.get("summary", ""),
                "timestamp":          datetime.now(tz=timezone.utc).isoformat(),
            })
        )
    except Exception as e:
        log.warning("Redis publish failed: %s", e)


# =============================================================================
# MAIN — REDIS SUBSCRIBER LOOP
# =============================================================================

async def handle_cancellation(db, r, flight_id: str) -> None:
    log.info("=" * 60)
    log.info("DISRUPTION: Flight %s cancelled — starting reallocation", flight_id)

    ctx = await fetch_disruption_context(db, flight_id)
    if not ctx:
        return

    log.info(
        "Found %d bookings, %d alternative flights",
        len(ctx["bookings"]), len(ctx["alternatives"])
    )

    brief = build_brief(ctx)
    plan  = await call_claude(brief)

    if not plan:
        log.error("Claude returned no plan — manual intervention required")
        return

    await execute_reallocation(db, ctx, plan)
    await publish_resolution(r, ctx, plan)


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'"
        )
        sys.exit(1)

    db = get_db()
    r  = await get_redis()

    log.info("=" * 60)
    log.info("  AeroSync-India — AI Disruption Coordinator")
    log.info("  Listening on channel: %s", CANCELLATION_CH)
    log.info("  Model: %s", MODEL)
    log.info("  Dry run: %s", DRY_RUN)
    log.info("=" * 60)
    log.info("Waiting for FLIGHT_CANCELLED events...")

    pubsub = r.pubsub()
    await pubsub.subscribe(CANCELLATION_CH)

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        try:
            event = json.loads(message["data"])
        except Exception:
            continue

        event_type = event.get("event_type", "")
        if event_type != "FLIGHT_CANCELLED":
            continue

        flight_id = event.get("flight_id", "")
        if not flight_id:
            continue

        try:
            await handle_cancellation(db, r, flight_id)
        except Exception as e:
            log.error("Reallocation error for %s: %s", flight_id, e, exc_info=True)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Disruption Coordinator stopped.")


if __name__ == "__main__":
    main()
