"""
backend/agents/yield_manager.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  AI Yield Manager
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
A Claude-powered agent that acts as the airline's head of revenue management.

Every SCAN_INTERVAL seconds it:
  1. Pulls all scheduled flights from MongoDB
  2. Groups them by route and analyses load factor vs days-to-departure
  3. Sends a structured brief to Claude (claude-sonnet-4-20250514)
  4. Parses Claude's pricing decisions
  5. Writes new fares back to MongoDB
  6. Publishes PRICE_UPDATE events to Redis

DECISION LOGIC (Claude's job)
──────────────────────────────
Claude receives a table of flights and must decide for each:
  - RAISE   → flight is filling fast, not enough time, raise price
  - LOWER   → flight is barely selling, need to stimulate demand
  - HOLD    → price is working, leave it alone
  - FLOOR   → price has drifted below floor, reset to floor

Claude reasons about:
  - Load factor vs days to departure (urgency)
  - Price relative to floor (margin headroom)
  - Route character (business vs leisure)
  - Our strategy: 1.70x hard cap, win by volume not margin

CONSTRAINTS (hardcoded, Claude cannot override)
───────────────────────────────────────────────
  - New price must be >= floor_inr (cardinal rule)
  - New price must be <= floor_inr * 1.70 (strategy cap)
  - Max single adjustment: ±20% per cycle
  - Flights departing in <2 hours: read-only, no changes

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.yield_manager

  Optional env vars:
    SCAN_INTERVAL=120    (seconds between scans, default 120)
    MAX_FLIGHTS=50       (flights per Claude call, default 50)
    DRY_RUN=true         (analyse but don't write to DB)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import motor.motor_asyncio

# ── Path bootstrap ────────────────────────────────────────────────────────────
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aerosync.yield_mgr")

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "120"))     # seconds
MAX_FLIGHTS       = int(os.getenv("MAX_FLIGHTS",   "50"))      # per Claude call
DRY_RUN           = os.getenv("DRY_RUN", "false").lower() == "true"
MODEL             = "claude-sonnet-4-20250514"

PRICE_CAP_MULT    = 1.40    # hard cap — matches economics engine
MAX_ADJ_PER_CYCLE = 0.20    # max ±20% per scan cycle

# ── Route character (for Claude's context) ────────────────────────────────────
BUSINESS_ROUTES = {
    frozenset({"DEL", "BOM"}), frozenset({"DEL", "MAA"}),
    frozenset({"BOM", "CCU"}), frozenset({"BOM", "MAA"}),
}


def route_type(origin: str, dest: str) -> str:
    return "BUSINESS" if frozenset({origin, dest}) in BUSINESS_ROUTES else "LEISURE"


# =============================================================================
# MONGO CLIENT
# =============================================================================

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


# =============================================================================
# REDIS PUBLISHER (standalone — no FastAPI app context needed)
# =============================================================================

async def publish_redis(channel: str, payload: dict) -> None:
    try:
        import redis.asyncio as aioredis
        r = await aioredis.from_url(
            settings.REDIS_URI,
            encoding="utf-8",
            decode_responses=True,
        )
        await r.publish(channel, json.dumps(payload))
        await r.aclose()
    except Exception as e:
        log.warning("Redis publish failed: %s", e)


# =============================================================================
# STEP 1 — FETCH FLIGHTS NEEDING ATTENTION
# =============================================================================

async def fetch_candidate_flights(db) -> list[dict]:
    """
    Pull scheduled flights that are worth the Yield Manager's attention.
    Filters out:
      - Departed / cancelled flights
      - Flights departing in <2 hours (too late to change prices)
      - Flights with zero seats capacity
    Sorts by urgency: (days_to_departure ASC, load_factor DESC)
    """
    today     = date.today()
    now_utc   = datetime.now(tz=timezone.utc)

    cursor = db["live_flights"].find(
        {"status": "scheduled"},
        {
            "_id": 1,
            "origin": 1,
            "destination": 1,
            "departure_date": 1,
            "slot": 1,
            "inventory": 1,
            "current_pricing": 1,
        }
    )

    flights   = []
    async for doc in cursor:
        inv   = doc.get("inventory") or {}
        cap   = inv.get("capacity", 0)
        sold  = inv.get("sold", 0)
        if cap <= 0:
            continue

        # Parse departure date
        dep_raw = doc.get("departure_date")
        try:
            if isinstance(dep_raw, datetime):
                dep_date = dep_raw.date()
            elif isinstance(dep_raw, date):
                dep_date = dep_raw
            else:
                dep_date = date.fromisoformat(str(dep_raw)[:10])
        except Exception:
            continue

        days_out = (dep_date - today).days
        if days_out < 0:
            continue          # already departed
        if days_out == 0:
            continue          # departing today — too late

        cp        = doc.get("current_pricing") or {}
        fare      = cp.get("ml_fare_inr", 0.0)
        floor     = cp.get("floor_inr", fare)
        lf        = sold / cap if cap > 0 else 0.0

        flights.append({
            "flight_id":    str(doc["_id"]),
            "origin":       doc.get("origin", ""),
            "destination":  doc.get("destination", ""),
            "departure":    dep_date.isoformat(),
            "days_out":     days_out,
            "slot":         doc.get("slot", "B"),
            "capacity":     cap,
            "sold":         sold,
            "available":    inv.get("available", cap - sold),
            "load_factor":  round(lf, 4),
            "fare_inr":     round(fare, 0),
            "floor_inr":    round(floor, 0),
            "ratio":        round(fare / floor, 3) if floor else 1.0,
            "route_type":   route_type(doc.get("origin",""), doc.get("destination","")),
            "cap_inr":      round(floor * PRICE_CAP_MULT, 0),
        })

    # Sort: close-in first, then by load factor descending
    flights.sort(key=lambda f: (f["days_out"], -f["load_factor"]))
    return flights[:MAX_FLIGHTS]


# =============================================================================
# STEP 2 — BUILD THE BRIEF FOR CLAUDE
# =============================================================================

def build_brief(flights: list[dict]) -> str:
    """
    Construct the structured prompt sent to Claude.
    Includes: airline strategy, constraints, flight table, decision format.
    """
    rows = []
    for f in flights:
        lf_pct = f["load_factor"] * 100
        rows.append(
            f"  {f['flight_id'][:28]:<28} | {f['origin']}->{f['destination']:<3} | "
            f"D+{f['days_out']:02d} | {f['route_type']:<8} | "
            f"LF {lf_pct:5.1f}% | "
            f"fare ₹{f['fare_inr']:>6,.0f} | floor ₹{f['floor_inr']:>6,.0f} | "
            f"ratio {f['ratio']:.3f} | cap ₹{f['cap_inr']:>6,.0f}"
        )
    table = "\n".join(rows)

    return f"""You are the AI Yield Manager for AeroSync-India, a fully AI-operated airline.

