"""
app/engines/economics_engine.py
Economics Engine — recalculates the price floor given market conditions.

This module is called synchronously (via asyncio.to_thread) from the game-loop.
Replace / extend the logic here with your real demand-curve or cost model.
"""

import logging
import math

logger = logging.getLogger("orchestrator.economics")

# Base operating-cost floor per seat (USD) — replace with DB/config-driven value
BASE_COST_FLOOR_USD: float = 80.0

# Disruption surcharge multiplier per unit of severity
SEVERITY_SURCHARGE_FACTOR: float = 0.25  # 25 % uplift per severity unit

# Regional risk premiums (IATA region codes)
REGION_RISK_PREMIUM: dict[str, float] = {
    "NA": 0.05,   # North America
    "EU": 0.07,
    "APAC": 0.10,
    "ME": 0.15,   # Middle East
    "AF": 0.20,
    "UNKNOWN": 0.08,
}


def recalculate_floor(
    *,
    flight_id: str,
    current_price: float,
    severity: float,
    region: str = "UNKNOWN",
) -> float:
    """
    Calculate the minimum acceptable seat price given a weather disruption.

    Parameters
    ----------
    flight_id    : Identifier used for logging / audit.
    current_price: Current published price (USD).
    severity     : Weather severity on [0.0, 1.0] scale.
    region       : IATA region code of the affected airspace.

    Returns
    -------
    floor_price  : Minimum price (USD) that should be charged.
    """
    region_key = region.upper() if region.upper() in REGION_RISK_PREMIUM else "UNKNOWN"
    risk_premium = REGION_RISK_PREMIUM[region_key]

    # Disruption surcharge scales non-linearly with severity
    disruption_surcharge = BASE_COST_FLOOR_USD * SEVERITY_SURCHARGE_FACTOR * math.exp(severity)

    # Floor = base costs + regional risk uplift + disruption premium
    floor = BASE_COST_FLOOR_USD * (1 + risk_premium) + disruption_surcharge

    # The floor must never *lower* the current price (one-way ratchet)
    floor = max(floor, current_price * 0.85)  # allow max 15 % downward relief

    logger.debug(
        "economics_engine: flight=%s severity=%.2f region=%s → floor=$%.2f",
        flight_id,
        severity,
        region,
        floor,
    )
    return round(floor, 2)
