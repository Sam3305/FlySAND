"""
backend/agents/finance_controller.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  AI Finance Controller
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
A Claude-powered CFO agent that computes real-time P&L for every route and
reports findings, flags problems, and makes recommendations.

Every SCAN_INTERVAL seconds it:
  1. Pulls all live_flights + bookings from MongoDB
  2. Computes per-flight P&L (actual revenue vs simulated cost floor)
  3. Rolls up to per-route P&L
  4. Sends a financial brief to Claude
  5. Claude produces a structured CFO report with:
     - Route-level profitability ranking
     - Margin warnings (routes flying below break-even)
     - Revenue leakage analysis (seats sold too cheap)
     - Recommendations (which routes need yield manager intervention)
  6. Saves report to MongoDB (finance_reports collection)
  7. Prints formatted report to terminal

P&L METHODOLOGY
────────────────
  Revenue per flight  = seats_sold × fare_charged_inr
  Cost per flight     = floor_inr × capacity  (full trip cost regardless of LF)

  Why floor × capacity?
  The floor IS the per-seat break-even at our target load factor (85.6%).
  If we sell fewer seats, we still pay the full trip cost.
  So actual cost = floor × capacity × (1/0.856) ... but since floor already
  embeds the LF assumption, we use: cost = floor × capacity as a conservative
  floor estimate. This slightly understates cost at low LF — which is fine,
  the agent should flag low-LF routes anyway.

  Contribution margin = Revenue - Cost
  Margin %            = Contribution margin / Revenue × 100

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.finance_controller

  Optional env vars:
    SCAN_INTERVAL=300    (seconds between reports, default 300)
    DRY_RUN=true         (don't save to DB)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
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
log = logging.getLogger("aerosync.finance")

# ── Config ────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "300"))
DRY_RUN           = os.getenv("DRY_RUN", "false").lower() == "true"
MODEL             = "claude-sonnet-4-20250514"

# ATF prices per city (INR/kl) — same as economics engine
ATF_PRICES = {
    "DEL": 92323, "BOM": 86352, "CCU": 95378,
    "MAA": 95770, "BLR": 91000, "HYD": 92000,
}

# Route distances (km)
ROUTE_DISTANCES = {
    frozenset({"DEL", "BOM"}): 1136,
    frozenset({"DEL", "CCU"}): 1305,
    frozenset({"DEL", "MAA"}): 1753,
    frozenset({"BOM", "CCU"}): 1660,
    frozenset({"BOM", "MAA"}):  843,
    frozenset({"CCU", "MAA"}): 1370,
}


def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


# =============================================================================
# STEP 1 — COMPUTE PER-FLIGHT P&L
# =============================================================================

def estimate_trip_cost(origin: str, dest: str, capacity: int, floor_inr: float) -> float:
    """
    Estimate full trip cost from the floor price.
    floor_inr = break_even_per_seat at 85.6% LF
    total_trip_cost ≈ floor × capacity × 0.856
    We use floor × capacity as a conservative proxy (slightly understates cost).
    """
    return floor_inr * capacity * 0.856


async def fetch_flight_pl(db) -> tuple[list[dict], dict]:
    """
    Returns:
      flight_pl: list of per-flight P&L records
      route_pl:  dict of route → aggregated P&L
    """
    today = date.today()

    # Fetch all flights with bookings
    flights_cursor = db["live_flights"].find(
        {"status": "scheduled", "inventory.sold": {"$gt": 0}},
        {
            "_id": 1, "origin": 1, "destination": 1,
            "departure_date": 1, "slot": 1,
            "inventory": 1, "current_pricing": 1,
        }
    )

    # Fetch all bookings grouped by flight
    booking_revenue: dict[str, float] = defaultdict(float)
    booking_count:   dict[str, int]   = defaultdict(int)

    async for bk in db["bookings"].find({}, {"flight_id": 1, "price_charged_inr": 1, "seats_booked": 1}):
        fid     = bk.get("flight_id", "")
        revenue = bk.get("price_charged_inr", 0) or 0
        seats   = bk.get("seats_booked", 1) or 1
        booking_revenue[fid] += revenue
        booking_count[fid]   += seats

    flight_pl  = []
    route_pl   = defaultdict(lambda: {
        "flights": 0, "revenue": 0.0, "cost": 0.0,
        "seats_sold": 0, "seats_capacity": 0,
    })

    async for fl in flights_cursor:
        fid   = str(fl["_id"])
        inv   = fl.get("inventory") or {}
        cp    = fl.get("current_pricing") or {}
        cap   = inv.get("capacity", 186)
        sold  = inv.get("sold", 0)
        fare  = cp.get("ml_fare_inr", 0.0)
        floor = cp.get("floor_inr", fare)

        origin = fl.get("origin", "")
        dest   = fl.get("destination", "")
        route  = f"{origin}-{dest}"

        # Revenue: use actual booking records if available, else estimate
        actual_revenue = booking_revenue.get(fid, 0.0)
        if actual_revenue == 0 and sold > 0:
            # Estimate from current fare × sold (no booking records for old data)
            actual_revenue = fare * sold

        trip_cost  = estimate_trip_cost(origin, dest, cap, floor)
        contrib    = actual_revenue - trip_cost
        margin_pct = (contrib / actual_revenue * 100) if actual_revenue > 0 else -999.0
        lf         = sold / cap if cap > 0 else 0.0

        # Departure date
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
            days_out = -1

        record = {
            "flight_id":      fid,
            "route":          route,
            "origin":         origin,
            "destination":    dest,
            "days_out":       days_out,
            "slot":           fl.get("slot", "B"),
            "capacity":       cap,
            "sold":           sold,
            "load_factor":    round(lf, 4),
            "fare_inr":       round(fare, 0),
            "floor_inr":      round(floor, 0),
            "revenue_inr":    round(actual_revenue, 0),
            "cost_inr":       round(trip_cost, 0),
            "contribution_inr": round(contrib, 0),
            "margin_pct":     round(margin_pct, 2),
        }
        flight_pl.append(record)

        rp = route_pl[route]
        rp["flights"]        += 1
        rp["revenue"]        += actual_revenue
        rp["cost"]           += trip_cost
        rp["seats_sold"]     += sold
        rp["seats_capacity"] += cap
        rp["origin"]          = origin
        rp["destination"]     = dest

    # Finalise route P&L
    for route, rp in route_pl.items():
        rev  = rp["revenue"]
        cost = rp["cost"]
        rp["contribution"] = rev - cost
        rp["margin_pct"]   = round((rev - cost) / rev * 100, 2) if rev > 0 else -999.0
        rp["avg_lf"]       = round(rp["seats_sold"] / rp["seats_capacity"] * 100, 1) if rp["seats_capacity"] > 0 else 0.0
        rp["revenue"]      = round(rev, 0)
        rp["cost"]         = round(cost, 0)
        rp["contribution"] = round(rp["contribution"], 0)

    return flight_pl, dict(route_pl)


# =============================================================================
# STEP 2 — BUILD BRIEF FOR CLAUDE
# =============================================================================

def build_brief(flight_pl: list[dict], route_pl: dict) -> str:
    # Sort routes by contribution descending
    routes_sorted = sorted(
        route_pl.items(),
        key=lambda x: x[1]["contribution"],
        reverse=True,
    )

    route_rows = []
    for route, rp in routes_sorted:
        margin_flag = ""
        if rp["margin_pct"] < 0:     margin_flag = " ⚠ LOSS"
        elif rp["margin_pct"] < 5:   margin_flag = " ⚠ THIN"
        route_rows.append(
            f"  {route:<10} | flights: {rp['flights']:>3} | "
            f"LF: {rp['avg_lf']:>5.1f}% | "
            f"rev: ₹{rp['revenue']:>12,.0f} | "
            f"cost: ₹{rp['cost']:>12,.0f} | "
            f"margin: {rp['margin_pct']:>+7.1f}%{margin_flag}"
        )

    # Worst flights by margin
    loss_flights = sorted(
        [f for f in flight_pl if f["margin_pct"] < 5],
        key=lambda x: x["margin_pct"]
    )[:10]

    loss_rows = []
    for f in loss_flights:
        loss_rows.append(
            f"  {f['flight_id'][:28]:<28} | {f['route']:<10} | "
            f"D+{f['days_out']:02d} | LF {f['load_factor']*100:>5.1f}% | "
            f"margin {f['margin_pct']:>+7.1f}% | "
            f"rev ₹{f['revenue_inr']:>8,.0f} | cost ₹{f['cost_inr']:>8,.0f}"
        )

    total_rev  = sum(rp["revenue"] for rp in route_pl.values())
    total_cost = sum(rp["cost"] for rp in route_pl.values())
    total_cont = total_rev - total_cost
    system_margin = total_cont / total_rev * 100 if total_rev > 0 else 0

    return f"""You are the AI Finance Controller for AeroSync-India.