## OUR PRICING STRATEGY
- We win by volume, not margin. Lower fares than competitors to build trust.
- Hard price cap: 1.40× floor. We NEVER exceed this — even for last-minute seats.
- Target margins: 2–15% above floor on most flights.
- Business routes (DEL-BOM, DEL-MAA, BOM-CCU, BOM-MAA): demand is inelastic, flat pricing.
- Leisure routes (DEL-CCU, CCU-MAA): DOW-sensitive, price-elastic travellers.

## YOUR JOB
Analyse each flight below and decide the optimal new fare.
You must balance two competing goals:
  1. Fill seats (revenue = fare × seats sold, empty seat = zero revenue)
  2. Maximize revenue per seat (within our 1.40× cap)

## HARD CONSTRAINTS (non-negotiable)
- new_fare >= floor_inr (cardinal rule — never fly below cost)
- new_fare <= floor_inr × 1.40 (strategy cap — no gouging)
- Max change per cycle: ±20% of current fare
- If current fare is already optimal → HOLD (don't change)

## DECISION HEURISTICS
Load factor vs days-to-departure guidance:
  - LF >80%, D+1-7:   RAISE aggressively (near-full, last seats)
  - LF >60%, D+1-14:  RAISE moderately
  - LF >40%, D+15-30: HOLD or RAISE slightly
  - LF <20%, D+1-7:   LOWER significantly (need to move seats fast)
  - LF <20%, D+8-21:  LOWER slightly (still time, but stimulate)
  - LF <10%, D+22+:   LOWER to near-floor (early-bird pricing)
  - ratio > 1.50:      Consider LOWER unless LF is high
  - ratio < 1.02:      HOLD (already at floor, can't go lower)

## FLIGHT TABLE
  flight_id                     | route      | DTD  | type     | LF      | fare    | floor   | ratio | cap
{table}

## RESPONSE FORMAT
Respond with ONLY a JSON array. No explanation, no markdown, no preamble.
Each object must have exactly these fields:
  "flight_id": string (exact match from table)
  "action":    "RAISE" | "LOWER" | "HOLD" | "FLOOR"
  "new_fare":  number (INR, integer, must satisfy constraints above)
  "reason":    string (one concise sentence explaining why)

Example:
[
  {{"flight_id": "6E-201_A_2026-03-28", "action": "RAISE", "new_fare": 6200, "reason": "82% full with 5 days left, raise to capture last-minute premium."}},
  {{"flight_id": "6E-301_B_2026-04-15", "action": "LOWER", "new_fare": 5540, "reason": "Only 8% sold at D+23, drop to floor to stimulate early-bird demand."}}
]"""


# =============================================================================
# STEP 3 — CALL CLAUDE
# =============================================================================

async def call_claude(brief: str) -> list[dict]:
    """
    Send the brief to Claude and parse the JSON response.
    Returns list of decision dicts, empty list on failure.
    """
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set — cannot call Claude")
        return []

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":      MODEL,
        "max_tokens": 4096,
        "messages":   [{"role": "user", "content": brief}],
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        raw = data["content"][0]["text"].strip()

        # Strip markdown fences if Claude wraps in ```json
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        decisions = json.loads(raw)
        log.info("Claude returned %d pricing decisions", len(decisions))
        return decisions

    except json.JSONDecodeError as e:
        log.error("Claude response was not valid JSON: %s", e)
        log.debug("Raw response: %s", raw[:500])
        return []
    except Exception as e:
        log.error("Claude API call failed: %s", e)
        return []


# =============================================================================
# STEP 4 — VALIDATE + APPLY DECISIONS
# =============================================================================

def validate_decision(decision: dict, flight: dict) -> tuple[bool, str]:
    """
    Enforce hard constraints on Claude's decision before writing to DB.
    Returns (is_valid, reason_string).
    """
    action   = decision.get("action", "")
    new_fare = decision.get("new_fare", 0)
    floor    = flight["floor_inr"]
    fare     = flight["fare_inr"]
    cap      = flight["cap_inr"]

    if action == "HOLD":
        return True, "hold"

    if not isinstance(new_fare, (int, float)) or new_fare <= 0:
        return False, f"invalid new_fare: {new_fare}"

    new_fare = round(float(new_fare))

    if new_fare < floor:
        return False, f"below floor (₹{new_fare} < ₹{floor})"

    if new_fare > cap:
        return False, f"above cap (₹{new_fare} > ₹{cap})"

    max_raise = fare * (1 + MAX_ADJ_PER_CYCLE)
    min_lower = fare * (1 - MAX_ADJ_PER_CYCLE)

    if new_fare > max_raise:
        return False, f"exceeds max raise of 20% (₹{new_fare} > ₹{max_raise:.0f})"

    if new_fare < min_lower:
        return False, f"exceeds max lower of 20% (₹{new_fare} < ₹{min_lower:.0f})"

    return True, "ok"


async def apply_decisions(
    db,
    decisions:  list[dict],
    flight_map: dict[str, dict],
) -> tuple[int, int, int]:
    """
    Write valid decisions to MongoDB and publish PRICE_UPDATE events.
    Returns (applied, held, rejected) counts.
    """
    applied = held = rejected = 0

    for dec in decisions:
        fid    = dec.get("flight_id", "")
        action = dec.get("action", "HOLD")
        reason = dec.get("reason", "")

        flight = flight_map.get(fid)
        if not flight:
            log.warning("Decision for unknown flight_id: %s — skipping", fid)
            rejected += 1
            continue

        if action == "HOLD":
            log.info("HOLD  %s — %s", fid[:32], reason)
            held += 1
            continue

        if action == "FLOOR":
            new_fare = flight["floor_inr"]
        else:
            new_fare = round(float(dec.get("new_fare", flight["fare_inr"])))

        valid, msg = validate_decision({**dec, "new_fare": new_fare}, flight)
        if not valid:
            log.warning(
                "REJECTED %s [%s] → ₹%s — constraint: %s",
                fid[:32], action, new_fare, msg
            )
            rejected += 1
            continue

        old_fare = flight["fare_inr"]
        pct      = (new_fare - old_fare) / old_fare * 100 if old_fare else 0

        log.info(
            "%s  %s  ₹%s → ₹%s (%+.1f%%)  |  %s",
            action.ljust(5), fid[:32], f"{old_fare:,.0f}", f"{new_fare:,.0f}", pct, reason
        )

        if DRY_RUN:
            applied += 1
            continue

        # Write to MongoDB
        try:
            await db["live_flights"].update_one(
                {"_id": fid},
                {"$set": {
                    "current_pricing.ml_fare_inr": new_fare,
                    "last_repriced_by": "yield_manager",
                    "last_repriced_at": datetime.now(tz=timezone.utc),
                }}
            )
        except Exception as e:
            log.error("MongoDB write failed for %s: %s", fid, e)
            rejected += 1
            continue

        # Publish PRICE_UPDATE to Redis
        await publish_redis(
            settings.REDIS_BROADCAST_CHANNEL,
            {
                "event_type":  "PRICE_UPDATE",
                "flight_id":   fid,
                "old_fare":    old_fare,
                "new_fare":    new_fare,
                "action":      action,
                "reason":      reason,
                "agent":       "yield_manager",
                "timestamp":   datetime.now(tz=timezone.utc).isoformat(),
            }
        )

        applied += 1

    return applied, held, rejected


# =============================================================================
# MAIN SCAN LOOP
# =============================================================================

async def scan_cycle(db) -> None:
    """One full scan: fetch → brief → Claude → validate → apply."""
    log.info("─" * 60)
    log.info("Yield Manager scan starting...")

    flights = await fetch_candidate_flights(db)
    if not flights:
        log.info("No candidate flights found — nothing to do.")
        return

    log.info(
        "Analysing %d flights  (D+1 to D+%d, LF %.1f%%–%.1f%%)",
        len(flights),
        max(f["days_out"] for f in flights),
        min(f["load_factor"] for f in flights) * 100,
        max(f["load_factor"] for f in flights) * 100,
    )

    # Build a lookup map for validation
    flight_map = {f["flight_id"]: f for f in flights}

    brief     = build_brief(flights)
    decisions = await call_claude(brief)

    if not decisions:
        log.warning("No decisions received from Claude — skipping apply.")
        return

    applied, held, rejected = await apply_decisions(db, decisions, flight_map)

    log.info(
        "Scan complete — applied: %d  held: %d  rejected: %d%s",
        applied, held, rejected,
        "  [DRY RUN]" if DRY_RUN else "",
    )


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'\n"
            "  Then restart: python -m agents.yield_manager"
        )
        sys.exit(1)

    db = get_db()

    log.info("=" * 60)
    log.info("  AeroSync-India — AI Yield Manager")
    log.info("  Model    : %s", MODEL)
    log.info("  Interval : %ds", SCAN_INTERVAL)
    log.info("  Max flt  : %d per cycle", MAX_FLIGHTS)
    log.info("  Cap      : %.2fx floor", PRICE_CAP_MULT)
    log.info("  Dry run  : %s", DRY_RUN)
    log.info("=" * 60)

    while True:
        try:
            await scan_cycle(db)
        except Exception as e:
            log.error("Scan cycle error: %s", e, exc_info=True)

        log.info("Next scan in %ds. Ctrl+C to stop.\n", SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Yield Manager stopped.")


if __name__ == "__main__":
    main()
