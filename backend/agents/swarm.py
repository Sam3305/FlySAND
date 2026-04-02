"""
backend/agents/swarm.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Autobooking Agent Swarm
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
Runs a pool of autonomous booking agents that continuously scan live_flights
and book seats, simulating realistic passenger demand curves:

DEMAND MODEL
────────────
Booking behaviour is governed by two axes:

  1. Days-to-flight (temporal urgency)
     Far out (>21d)   → Very few bookings. Only the most price-insensitive
                        early birds. Long sleep intervals between attempts.
     Mid-range (7–21d)→ Gradual ramp. Leisure travellers, families planning.
     Near-term (3–7d) → Business travellers enter. Pace accelerates sharply.
     Last-minute (<3d)→ Panic bookings + latecomers. Highest pace.

  2. Student price-sensitivity
     Each agent has a personal PRICE_CEILING (INR) drawn from a realistic
     distribution:
       - 40% of agents are "budget students": ceiling ₹4,500 — will only book
         if ml_fare_inr is below their ceiling. Skip otherwise.
       - 35% are "mid-range leisure": ceiling ₹7,000
       - 25% are "price-insensitive business": ceiling ₹15,000 (always books)

     This means cheap early-seeded fares fill faster; expensive flights on
     high-demand dates fill much more slowly — exactly like real LCC demand.

PACING MECHANICS
────────────────
  - Each agent sleeps for a random interval drawn from a Poisson distribution
    whose mean is determined by days_to_flight:

      days > 21  : mean sleep = 180–480 s  (1 booking attempt per 3–8 min)
      days 7–21  : mean sleep = 60–180 s   (1 booking attempt per 1–3 min)
      days 3–7   : mean sleep = 20–60 s    (1 booking attempt per 20–60 s)
      days < 3   : mean sleep = 5–20 s     (near-real-time panic bookings)

  - Agents book 1 seat at a time (students don't bulk-book).
  - A 30% random skip chance adds organic irregularity.
  - Lock contention (HTTP 409) triggers a short back-off, not a crash.

CONCURRENCY
───────────
  N_AGENTS (default 12) coroutines run concurrently via asyncio.gather.
  They share a single aiohttp ClientSession for connection pooling.
  The booking endpoint's Redis lock handles race conditions server-side.

USAGE
─────
  From backend/ with venv activated:
    python -m agents.swarm

  With custom agent count:
    N_AGENTS=20 python -m agents.swarm

  Stop cleanly with Ctrl+C.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

# ── Path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aerosync.swarm")

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE    = os.getenv("API_BASE",  "http://localhost:8000")
N_AGENTS    = int(os.getenv("N_AGENTS", "100"))
FLIGHTS_URL = f"{API_BASE}/api/v1/flights"
BOOK_URL    = f"{API_BASE}/api/v1/book"


# =============================================================================
# DEMAND MODEL — market willingness-to-pay predictor
# =============================================================================

_demand_model   = None
_demand_scaler  = None
_demand_meta    = None
_demand_ready   = False

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DM_MODEL  = _REPO_ROOT / "ml_pricing/artifacts/demand_model.ubj"
_DM_SCALER = _REPO_ROOT / "ml_pricing/artifacts/demand_scaler.pkl"
_DM_META   = _REPO_ROOT / "ml_pricing/artifacts/demand_meta.json"

_GQ_PAIRS = {
    frozenset({"Delhi","Mumbai"}),   frozenset({"Delhi","Kolkata"}),
    frozenset({"Delhi","Chennai"}),  frozenset({"Mumbai","Kolkata"}),
    frozenset({"Mumbai","Chennai"}), frozenset({"Kolkata","Chennai"}),
}
_IATA_TO_CITY = {"DEL":"Delhi","BOM":"Mumbai","CCU":"Kolkata","MAA":"Chennai"}
_DEP_HOUR    = {"A": 6, "B": 12, "C": 18}

def _load_demand_model() -> bool:
    global _demand_model, _demand_scaler, _demand_meta, _demand_ready
    if _demand_ready:
        return True
    if not _DM_MODEL.exists():
        logger.warning("Demand model not found — using hardcoded ceilings. "
                       "Run: python -m ml_pricing.demand_model")
        return False
    try:
        import xgboost as xgb, joblib, json as _json, numpy as _np
        _demand_model = xgb.XGBRegressor()
        _demand_model.load_model(str(_DM_MODEL))
        _demand_scaler = joblib.load(str(_DM_SCALER))
        with open(_DM_META) as f:
            _demand_meta = _json.load(f)
        _demand_ready = True
        logger.info("Demand model loaded — agents now use market willingness-to-pay")
        return True
    except Exception as e:
        logger.warning("Demand model load failed: %s — hardcoded ceilings", e)
        return False


def predict_willingness(
    origin: str, destination: str,
    days_left: int, slot: str,
    is_economy: bool = True,
    floor_price: float = 5500.0,
) -> float:
    """
    Predict the willingness-to-pay ratio for this booking context.
    Returns: ratio such that agent books if current_fare <= floor * ratio.

    Falls back to hardcoded ratios if model not available.
    """
    import numpy as _np

    origin_city = _IATA_TO_CITY.get(origin, origin)
    dest_city   = _IATA_TO_CITY.get(destination, destination)
    dep_hr      = _DEP_HOUR.get(slot, 12)
    is_gq       = int(frozenset({origin_city, dest_city}) in _GQ_PAIRS)
    dow         = days_left % 7

    if not _demand_ready or _demand_meta is None:
        # Hardcoded fallback ratios by days_left bucket
        if days_left <= 3:    return 1.68
        elif days_left <= 7:  return 1.17
        elif days_left <= 21: return 1.00
        else:                 return 1.10
    try:
        numeric_vals = [
            days_left,
            1.8,                               # duration_hrs proxy
            # stops_numeric removed — nonstop only
            int(is_economy),
            is_gq,
            dep_hr,
            int(6 <= dep_hr <= 9),             # is_morning
            int(17 <= dep_hr <= 20),           # is_evening
            int(dep_hr >= 21),                 # is_night
            dow,
            int(dow in {4, 5, 6}),             # is_weekend
            floor_price,
        ]
        vocabs = _demand_meta.get("cat_vocabs", {})
        def enc(col, val):
            v = vocabs.get(col, [])
            try:    return float(v.index(val))
            except: return -1.0
        cat_vals = [enc("source_city", origin_city), enc("destination_city", dest_city)]

        row    = _np.array(numeric_vals + cat_vals, dtype=float).reshape(1, -1)
        n_num  = len(_demand_meta["numeric_features"])
        row[0, :n_num] = _demand_scaler.transform(row[:, :n_num])[0]
        ratio  = float(_np.expm1(_demand_model.predict(row)[0]))
        return max(ratio, 1.0)   # never book below floor
    except Exception as e:
        logger.debug("Demand model inference error: %s", e)
        return 1.10


# =============================================================================
# DEMAND CURVE — days-to-flight → sleep interval range (seconds)
# =============================================================================

def sleep_range(days: int) -> tuple[float, float]:
    """
    Returns (min_sleep, max_sleep) in seconds for a given days-to-flight.
    Intervals are long far out (sparse demand) and short near departure
    (surge bookings). Values are calibrated so a 180-seat A321neo takes
    roughly 3–4 simulated days to fill on a high-demand route — realistic
    for IndiGo's ~85% load factor target.
    """
    if days > 21:
        return (180.0, 480.0)   # Very sparse — early birds only
    elif days > 14:
        return (90.0,  240.0)   # Starting to pick up
    elif days > 7:
        return (40.0,  120.0)   # Leisure travellers entering
    elif days > 3:
        return (12.0,   40.0)   # Business + last-minute leisure
    else:
        return (3.0,    15.0)   # Panic zone — near departure


def poisson_sleep(days: int) -> float:
    """
    Sample a sleep duration from an exponential distribution (memoryless /
    Poisson process) whose mean is the midpoint of sleep_range(days).
    Clipped to the [min, max] bounds so outliers don't stall the swarm.
    """
     

    lo, hi   = sleep_range(days)
    mean     = (lo + hi) / 2.0
    # Exponential distribution: -mean * ln(uniform)
    sample   = -mean * math.log(max(random.random(), 1e-9))
    return max(lo, min(hi * 2, sample))


# =============================================================================
# AGENT PERSONALITY — market-driven willingness distribution
# =============================================================================
# Each persona samples at a different quantile of the real market distribution
# learned from 300,153 Indian airline bookings across 6 airlines.
# willingness_mult is applied ON TOP of the demand model prediction.

PERSONALITY_DIST = [
    # (weight, label, willingness_mult, seats, dtd_pref)
    (0.40, "STUDENT",  0.78, 1, "far"),    # price-sensitive, books far-out
    (0.35, "LEISURE",  1.00, 1, "mid"),    # median market behaviour
    (0.25, "BUSINESS", 1.35, 2, "close"),  # inelastic, books close-in
]

def pick_personality() -> tuple[str, float, int, str]:
    """Returns (label, willingness_mult, seats_to_book, dtd_pref)."""
    r = random.random()
    cumulative = 0.0
    for weight, label, mult, seats, dtd in PERSONALITY_DIST:
        cumulative += weight
        if r <= cumulative:
            personal_mult = mult * (1.0 + random.uniform(-0.10, 0.10))
            return label, personal_mult, seats, dtd
    last = PERSONALITY_DIST[-1]
    return last[1], last[2], last[3], last[4]


# =============================================================================
# FLIGHT FETCHER
# =============================================================================

async def fetch_flights(
    session:  aiohttp.ClientSession,
    origin:   str,
    dest:     str,
    dep_date: str,
) -> list[dict[str, Any]]:
    """Fetch scheduled flights for one OD-pair + date from the API."""
    try:
        async with session.get(
            FLIGHTS_URL,
            params={"origin": origin, "destination": dest, "departure_date": dep_date},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                return []
            return await resp.json()
    except Exception as exc:
        logger.debug("fetch_flights error %s→%s %s: %s", origin, dest, dep_date, exc)
        return []


# =============================================================================
# SINGLE BOOKING ATTEMPT
# =============================================================================

async def attempt_booking(
    session:    aiohttp.ClientSession,
    agent_id:   str,
    flight_id:  str,
    seats:      int,
) -> dict[str, Any] | None:
    """
    POST /api/v1/book for one flight.
    Returns the response dict on success, None on any failure.
    """
    payload = {
        "flight_id":        flight_id,
        "passenger_id":     agent_id,
        "seats_requested":  seats,
        "idempotency_key":  f"{agent_id}-{flight_id}-{int(datetime.now(tz=timezone.utc).timestamp())}",
    }
    try:
        async with session.post(
            BOOK_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            data = await resp.json()
            if resp.status == 201:
                return data
            elif resp.status == 409:
                logger.debug("%s lock contention on %s — will retry", agent_id, flight_id)
            elif resp.status == 422:
                reason = (data.get("detail") or {}).get("reason", "rejected")
                logger.debug("%s booking rejected for %s: %s", agent_id, flight_id, reason)
            else:
                logger.debug("%s unexpected status %d for %s", agent_id, resp.status, flight_id)
    except Exception as exc:
        logger.debug("%s booking error for %s: %s", agent_id, flight_id, exc)
    return None


# =============================================================================
# ROUTE POOL — all 12 GQ directional routes
# =============================================================================

GQ_ROUTES = [
    ("DEL", "BOM"), ("BOM", "DEL"),
    ("DEL", "CCU"), ("CCU", "DEL"),
    ("DEL", "MAA"), ("MAA", "DEL"),
    ("BOM", "CCU"), ("CCU", "BOM"),
    ("BOM", "MAA"), ("MAA", "BOM"),
    ("CCU", "MAA"), ("MAA", "CCU"),
]


# =============================================================================
# SINGLE AGENT COROUTINE
# =============================================================================

async def agent_loop(agent_idx: int, session: aiohttp.ClientSession) -> None:
    """
    One autonomous booking agent.

    Each iteration:
      1. Pick a random route from the GQ pool.
      2. Pick a random departure date from the next 30 days,
         weighted toward near-future (more likely to pick closer dates).
      3. Fetch available flights for that route + date.
      4. Filter flights this agent can afford (price ceiling check).
      5. If nothing affordable → skip, sleep, retry.
      6. Pick one flight, book it, log the result.
      7. Sleep for poisson_sleep(days_to_flight) before next attempt.
    """
    agent_id = f"AGENT_{agent_idx:03d}"
    label, willingness_mult, seats, dtd_pref = pick_personality()

    # Load demand model once at agent start
    _load_demand_model()

    logger.info(
        "Agent %s started — type=%s willingness=%.2fx seats=%d dtd=%s",
        agent_id, label, willingness_mult, seats, dtd_pref,
    )

    today = date.today()

    while True:
        try:
            # ── 1. Pick route ─────────────────────────────────────────────────
            origin, dest = random.choice(GQ_ROUTES)

            # ── 2. Pick date — biased by persona DTD preference ───────────────
            from datetime import timedelta
            if dtd_pref == "close":
                # Business: beta skewed very close-in (peaks D+2-4)
                raw_offset = int(random.betavariate(1.0, 6.0) * 14) + 1
            elif dtd_pref == "far":
                # Student: beta skewed far-out (peaks D+18-25)
                raw_offset = int(random.betavariate(2.0, 1.5) * 29) + 1
            else:
                # Leisure: original distribution (peaks D+5-8)
                raw_offset = int(random.betavariate(1.5, 4.0) * 29) + 1
            day_offset   = max(1, min(30, raw_offset))
            dep_date_obj = today + timedelta(days=day_offset)
            dep_date_str = dep_date_obj.strftime("%Y-%m-%d")
            days_to_flt  = day_offset

            # ── 3. Random skip (organic irregularity) ────────────────────────
            if random.random() < 0.30:
                await asyncio.sleep(poisson_sleep(days_to_flt) * 0.5)
                continue

            # ── 4. Fetch flights ──────────────────────────────────────────────
            flights = await fetch_flights(session, origin, dest, dep_date_str)
            if not flights:
                await asyncio.sleep(poisson_sleep(days_to_flt))
                continue

            # ── 5. Filter by market willingness-to-pay (model-driven) ─────────
            # For each flight, ask the demand model:
            # "Given this context, what ratio above floor is a real traveller
            #  willing to pay?" Then apply persona multiplier on top.
            affordable = []
            for f in flights:
                if f.get("status") != "scheduled":
                    continue
                if (f.get("inventory") or {}).get("available", 0) < seats:
                    continue
                cp    = f.get("current_pricing") or {}
                fare  = cp.get("ml_fare_inr", 999_999)
                floor = cp.get("floor_inr", fare)
                if floor <= 0:
                    continue
                slot = (f.get("flight_id") or "").split("_")[1] if "_" in (f.get("flight_id") or "") else "B"
                # Market willingness × persona multiplier = personal ceiling
                market_ratio  = predict_willingness(
                    origin=origin, destination=dest,
                    days_left=days_to_flt, slot=slot,
                    floor_price=floor,
                )
                personal_ceil = floor * market_ratio * willingness_mult
                if fare <= personal_ceil:
                    affordable.append(f)

            if not affordable:
                logger.info(
                    "%s [%s] nothing within willingness %s→%s D+%d",
                    agent_id, label, origin, dest, days_to_flt,
                )
                await asyncio.sleep(poisson_sleep(days_to_flt))
                continue

            # ── 6. Pick one flight and book ───────────────────────────────────
            target = random.choice(affordable)

            # flight_id is set by flights.py (_id renamed); fall back to _id
            flight_id = target.get("flight_id") or str(target.get("_id", ""))
            if not flight_id:
                logger.debug("%s could not resolve flight_id from doc keys: %s",
                             agent_id, list(target.keys()))
                await asyncio.sleep(poisson_sleep(days_to_flt))
                continue

            fare      = (target.get("current_pricing") or {}).get("ml_fare_inr", 0)
            available = (target.get("inventory") or {}).get("available", 0)

            result = await attempt_booking(session, agent_id, flight_id, seats)

            if result:
                remaining = result.get("seats_remaining", "?")
                logger.info(
                    "✅  %s [%s] BOOKED %s  %s→%s  D+%02d  ₹%.0f/seat  "
                    "seats_left=%s  ref=%s",
                    agent_id, label, flight_id, origin, dest,
                    days_to_flt, fare, remaining, result.get("booking_ref", "?"),
                )
            else:
                logger.debug(
                    "%s [%s] booking failed for %s — will retry later",
                    agent_id, label, flight_id,
                )

            # ── 7. Sleep (demand curve pacing) ────────────────────────────────
            sleep_s = poisson_sleep(days_to_flt)
            logger.debug("%s sleeping %.1fs (D+%d)", agent_id, sleep_s, days_to_flt)
            await asyncio.sleep(sleep_s)

        except asyncio.CancelledError:
            logger.info("%s shutting down.", agent_id)
            return
        except Exception as exc:
            logger.warning("%s unexpected error: %s — continuing", agent_id, exc,
                           exc_info=True)
            await asyncio.sleep(5)


# =============================================================================
# SWARM CONTROLLER
# =============================================================================

async def run_swarm() -> None:
    """
    Spawn N_AGENTS concurrent booking agents and run until Ctrl+C.
    All agents share one aiohttp ClientSession (connection pooling).
    """
    logger.info("=" * 64)
    logger.info("AeroSync-India Autobooking Swarm")
    logger.info("Agents: %d  |  API: %s", N_AGENTS, API_BASE)
    logger.info("")
    logger.info("Demand model:")
    logger.info("  Days >21  → sleep 3–8 min/attempt  (sparse early-bird)")
    logger.info("  Days 7–21 → sleep 1–3 min/attempt  (leisure ramp)")
    logger.info("  Days 3–7  → sleep 20–60s/attempt   (business surge)")
    logger.info("  Days <3   → sleep 3–15s/attempt    (last-minute panic)")
    logger.info("")
    logger.info("Agent mix (market demand model):")
    for _, label, mult, seats, dtd in PERSONALITY_DIST:
        logger.info("  %-10s willingness=%.2fx  seats=%d  prefers=%s",
                    label, mult, seats, dtd)
    logger.info("=" * 64)

    # Verify API is reachable before spawning agents
    try:
        async with aiohttp.ClientSession() as probe:
            async with probe.get(
                f"{API_BASE}/health",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    raise ConnectionError(f"API health check failed: {resp.status}")
        logger.info("✅  API reachable at %s", API_BASE)
    except Exception as exc:
        logger.critical("Cannot reach API at %s: %s", API_BASE, exc)
        logger.critical("Make sure uvicorn app.main:app is running first.")
        sys.exit(1)

    connector = aiohttp.TCPConnector(limit=N_AGENTS + 100)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [
            asyncio.create_task(agent_loop(i, session))
            for i in range(N_AGENTS)
        ]
        logger.info("Swarm running — Ctrl+C to stop\n")
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("All agents stopped. Swarm shut down.")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main() -> None:
    try:
        asyncio.run(run_swarm())
    except KeyboardInterrupt:
        logger.info("Swarm interrupted by user.")


if __name__ == "__main__":
    main()
