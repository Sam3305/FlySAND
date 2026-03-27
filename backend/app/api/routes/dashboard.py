"""
app/api/routes/dashboard.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Dashboard API endpoints
──────────────────────────────────────────────────────────────────────────────

GET /api/v1/dashboard/stats   — system-level KPIs from live_flights + bookings
GET /api/v1/reports/finance   — latest Finance Controller report
GET /api/v1/reports/network   — latest Network Planner report
GET /api/v1/reports/fuel      — latest Fuel Procurement report
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.db import get_database

logger = logging.getLogger("orchestrator.dashboard")
router = APIRouter()


# ── /api/v1/dashboard/stats ───────────────────────────────────────────────────

@router.get("/dashboard/stats", status_code=status.HTTP_200_OK)
async def get_dashboard_stats() -> dict[str, Any]:
    """
    System-wide KPIs computed live from MongoDB.
    Used by the AOCC dashboard stats strip.
    """
    try:
        db = get_database()

        # ── Flight inventory stats ──────────────────────────────────────────
        flights_cursor = db["live_flights"].find(
            {},
            {"inventory": 1, "status": 1, "origin": 1, "destination": 1,
             "current_pricing": 1}
        )
        flights = await flights_cursor.to_list(length=None)

        total_flights  = len(flights)
        total_capacity = sum(f.get("inventory", {}).get("capacity", 0) for f in flights)
        total_sold     = sum(f.get("inventory", {}).get("sold", 0) for f in flights)
        system_lf      = round(total_sold / total_capacity * 100, 1) if total_capacity else 0.0

        # Route count
        routes = set(
            f"{f.get('origin','')}-{f.get('destination','')}" for f in flights
        )

        # ── Booking revenue stats ───────────────────────────────────────────
        bookings_cursor = db["bookings"].find(
            {},
            {"price_charged_inr": 1, "seats_booked": 1, "price_to_floor_ratio": 1}
        )
        bookings = await bookings_cursor.to_list(length=None)

        total_bookings = len(bookings)
        total_revenue  = sum(b.get("price_charged_inr", 0) or 0 for b in bookings)

        # Estimated cost: floor × capacity × 0.856 per flight
        total_cost = sum(
            (f.get("current_pricing", {}).get("floor_inr", 0) or 0)
            * (f.get("inventory", {}).get("capacity", 0) or 0)
            * 0.856
            for f in flights
            if f.get("inventory", {}).get("sold", 0) > 0
        )

        contribution = total_revenue - total_cost
        margin_pct   = round(contribution / total_revenue * 100, 1) if total_revenue else 0.0

        # ── Report availability flags ───────────────────────────────────────
        has_finance = await db["finance_reports"].count_documents({}) > 0
        has_network = await db["network_reports"].count_documents({}) > 0
        has_fuel    = await db["fuel_reports"].count_documents({}) > 0

        return {
            "total_flights":    total_flights,
            "total_capacity":   total_capacity,
            "total_sold":       total_sold,
            "system_lf_pct":    system_lf,
            "active_routes":    len(routes),
            "total_bookings":   total_bookings,
            "total_revenue_inr": round(total_revenue, 0),
            "total_cost_inr":   round(total_cost, 0),
            "contribution_inr": round(contribution, 0),
            "margin_pct":       margin_pct,
            "reports": {
                "finance": has_finance,
                "network": has_network,
                "fuel":    has_fuel,
            },
        }

    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("dashboard/stats error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /api/v1/reports/finance ───────────────────────────────────────────────────

@router.get("/reports/finance", status_code=status.HTTP_200_OK)
async def get_latest_finance_report() -> dict[str, Any]:
    """Latest Finance Controller report from MongoDB."""
    try:
        db  = get_database()
        doc = await db["finance_reports"].find_one(
            {}, sort=[("generated_at", -1)]
        )
        if not doc:
            return {"available": False}
        doc.pop("_id", None)
        doc["available"] = True
        # Convert datetime to ISO string
        if "generated_at" in doc:
            doc["generated_at"] = doc["generated_at"].isoformat()
        return doc
    except Exception as exc:
        logger.exception("reports/finance error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /api/v1/reports/network ───────────────────────────────────────────────────

@router.get("/reports/network", status_code=status.HTTP_200_OK)
async def get_latest_network_report() -> dict[str, Any]:
    """Latest Network Planner report from MongoDB."""
    try:
        db  = get_database()
        doc = await db["network_reports"].find_one(
            {}, sort=[("generated_at", -1)]
        )
        if not doc:
            return {"available": False}
        doc.pop("_id", None)
        doc["available"] = True
        if "generated_at" in doc:
            doc["generated_at"] = doc["generated_at"].isoformat()
        return doc
    except Exception as exc:
        logger.exception("reports/network error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /api/v1/reports/fuel ─────────────────────────────────────────────────────

@router.get("/reports/fuel", status_code=status.HTTP_200_OK)
async def get_latest_fuel_report() -> dict[str, Any]:
    """Latest Fuel Procurement report from MongoDB."""
    try:
        db  = get_database()
        doc = await db["fuel_reports"].find_one(
            {}, sort=[("generated_at", -1)]
        )
        if not doc:
            return {"available": False}
        doc.pop("_id", None)
        doc["available"] = True
        if "generated_at" in doc:
            doc["generated_at"] = doc["generated_at"].isoformat()
        return doc
    except Exception as exc:
        logger.exception("reports/fuel error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── /api/v1/reports/cfo-briefing ─────────────────────────────────────────────

@router.get("/reports/cfo-briefing", status_code=status.HTTP_200_OK)
async def get_latest_cfo_briefing() -> dict[str, Any]:
    """Latest CFO Dashboard Narrator briefing from MongoDB."""
    try:
        db  = get_database()
        doc = await db["cfo_briefings"].find_one(
            {}, sort=[("generated_at", -1)]
        )
        if not doc:
            return {"available": False}
        doc.pop("_id", None)
        doc.pop("stats_snapshot", None)
        doc["available"] = True
        if "generated_at" in doc:
            doc["generated_at"] = doc["generated_at"].isoformat()
        return doc
    except Exception as exc:
        logger.exception("reports/cfo-briefing error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
