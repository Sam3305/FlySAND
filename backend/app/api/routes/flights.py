"""
app/api/routes/flights.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  GET /api/v1/flights — Live Flight Read Endpoint
──────────────────────────────────────────────────────────────────────────────

Query the ``live_flights`` MongoDB collection.  Supports optional filtering by
origin, destination, and departure_date so the B2C portal and the Agent Swarm
can both narrow their search without full-collection scans.

Index assumption (enforced by mongo_manager.py or an Atlas index policy):
    Compound index on  (origin, destination, departure_date, status)
    guarantees sub-10 ms reads for the expected 1,080-doc collection size.

Projection:
    ``_id`` is excluded from every response document.  The ``flight_id`` field
    (promoted from ``_id`` on write) is the canonical client-side identifier.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status

from app.core.db import get_database

logger = logging.getLogger("orchestrator.flights")

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schema (lightweight — avoids re-importing the full Pydantic model
# just for a read endpoint; motor returns raw dicts which FastAPI serialises).
# ---------------------------------------------------------------------------

@router.get(
    "/flights",
    summary="List live flights",
    description=(
        "Returns scheduled and active flights from the ``live_flights`` collection. "
        "Optionally filter by ``origin``, ``destination``, and / or ``departure_date``."
    ),
    response_description="Array of live flight documents (``_id`` excluded).",
    status_code=status.HTTP_200_OK,
)
async def list_flights(
    origin: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=3,
            description="IATA origin airport code, e.g. 'DEL'",
        ),
    ] = None,
    destination: Annotated[
        str | None,
        Query(
            min_length=3,
            max_length=3,
            description="IATA destination airport code, e.g. 'BOM'",
        ),
    ] = None,
    departure_date: Annotated[
        str | None,
        Query(
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="ISO-8601 departure date, e.g. '2026-10-16'",
        ),
    ] = None,
) -> list[dict[str, Any]]:
    """
    Fetch flights from MongoDB with optional query-parameter filters.

    Filter logic:
    - Supplying none of the three parameters returns all documents (up to 1,080
      for the default 30-day seed horizon).
    - All supplied filters are ANDed together.
    - ``origin`` and ``destination`` are normalised to uppercase before matching.

    Returns:
        A (possibly empty) list of raw flight documents.  Each document matches
        the ``LiveFlight`` schema minus the ``_id`` field.

    Raises:
        HTTP 500 if the Motor query itself fails.
    """

    # ── Build MongoDB filter ─────────────────────────────────────────────────
    mongo_filter: dict[str, Any] = {}

    if origin is not None:
        mongo_filter["origin"] = origin.upper()

    if destination is not None:
        mongo_filter["destination"] = destination.upper()

    if departure_date is not None:
        mongo_filter["departure_date"] = departure_date

    # ── Execute query ────────────────────────────────────────────────────────
    try:
        collection = get_database()["live_flights"]

        # Exclude MongoDB's internal _id; flight_id is the canonical identifier.
        cursor = collection.find(
            filter=mongo_filter,
            projection={"_id": 1, "origin": 1, "destination": 1,
                        "departure_date": 1, "departure_time": 1,
                        "status": 1, "inventory": 1, "current_pricing": 1,
                        "physics_snapshot": 1, "slot": 1, "route": 1},
        )

        raw: list[dict[str, Any]] = await cursor.to_list(length=None)

        # Rename _id → flight_id so the frontend can use it for booking
        flights = []
        for doc in raw:
            doc["flight_id"] = str(doc.pop("_id"))
            flights.append(doc)

    except RuntimeError as exc:
        # get_database() raises RuntimeError when Motor client is uninitialised
        logger.error("DB not ready when querying live_flights: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "DB_NOT_READY",
                "message": "MongoDB client is not initialised. The service may be starting up.",
            },
        )

    except Exception as exc:
        logger.exception("Unexpected error querying live_flights: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "QUERY_FAILED",
                "message": str(exc),
            },
        )

    logger.debug(
        "list_flights filter=%s → %d result(s)", mongo_filter, len(flights)
    )

    return flights