## AIRLINE CONTEXT
- Fully AI-operated LCC on India's Golden Quadrilateral (DEL/BOM/CCU/MAA)
- Strategy: win by volume, not margin. Target 5-15% contribution margin.
- 1,080 flights seeded (30-day horizon), currently {len(flight_pl)} with bookings.
- System load factor: {sum(f['load_factor'] for f in flight_pl)/len(flight_pl)*100:.1f}% average on booked flights.

## SYSTEM P&L SUMMARY
  Total Revenue:      ₹{total_rev:>14,.0f}
  Total Cost:         ₹{total_cost:>14,.0f}
  Contribution:       ₹{total_cont:>14,.0f}
  System Margin:      {system_margin:>+.1f}%

## ROUTE P&L TABLE (sorted by contribution)
{chr(10).join(route_rows)}

## WORST-MARGIN FLIGHTS (margin < 5%)
{chr(10).join(loss_rows) if loss_rows else "  None — all flights above 5% margin."}

## YOUR TASK
As CFO, produce a structured financial report with:

1. EXECUTIVE SUMMARY (2-3 sentences on overall financial health)
2. ROUTE RANKING (rank routes: star performers, acceptable, problem routes)
3. MARGIN WARNINGS (specific flights/routes flying below break-even or dangerously thin)
4. REVENUE LEAKAGE (are we pricing too cheap on high-LF flights? quantify the lost revenue)
5. RECOMMENDATIONS (3-5 specific, actionable items for the Yield Manager and operations)

