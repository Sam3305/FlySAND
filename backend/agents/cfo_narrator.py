"""
backend/agents/cfo_narrator.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  CFO Dashboard Narrator
──────────────────────────────────────────────────────────────────────────────

Combines all agent reports (Finance Controller, Network Planner, Fuel
Procurement) plus live dashboard KPIs into a single daily written
executive briefing.

Every SCAN_INTERVAL seconds it:
  1. Fetches the latest finance_reports, network_reports, fuel_reports
  2. Fetches live dashboard stats from MongoDB
  3. Builds a combined brief and sends it to Claude
  4. Claude produces a narrative daily briefing
  5. Saves the briefing to cfo_briefings collection

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.cfo_narrator
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import motor.motor_asyncio
from dotenv import load_dotenv

load_dotenv()

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aerosync.cfo_narrator")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "600"))
DRY_RUN           = os.getenv("DRY_RUN", "false").lower() == "true"
MODEL             = "claude-sonnet-4-20250514"


def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


# =============================================================================
# STEP 1 — GATHER ALL REPORTS + STATS
# =============================================================================

async def gather_inputs(db) -> dict:
    finance = await db["finance_reports"].find_one({}, sort=[("generated_at", -1)])
    network = await db["network_reports"].find_one({}, sort=[("generated_at", -1)])
    fuel    = await db["fuel_reports"].find_one({}, sort=[("generated_at", -1)])

    flights = await db["live_flights"].find(
        {}, {"inventory": 1, "current_pricing": 1, "status": 1, "origin": 1, "destination": 1}
    ).to_list(length=None)

    bookings = await db["bookings"].find(
        {}, {"price_charged_inr": 1, "seats_booked": 1}
    ).to_list(length=None)

    total_flights  = len(flights)
    total_capacity = sum(f.get("inventory", {}).get("capacity", 0) for f in flights)
    total_sold     = sum(f.get("inventory", {}).get("sold", 0) for f in flights)
    system_lf      = round(total_sold / total_capacity * 100, 1) if total_capacity else 0.0
    routes         = set(f"{f.get('origin','')}-{f.get('destination','')}" for f in flights)
    total_bookings = len(bookings)
    total_revenue  = sum(b.get("price_charged_inr", 0) or 0 for b in bookings)

    total_cost = sum(
        (f.get("current_pricing", {}).get("floor_inr", 0) or 0)
        * (f.get("inventory", {}).get("capacity", 0) or 0)
        * 0.856
        for f in flights
        if f.get("inventory", {}).get("sold", 0) > 0
    )

    contribution = total_revenue - total_cost
    margin_pct   = round(contribution / total_revenue * 100, 1) if total_revenue else 0.0

    def clean_doc(doc):
        if not doc:
            return None
        doc.pop("_id", None)
        if "generated_at" in doc and hasattr(doc["generated_at"], "isoformat"):
            doc["generated_at"] = doc["generated_at"].isoformat()
        if "route_pl_snapshot" in doc:
            doc.pop("route_pl_snapshot", None)
        return doc

    return {
        "stats": {
            "total_flights": total_flights,
            "total_capacity": total_capacity,
            "total_sold": total_sold,
            "system_lf_pct": system_lf,
            "active_routes": len(routes),
            "total_bookings": total_bookings,
            "total_revenue_inr": round(total_revenue),
            "total_cost_inr": round(total_cost),
            "contribution_inr": round(contribution),
            "margin_pct": margin_pct,
        },
        "finance_report": clean_doc(finance),
        "network_report": clean_doc(network),
        "fuel_report":    clean_doc(fuel),
    }


# =============================================================================
# STEP 2 — BUILD BRIEF FOR CLAUDE
# =============================================================================

def fmt_inr(n: float) -> str:
    if n >= 1_00_00_000:
        return f"₹{n/1_00_00_000:.1f}Cr"
    if n >= 1_00_000:
        return f"₹{n/1_00_000:.1f}L"
    return f"₹{n:,.0f}"


def build_brief(inputs: dict) -> str:
    s = inputs["stats"]
    fin = inputs["finance_report"]
    net = inputs["network_report"]
    fuel = inputs["fuel_report"]

    # Finance section
    fin_section = "No finance report available yet."
    if fin:
        fin_section = f"""Finance Controller Report (generated: {fin.get('generated_at', 'unknown')}):
  Overall Health: {fin.get('overall_health', 'UNKNOWN')}
  Executive Summary: {fin.get('executive_summary', 'N/A')}
  Route Ranking: Star={fin.get('route_ranking', {}).get('star', [])}, Problem={fin.get('route_ranking', {}).get('problem', [])}
  Revenue Leakage: {fmt_inr(fin.get('revenue_leakage', {}).get('estimated_inr', 0))} — {fin.get('revenue_leakage', {}).get('explanation', 'N/A')}
  Flights Analysed: {fin.get('flights_analysed', 0)}
  Total Revenue: {fmt_inr(fin.get('total_revenue', 0))}
  Total Cost: {fmt_inr(fin.get('total_cost', 0))}
  Recommendations: {json.dumps(fin.get('recommendations', []), indent=2)}"""

    # Network section
    net_section = "No network report available yet."
    if net:
        net_section = f"""Network Planner Report (generated: {net.get('generated_at', 'unknown')}):
  Executive Summary: {net.get('executive_summary', 'N/A')}
  Network Efficiency: {net.get('network_efficiency_score', {}).get('score', '?')}/10
  Frequency Decisions: {json.dumps(net.get('frequency_decisions', []), indent=2)}
  Growth Opportunities: {json.dumps(net.get('growth_opportunities', []), indent=2)}
  System LF: {net.get('system_lf_pct', 0)}%"""

    # Fuel section
    fuel_section = "No fuel report available yet."
    if fuel:
        fuel_section = f"Fuel Procurement Report (generated: {fuel.get('generated_at', 'unknown')}): {json.dumps({k: v for k, v in fuel.items() if k not in ('_id', 'generated_at')}, default=str, indent=2)}"

    return f"""You are the CFO Dashboard Narrator for AeroSync-India, a fully AI-operated LCC airline.

