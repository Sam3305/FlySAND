"""
pipeline/daily_seeder.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Daily Flight Inventory Seeder
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
Runs as a cron job (see cron_seeder.sh) every day at 02:00 IST.
Seeds the next 30 departure days × 12 routes × 3 daily slots = 1,080 docs.

PIPELINE PER DOCUMENT
──────────────────────
 1. AeroPhysicsEngine.calculate_physical_flight(days_to_flight=N)
      → day-specific weather (Open-Meteo forecast <=14d, archive >14d)
      → thermodynamic density, thrust lapse, phase-split fuel burn
      → output stored as the immutable PhysicsSnapshot in the Mongo document
 2. AirlineEconomicsEngine.generate_market_fares(days_to_flight=N)
      → internally: calculate_trip_economics() → ICAO nav + airport tariffs
        + load-factor-adjusted break-even (CARDINAL FLOOR)
      → internally: EventOracle.get_market_signals() → festival demand mult
      → returns floor_inr and final_dynamic_price_inr directly
 3. LiveFlight Pydantic validation (Cardinal Rule enforced as final guard)
 4. MongoDB bulk-upsert via MongoManager

ARCHITECTURE RULES
──────────────────
- Import the existing services; NEVER rewrite them.
- AeroPhysicsEngine is instantiated ONCE and injected into AirlineEconomicsEngine
  via the physics= parameter — eliminates the hidden double-init overhead.
- AirlineEconomicsEngine owns EventOracle internally; seeder does not
  instantiate or manage oracle separately.
- days_to_flight is passed through to both engine calls so weather is
  consistent between the physics snapshot and the cost floor calculation.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# PATH BOOTSTRAP
# Supports both `python pipeline/daily_seeder.py` (cron) and
# `python -m pipeline.daily_seeder` (module) invocation styles.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# ENGINE IMPORTS — existing services (DO NOT MODIFY these files)
# ---------------------------------------------------------------------------
from backend.app.services.physics_engine   import AeroPhysicsEngine       # noqa: E402
from backend.app.services.economics_engine import AirlineEconomicsEngine  # noqa: E402
# EventOracle is instantiated internally by AirlineEconomicsEngine —
# the seeder no longer manages it directly.

# ---------------------------------------------------------------------------
# DATABASE IMPORTS
# ---------------------------------------------------------------------------
from database.models import (                                          # noqa: E402
    CurrentPricing,
    DepartureSlot,
    FlightInventory,
    FlightPhases,
    FlightStatus,
    LiveFlight,
    PhysicsSnapshot,
    ThermoMetrics,
)
from database.mongo_manager import MongoManager                       # noqa: E402

# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("aerosync.daily_seeder")


# ===========================================================================
# SEEDER CONSTANTS
# ===========================================================================

SEED_HORIZON_DAYS: int = 30         # seed D+1 through D+30
DEFAULT_AIRCRAFT_MODEL = "A320neo"  # openap_service fleet_map key
# NOTE: fixed_taxes_and_fees and base_profit_margin are read from the
# AirlineEconomicsEngine instance after init — not redeclared here.
# Single source of truth lives in economics_engine.py.

# Three daily departure waves per route
# (departure_time_IST, DepartureSlot enum)
DEPARTURE_SLOTS: list[tuple[str, DepartureSlot]] = [
    ("06:00", DepartureSlot.MORNING),
    ("12:30", DepartureSlot.AFTERNOON),
    ("18:00", DepartureSlot.EVENING),
]

# IndiGo-style flight number per route-key
# route_key = f"{origin}_{destination}"
ROUTE_FLIGHT_NUMBERS: dict[str, str] = {
    "DEL_BOM": "6E-101",
    "BOM_DEL": "6E-102",
    "DEL_CCU": "6E-201",
    "CCU_DEL": "6E-202",
    "DEL_MAA": "6E-301",
    "MAA_DEL": "6E-302",
    "BOM_CCU": "6E-401",
    "CCU_BOM": "6E-402",
    "BOM_MAA": "6E-501",
    "MAA_BOM": "6E-502",
    "CCU_MAA": "6E-601",
    "MAA_CCU": "6E-602",
}

# All 12 directional routes in the Golden Quadrilateral
GOLDEN_QUADRILATERAL_ROUTES: list[tuple[str, str]] = [
    ("DEL", "BOM"), ("BOM", "DEL"),
    ("DEL", "CCU"), ("CCU", "DEL"),
    ("DEL", "MAA"), ("MAA", "DEL"),
    ("BOM", "CCU"), ("CCU", "BOM"),
    ("BOM", "MAA"), ("MAA", "BOM"),
    ("CCU", "MAA"), ("MAA", "CCU"),
]


# ===========================================================================
# PYDANTIC DOCUMENT BUILDER
# ===========================================================================

def build_physics_snapshot(physics_output: dict[str, Any]) -> PhysicsSnapshot:
    """
    Map AeroPhysicsEngine.calculate_physical_flight() output to PhysicsSnapshot.

    Physics engine return shape (physics_engine.py):
    ─────────────────────────────────────────────────
    {
      "route":               "DEL-BOM",
      "distance_km":         1136.82,
      "aircraft_icao":       "A20N",
      "pax_capacity":        161,
      "flight_phases": {
          "climb_fuel_kg":           xxx,
          "cruise_fuel_kg":          xxx,
          "descent_fuel_kg":         xxx,
          "ground_and_hold_fuel_kg": xxx
      },
      "block_time_hrs":      2.123,
      "total_fuel_burn_kg":  4250.5,
      "thermodynamic_metrics": {
          "calculated_rho_kg_m3":   xxx,
          "density_ratio":          xxx,
          "v_ground_kph":           xxx,
          "actual_flight_time_hrs": xxx,
          "total_burn_multiplier":  xxx,
          "atc_holding_time_mins":  xxx
      }
    }
    """
    p = physics_output
    ph = p["flight_phases"]
    th = p["thermodynamic_metrics"]

    return PhysicsSnapshot(
        aircraft_icao=p["aircraft_icao"],
        distance_km=p["distance_km"],
        block_time_hrs=p["block_time_hrs"],
        total_fuel_burn_kg=p["total_fuel_burn_kg"],
        flight_phases=FlightPhases(
            climb_fuel_kg=ph["climb_fuel_kg"],
            cruise_fuel_kg=ph["cruise_fuel_kg"],
            descent_fuel_kg=ph["descent_fuel_kg"],
            ground_and_hold_fuel_kg=ph["ground_and_hold_fuel_kg"],
        ),
        thermodynamic_metrics=ThermoMetrics(
            calculated_rho_kg_m3=th["calculated_rho_kg_m3"],
            density_ratio=th["density_ratio"],
            v_ground_kph=th["v_ground_kph"],
            actual_flight_time_hrs=th["actual_flight_time_hrs"],
            total_burn_multiplier=th["total_burn_multiplier"],
            atc_holding_time_mins=int(th["atc_holding_time_mins"]),
        ),
    )


def build_flight_document(
    origin:             str,
    destination:        str,
    departure_date_obj: date,
    slot_time:          str,
    slot_enum:          DepartureSlot,
    days_to_flight:     int,
    physics_engine:     AeroPhysicsEngine,
    economics_engine:   AirlineEconomicsEngine,
    now_utc:            datetime,
) -> LiveFlight | None:
    """
    Build one LiveFlight document for a single route-slot-date triple.

    Two engine calls per document:
      1. physics_engine.calculate_physical_flight()  → PhysicsSnapshot only
         (thermodynamic audit trail stored immutably in the Mongo document)
      2. economics_engine.generate_market_fares()    → pricing only
         (internally runs calculate_trip_economics + EventOracle in one call)

    Both calls receive the same days_to_flight so weather is consistent
    between the snapshot and the cost floor.

    Returns None on any exception — caller logs WARNING and continues seeding.
    Pydantic model_validator enforces the Cardinal Rule as the final guard.
    """
    route_key  = f"{origin}_{destination}"
    route_str  = f"{origin}-{destination}"
    date_str   = departure_date_obj.strftime("%Y-%m-%d")
    flight_num = ROUTE_FLIGHT_NUMBERS[route_key]
    flight_id  = f"{flight_num}_{slot_enum.value}_{date_str}"

    try:
        # STEP 1: Physics — day-specific atmospheric conditions ───────────────
        # days_to_flight drives Open-Meteo weather selection:
        #   <= 14  →  forecast API  (real weather, high accuracy)
        #   >  14  →  archive API   (historical proxy from same date last year)
        # Output is stored as the immutable PhysicsSnapshot in the document.
        physics = physics_engine.calculate_physical_flight(
            origin=origin,
            destination=destination,
            model_name=DEFAULT_AIRCRAFT_MODEL,
            extra_payload_kg=0.0,
            days_to_flight=days_to_flight,
        )
        pax_capacity: int = physics["pax_capacity"]

        # STEP 2: Market fares — cost floor + demand signal in one call ────────
        # generate_market_fares() now correctly:
        #   - Runs calculate_trip_economics(days_to_flight=N) for ICAO-accurate
        #     cost floor using real airport tariffs and 85.6% load factor
        #   - Calls self.oracle.get_market_signals() for demand multiplier
        #   - Applies correct 13.5% margin (base_profit_margin = 0.135)
        #   - Enforces Cardinal Rule: final_price >= floor_inr
        #   - Returns floor_inr and final_dynamic_price_inr directly
        market_fares = economics_engine.generate_market_fares(
            origin=origin,
            destination=destination,
            model_name=DEFAULT_AIRCRAFT_MODEL,
            flight_date=date_str,
            days_to_flight=days_to_flight,
        )
        pricing      = market_fares["pricing_breakdown"]
        floor_inr:   float = pricing["floor_inr"]
        ml_fare_inr: float = pricing["final_dynamic_price_inr"]
        demand_multiplier: float = pricing["demand_multiplier"]

        # STEP 3: Pydantic model — validators re-enforce all invariants ────────
        flight = LiveFlight(
            flight_id=flight_id,
            route=route_str,
            origin=origin,
            destination=destination,
            departure_date=date_str,
            departure_time=slot_time,
            slot=slot_enum,
            status=FlightStatus.SCHEDULED,
            inventory=FlightInventory(
                capacity=pax_capacity,
                sold=0,
                available=pax_capacity,
            ),
            current_pricing=CurrentPricing(
                floor_inr=floor_inr,
                ml_fare_inr=ml_fare_inr,
            ),
            physics_snapshot=build_physics_snapshot(physics),
            seeded_at=now_utc,
            last_updated=now_utc,
        )

        logger.debug(
            "OK %-22s | floor=Rs%6.0f | fare=Rs%6.0f | margin=%5.1f%% | "
            "demand=%.3f | fuel=%6.0fkg | block=%.2fh",
            flight_id,
            floor_inr,
            ml_fare_inr,
            flight.current_pricing.margin_pct,
            demand_multiplier,
            physics["total_fuel_burn_kg"],
            physics["block_time_hrs"],
        )
        return flight

    except Exception as exc:
        logger.warning(
            "SKIP %s on %s slot-%s: %s",
            route_str, date_str, slot_enum.value, exc,
            exc_info=True,
        )
        return None


# ===========================================================================
# MAIN ASYNC SEEDER
# ===========================================================================

async def run_seeder() -> dict[str, Any]:
    """
    Core async seeder.

    Flow:
        connect MongoDB → init engine singletons → generate documents →
        bulk-upsert → health check → disconnect → return summary

    Idempotency: uses UpdateOne(upsert=True) on flight_id (_id).
    Re-running on the same day refreshes pricing/physics; no duplicates created.
    """
    run_start = time.perf_counter()
    now_utc   = datetime.now(tz=timezone.utc)
    today     = date.today()

    expected_count = (
        len(GOLDEN_QUADRILATERAL_ROUTES) * len(DEPARTURE_SLOTS) * SEED_HORIZON_DAYS
    )

    logger.info("=" * 72)
    logger.info("AeroSync-India Daily Seeder — %s UTC", now_utc.isoformat())
    logger.info(
        "Seeding D+1 to D+%d from %s | Expected: %d documents",
        SEED_HORIZON_DAYS, today, expected_count,
    )
    logger.info("=" * 72)

    # ── MongoDB ──────────────────────────────────────────────────────────────
    await MongoManager.connect()

    # ── Engine singletons (instantiate ONCE — not inside the loop) ───────────
    # PERFORMANCE FIX: physics_engine is created first, then INJECTED into
    # AirlineEconomicsEngine via the physics= parameter. This eliminates the
    # hidden second AeroPhysicsEngine.__init__() that ran inside the economics
    # engine's own __init__, which loaded 3 JSON config files and queried the
    # OpenAP DB a second time (~80ms wasted per seeder run).
    #
    # EventOracle is owned internally by AirlineEconomicsEngine (self.oracle).
    # The seeder no longer instantiates or manages it separately.
    logger.info("Initialising engine singletons (once per run)...")
    physics_engine   = AeroPhysicsEngine()
    economics_engine = AirlineEconomicsEngine(physics=physics_engine)
    logger.info("Engines ready.")

    # ── Document generation loop ─────────────────────────────────────────────
    flight_docs:  list[dict[str, Any]] = []
    build_errors: int                  = 0
    total_attempted: int               = 0

    for day_offset in range(1, SEED_HORIZON_DAYS + 1):
        dep_date       = today + timedelta(days=day_offset)
        days_to_flight = day_offset

        for origin, destination in GOLDEN_QUADRILATERAL_ROUTES:
            for slot_time, slot_enum in DEPARTURE_SLOTS:
                total_attempted += 1

                flight = build_flight_document(
                    origin=origin,
                    destination=destination,
                    departure_date_obj=dep_date,
                    slot_time=slot_time,
                    slot_enum=slot_enum,
                    days_to_flight=days_to_flight,
                    physics_engine=physics_engine,
                    economics_engine=economics_engine,
                    now_utc=now_utc,
                )

                if flight is not None:
                    flight_docs.append(flight.to_mongo_dict())
                else:
                    build_errors += 1

        # Progress checkpoint every 5 days
        if day_offset % 5 == 0:
            logger.info(
                "Progress: %d/%d days done — %d docs built, %d errors.",
                day_offset, SEED_HORIZON_DAYS, len(flight_docs), build_errors,
            )

    success_rate = (len(flight_docs) / max(total_attempted, 1)) * 100
    logger.info(
        "Generation complete: %d built / %d attempted (%.1f%% success, %d errors).",
        len(flight_docs), total_attempted, success_rate, build_errors,
    )

    if not flight_docs:
        logger.error("Zero documents built — aborting MongoDB write.")
        await MongoManager.disconnect()
        return {
            "status":       "failed",
            "reason":       "All document builds failed. Check engine and weather service logs.",
            "build_errors": build_errors,
        }

    # ── MongoDB bulk upsert ──────────────────────────────────────────────────
    logger.info("Writing %d documents to MongoDB...", len(flight_docs))
    upsert_result = await MongoManager.bulk_upsert_flights(flight_docs)

    # ── Health check ─────────────────────────────────────────────────────────
    health = await MongoManager.health_check()

    # ── Teardown ─────────────────────────────────────────────────────────────
    await MongoManager.disconnect()

    elapsed_s = time.perf_counter() - run_start
    docs_per_sec = len(flight_docs) / elapsed_s if elapsed_s > 0 else 0

    summary = {
        "status":              "success",
        "run_date_utc":        now_utc.isoformat(),
        "seed_horizon_days":   SEED_HORIZON_DAYS,
        "routes_seeded":       len(GOLDEN_QUADRILATERAL_ROUTES),
        "slots_per_route":     len(DEPARTURE_SLOTS),
        "total_attempted":     total_attempted,
        "documents_built":     len(flight_docs),
        "build_errors":        build_errors,
        "mongo_upserted":      upsert_result["upserted"],
        "mongo_modified":      upsert_result["modified"],
        "mongo_errors":        upsert_result.get("errors", 0),
        "total_in_db_after":   health.get("total_flights"),
        "scheduled_in_db":     health.get("scheduled_flights"),
        "elapsed_seconds":     round(elapsed_s, 2),
        "docs_per_second":     round(docs_per_sec, 1),
    }

    logger.info("=" * 72)
    logger.info("SEEDER COMPLETE")
    for k, v in summary.items():
        logger.info("  %-26s: %s", k, v)
    logger.info("=" * 72)

    return summary


# ===========================================================================
# ENTRY POINT
# ===========================================================================

def main() -> None:
    """Synchronous entry point for cron invocation."""
    try:
        summary = asyncio.run(run_seeder())
        if summary.get("status") != "success":
            logger.error("Seeder ended with non-success status.")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Seeder interrupted.")
        sys.exit(0)
    except Exception as exc:
        logger.critical("FATAL: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()