## RESPONSE FORMAT
Respond with a JSON object with exactly these keys:
{{
  "executive_summary": "string",
  "route_ranking": {{
    "star":    ["route1", "route2"],
    "acceptable": ["route3"],
    "problem": ["route4", "route5"]
  }},
  "margin_warnings": [
    {{"flight_id": "...", "route": "...", "issue": "...", "severity": "HIGH|MEDIUM|LOW"}}
  ],
  "revenue_leakage": {{
    "estimated_inr": number,
    "explanation": "string"
  }},
  "recommendations": [
    {{"priority": 1, "action": "string", "expected_impact": "string"}}
  ],
  "overall_health": "HEALTHY|CAUTION|CRITICAL"
}}"""


# =============================================================================
# STEP 3 — CALL CLAUDE
# =============================================================================

async def call_claude(brief: str) -> dict | None:
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set")
        return None

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type":      "application/json",
    }
    body = {
        "model":      MODEL,
        "max_tokens": 2048,
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
            raw = resp.json()["content"][0]["text"].strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        return json.loads(raw)

    except Exception as e:
        log.error("Claude call failed: %s", e)
        return None


# =============================================================================
# STEP 4 — FORMAT + SAVE REPORT
# =============================================================================

def print_report(report: dict, route_pl: dict) -> None:
    health = report.get("overall_health", "UNKNOWN")
    health_icon = {"HEALTHY": "✅", "CAUTION": "⚠️ ", "CRITICAL": "🔴"}.get(health, "❓")

    print()
    print("=" * 70)
    print(f"  AeroSync-India  |  Finance Controller Report")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  Status: {health_icon} {health}")
    print("=" * 70)

    print()
    print("EXECUTIVE SUMMARY")
    print("-" * 70)
    print(" ", report.get("executive_summary", "N/A"))

    print()
    print("ROUTE RANKING")
    print("-" * 70)
    ranking = report.get("route_ranking", {})
    if ranking.get("star"):
        print("  ⭐ Star:      ", ", ".join(ranking["star"]))
    if ranking.get("acceptable"):
        print("  ✅ Acceptable:", ", ".join(ranking["acceptable"]))
    if ranking.get("problem"):
        print("  🔴 Problem:   ", ", ".join(ranking["problem"]))

    warnings = report.get("margin_warnings", [])
    if warnings:
        print()
        print("MARGIN WARNINGS")
        print("-" * 70)
        for w in warnings[:8]:
            sev_icon = {"HIGH": "🔴", "MEDIUM": "⚠️ ", "LOW": "ℹ️ "}.get(w.get("severity",""), "")
            print(f"  {sev_icon} {w.get('route',''):<10} {w.get('flight_id','')[:28]:<28} — {w.get('issue','')}")

    leakage = report.get("revenue_leakage", {})
    if leakage:
        print()
        print("REVENUE LEAKAGE")
        print("-" * 70)
        print(f"  Estimated loss: ₹{leakage.get('estimated_inr', 0):,.0f}")
        print(f"  {leakage.get('explanation', '')}")

    recs = report.get("recommendations", [])
    if recs:
        print()
        print("RECOMMENDATIONS")
        print("-" * 70)
        for r in recs:
            print(f"  [{r.get('priority','')}] {r.get('action','')}")
            print(f"      → Expected: {r.get('expected_impact','')}")

    print()
    print("=" * 70)


async def save_report(db, report: dict, route_pl: dict, flight_pl: list) -> None:
    if DRY_RUN:
        return
    doc = {
        "generated_at":  datetime.now(tz=timezone.utc),
        "overall_health": report.get("overall_health"),
        "executive_summary": report.get("executive_summary"),
        "route_ranking":  report.get("route_ranking"),
        "margin_warnings": report.get("margin_warnings"),
        "revenue_leakage": report.get("revenue_leakage"),
        "recommendations": report.get("recommendations"),
        "route_pl_snapshot": route_pl,
        "flights_analysed": len(flight_pl),
        "total_revenue": sum(f["revenue_inr"] for f in flight_pl),
        "total_cost":    sum(f["cost_inr"] for f in flight_pl),
    }
    await db["finance_reports"].insert_one(doc)
    log.info("Report saved to finance_reports collection")


# =============================================================================
# MAIN LOOP
# =============================================================================

async def scan_cycle(db) -> None:
    log.info("─" * 60)
    log.info("Finance Controller scan starting...")

    flight_pl, route_pl = await fetch_flight_pl(db)

    if not flight_pl:
        log.info("No flights with bookings found — nothing to report.")
        return

    total_rev  = sum(f["revenue_inr"] for f in flight_pl)
    total_cost = sum(f["cost_inr"] for f in flight_pl)
    log.info(
        "Analysing %d flights | Revenue ₹%s | Cost ₹%s | Margin %.1f%%",
        len(flight_pl),
        f"{total_rev:,.0f}",
        f"{total_cost:,.0f}",
        (total_rev - total_cost) / total_rev * 100 if total_rev else 0,
    )

    brief  = build_brief(flight_pl, route_pl)
    report = await call_claude(brief)

    if not report:
        log.warning("No report received from Claude.")
        return

    print_report(report, route_pl)
    await save_report(db, report, route_pl, flight_pl)


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'\n"
            "  Then restart: python -m agents.finance_controller"
        )
        sys.exit(1)

    db = get_db()

    log.info("=" * 60)
    log.info("  AeroSync-India — AI Finance Controller")
    log.info("  Model    : %s", MODEL)
    log.info("  Interval : %ds", SCAN_INTERVAL)
    log.info("  Dry run  : %s", DRY_RUN)
    log.info("=" * 60)

    while True:
        try:
            await scan_cycle(db)
        except Exception as e:
            log.error("Scan error: %s", e, exc_info=True)

        log.info("Next report in %ds. Ctrl+C to stop.\n", SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("Finance Controller stopped.")


if __name__ == "__main__":
    main()
