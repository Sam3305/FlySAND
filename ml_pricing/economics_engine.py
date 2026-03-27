"""
economics_engine.py  (STUB — replace with your actual engine import)
=====================================================================
This file documents the expected interface contract of the existing
economics engine so the pipeline can be tested before the real module
is wired in.

The real engine should expose exactly:

    generate_market_fares(market_context: dict) -> dict

Where the return dict contains AT MINIMUM:
    {
        "simulated_base_cost_inr":  float,  # physical cost floor (> 0)
        "event_demand_multiplier":  float,  # demand scalar (> 0, typically 0.8 – 3.0)
    }

Replace this file (or shadow it on PYTHONPATH) with your real implementation.
"""

from __future__ import annotations

import random
import math


# ── Stub constants ────────────────────────────────────────────────────────────

_BASE_COST_BY_ROUTE: dict[frozenset, float] = {
    frozenset({"Delhi",   "Mumbai"}):  2_800.0,
    frozenset({"Delhi",   "Kolkata"}): 3_100.0,
    frozenset({"Delhi",   "Chennai"}): 3_400.0,
    frozenset({"Mumbai",  "Kolkata"}): 3_600.0,
    frozenset({"Mumbai",  "Chennai"}): 2_500.0,
    frozenset({"Kolkata", "Chennai"}): 3_700.0,
}
_DEFAULT_BASE_COST = 2_600.0


def generate_market_fares(market_context: dict) -> dict:
    """
    STUB implementation — simulates economics-engine output for development.

    Physical cost model
    -------------------
    base_cost = route_base
              + duration_minutes × 4.5 INR/min  (fuel proxy)
              + stops × 400 INR  (ground handling)

    Demand model
    ------------
    multiplier is driven by days_to_departure on a 1/log curve:
        • < 3  days → ~2.0x  (last-minute surge)
        • 7    days → ~1.5x
        • 30   days → ~1.1x
        • > 90 days → ~0.95x (advance booking discount)
    Plus a ±5% random jitter to simulate event / season noise.

    Parameters
    ----------
    market_context : dict with keys matching data_fusion.py payload schema

    Returns
    -------
    dict with 'simulated_base_cost_inr' and 'event_demand_multiplier'
    """
    origin      = market_context.get("origin", "Unknown")
    destination = market_context.get("destination", "Unknown")
    days        = int(market_context.get("days_to_departure", 30))
    stops       = int(market_context.get("stops", 1))
    duration    = int(market_context.get("duration_minutes", 90))
    is_gq       = int(market_context.get("is_golden_quad", 0))

    # ── Physical cost floor ───────────────────────────────────────────────────
    route_key  = frozenset({origin, destination})
    route_base = _BASE_COST_BY_ROUTE.get(route_key, _DEFAULT_BASE_COST)
    base_cost  = route_base + duration * 4.5 + stops * 400
    if is_gq:
        base_cost *= 1.05          # GQ routes carry slot premium

    # ── Demand multiplier ─────────────────────────────────────────────────────
    days_safe   = max(days, 1)
    curve       = 1.0 + 0.8 / math.log(days_safe + 1.5)  # 1/log decay
    jitter      = 1.0 + random.uniform(-0.05, 0.05)        # ±5% noise
    multiplier  = round(curve * jitter, 4)

    return {
        "simulated_base_cost_inr": round(base_cost, 2),
        "event_demand_multiplier": multiplier,
    }