Your job is to write a DAILY EXECUTIVE BRIEFING that synthesizes all agent reports into one coherent narrative. Write as a senior finance executive would — clear, decisive, and action-oriented.

## LIVE DASHBOARD KPIs
  Total Flights:    {s['total_flights']}
  System Load:      {s['system_lf_pct']}%
  Active Routes:    {s['active_routes']}
  Total Bookings:   {s['total_bookings']:,}
  Total Revenue:    {fmt_inr(s['total_revenue_inr'])}
  Total Cost:       {fmt_inr(s['total_cost_inr'])}
  Contribution:     {fmt_inr(s['contribution_inr'])}
  Margin:           {s['margin_pct']:+.1f}%

## AGENT REPORTS

### FINANCE CONTROLLER
{fin_section}

### NETWORK PLANNER
{net_section}

### FUEL PROCUREMENT
{fuel_section}

## YOUR TASK
Write a cohesive daily briefing with these exact sections. Use natural, authoritative language — not bullet points or JSON.

Respond with ONLY a JSON object. No markdown, no explanation.
{{
  "headline": "One-sentence health verdict for the airline today (max 15 words)",
  "financial_snapshot": "2-3 paragraph narrative about revenue, cost, margin, and financial health. Include specific numbers.",
  "route_performance": "2-3 paragraphs about which routes are performing and which need intervention. Be specific about route codes.",
  "network_intelligence": "1-2 paragraphs synthesizing network planner insights on frequency, aircraft, and growth.",
  "risk_flags": "1-2 paragraphs about revenue leakage, margin warnings, and any urgent risks.",
  "recommendations": "3-5 numbered actionable recommendations for today, written as complete sentences.",
  "overall_health": "HEALTHY | CAUTION | CRITICAL"
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
                    "max_tokens": 3000,
                    "messages":   [{"role": "user", "content": brief}],
                },
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
# STEP 4 — SAVE BRIEFING
# =============================================================================

def print_briefing(briefing: dict) -> None:
    health = briefing.get("overall_health", "UNKNOWN")
    icon = {"HEALTHY": "✅", "CAUTION": "⚠️ ", "CRITICAL": "🔴"}.get(health, "❓")

    print()
    print("=" * 70)
    print(f"  AeroSync-India  |  CFO Daily Briefing")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  {icon} {health}")
    print("=" * 70)
    print()
    print(f"HEADLINE: {briefing.get('headline', '')}")
    print()
    print("FINANCIAL SNAPSHOT")
    print("-" * 70)
    print(briefing.get("financial_snapshot", ""))
    print()
    print("ROUTE PERFORMANCE")
    print("-" * 70)
    print(briefing.get("route_performance", ""))
    print()
    print("NETWORK INTELLIGENCE")
    print("-" * 70)
    print(briefing.get("network_intelligence", ""))
    print()
    print("RISK FLAGS")
    print("-" * 70)
    print(briefing.get("risk_flags", ""))
    print()
    print("RECOMMENDATIONS")
    print("-" * 70)
    print(briefing.get("recommendations", ""))
    print()
    print("=" * 70)


async def save_briefing(db, briefing: dict, inputs: dict) -> None:
    if DRY_RUN:
        return
    doc = {
        "generated_at":           datetime.now(tz=timezone.utc),
        "headline":               briefing.get("headline"),
        "financial_snapshot":     briefing.get("financial_snapshot"),
        "route_performance":      briefing.get("route_performance"),
        "network_intelligence":   briefing.get("network_intelligence"),
        "risk_flags":             briefing.get("risk_flags"),
        "recommendations":        briefing.get("recommendations"),
        "overall_health":         briefing.get("overall_health"),
        "stats_snapshot":         inputs["stats"],
    }
    await db["cfo_briefings"].insert_one(doc)
    log.info("Briefing saved to cfo_briefings collection")


# =============================================================================
# MAIN LOOP
# =============================================================================

async def scan_cycle(db) -> None:
    log.info("─" * 60)
    log.info("CFO Narrator scan starting...")

    inputs = await gather_inputs(db)
    stats = inputs["stats"]

    has_any = inputs["finance_report"] or inputs["network_report"] or inputs["fuel_report"]

    log.info(
        "Stats: %d flights | %d bookings | Revenue %s | Margin %+.1f%%",
        stats["total_flights"], stats["total_bookings"],
        fmt_inr(stats["total_revenue_inr"]), stats["margin_pct"],
    )

    if not has_any and stats["total_bookings"] == 0:
        log.info("No agent reports or bookings found — generating briefing from stats only.")

    brief    = build_brief(inputs)
    briefing = await call_claude(brief)

    if not briefing:
        log.warning("No briefing received from Claude.")
        return

    print_briefing(briefing)
    await save_briefing(db, briefing, inputs)


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'\n"
            "  Then restart: python -m agents.cfo_narrator"
        )
        sys.exit(1)

    db = get_db()

    log.info("=" * 60)
    log.info("  AeroSync-India — CFO Dashboard Narrator")
    log.info("  Model:    %s", MODEL)
    log.info("  Interval: %ds (%.0f min)", SCAN_INTERVAL, SCAN_INTERVAL / 60)
    log.info("  Dry run:  %s", DRY_RUN)
    log.info("=" * 60)

    while True:
        try:
            await scan_cycle(db)
        except Exception as e:
            log.error("Scan error: %s", e, exc_info=True)

        log.info("Next briefing in %ds. Ctrl+C to stop.\n", SCAN_INTERVAL)
        await asyncio.sleep(SCAN_INTERVAL)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("CFO Narrator stopped.")


if __name__ == "__main__":
    main()
