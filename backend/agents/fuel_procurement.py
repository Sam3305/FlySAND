"""
backend/agents/fuel_procurement.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  AI Fuel Procurement Officer
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
A Claude-powered agent that acts as the airline's head of fuel procurement.

Every SCAN_INTERVAL seconds it:
  1. Reads current ATF prices across all 4 stations (DEL/BOM/CCU/MAA)
  2. Reads upcoming flight schedule from MongoDB
  3. Calculates fuel requirements per route per day
  4. Sends a procurement brief to Claude
  5. Claude decides:
     - TANKER decisions: carry extra fuel from cheap stations to expensive ones
     - SPOT vs CONTRACT: which station to buy spot vs contracted supply
     - DAILY BUDGET: total ATF spend estimate for next 24h
     - ALERTS: price spike warnings, supply risk flags
  6. Saves recommendations to MongoDB (fuel_reports collection)
  7. Prints formatted report

TANKERING EXPLAINED
────────────────────
  BOM ATF: ₹86,352/kl  (cheapest)
  CCU ATF: ₹95,378/kl  (most expensive)
  Spread:  ₹9,026/kl   = 10.4% cheaper at BOM

  A BOM→CCU flight burns ~3,800 kg fuel (1,660km, A320neo).
  If we uplift 500 kg extra at BOM for the return CCU→BOM leg:
    Extra weight penalty: 500kg × 0.03 kg/km/kg × 1660km = 24.9 kg extra fuel
    Extra fuel cost at BOM: (500 + 24.9) kg / 800 × ₹86,352 = ₹56,700
    Savings vs buying at CCU: 500 kg / 800 × ₹95,378 = ₹59,611
    Net saving: ₹59,611 - ₹56,700 = ₹2,911 per tankering decision

  Claude evaluates all 12 GQ route pairs and recommends tankering where
  the spread justifies the weight penalty.

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.fuel_procurement

  Optional env vars:
    SCAN_INTERVAL=600    (seconds between reports, default 600 = 10 min)
    DRY_RUN=true
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import httpx
import motor.motor_asyncio

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aerosync.fuel")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "600"))
DRY_RUN           = os.getenv("DRY_RUN", "false").lower() == "true"
MODEL             = "claude-sonnet-4-20250514"

# ── Aircraft fuel specs ───────────────────────────────────────────────────────
AIRCRAFT_BURN = {
    # model: (burn_kg_per_hr, density_kg_per_kl=800)
    "A321neo": 1650,
    "A320neo": 1650,
    "A320ceo": 1700,
}

# ── Route distances (km) ─────────────────────────────────────────────────────
ROUTE_DIST = {
    ("DEL","BOM"): 1136, ("BOM","DEL"): 1136,
    ("DEL","CCU"): 1305, ("CCU","DEL"): 1305,
    ("DEL","MAA"): 1753, ("MAA","DEL"): 1753,
    ("BOM","CCU"): 1660, ("CCU","BOM"): 1660,
    ("BOM","MAA"):  843, ("MAA","BOM"):  843,
    ("CCU","MAA"): 1370, ("MAA","CCU"): 1370,
}

# ── Route aircraft mapping ────────────────────────────────────────────────────
ROUTE_AIRCRAFT = {
    frozenset({"DEL","BOM"}): "A321neo",
    frozenset({"DEL","MAA"}): "A321neo",
    frozenset({"DEL","CCU"}): "A320neo",
    frozenset({"BOM","CCU"}): "A320neo",
    frozenset({"BOM","MAA"}): "A320neo",
    frozenset({"CCU","MAA"}): "A320ceo",
}

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


# =============================================================================
# STEP 1 — READ ATF PRICES
# =============================================================================

def load_atf_prices() -> dict[str, float]:
    """Load current ATF prices from config file."""
    config_path = _BACKEND / "app/services/config/atf_prices.json"
    try:
        with open(config_path) as f:
            data = json.load(f)
        prices = data.get("prices_inr_per_kl", {})
        log.info("ATF prices loaded: %s", prices)
        return prices
    except Exception as e:
        log.warning("Could not load ATF config: %s — using defaults", e)
        return {"DEL": 92323, "BOM": 86352, "CCU": 95378, "MAA": 95770}


# =============================================================================
# STEP 2 — COMPUTE FUEL REQUIREMENTS
# =============================================================================

def fuel_burn_kg(origin: str, dest: str, model: str) -> float:
    """Estimate fuel burn for a single sector."""
    dist     = ROUTE_DIST.get((origin, dest), 1000)
    burn_hr  = AIRCRAFT_BURN.get(model, 1650)
    speed    = 780   # km/hr cruise
    block_hr = dist / speed + 0.55   # 33 min taxi/climb overhead
    burn     = burn_hr * block_hr * 1.10   # +10% for climb/descent
    return round(burn, 0)


def tanker_saving(
    origin: str, dest: str,
    atf: dict[str, float],
    extra_kg: float = 500,
) -> float:
    """
    Calculate net saving from tankering `extra_kg` from origin to dest.
    Accounts for the weight penalty of carrying extra fuel.
    Returns positive number = saving in INR, negative = not worth it.
    """
    dist      = ROUTE_DIST.get((origin, dest), 1000)
    model     = ROUTE_AIRCRAFT.get(frozenset({origin, dest}), "A320neo")
    burn_rate = AIRCRAFT_BURN.get(model, 1650) / 780   # kg per km

    # Extra fuel burned to carry the extra weight (simplified: 3% per tonne per km)
    extra_burn = extra_kg * 0.03 / 1000 * dist   # kg
    total_uplift = extra_kg + extra_burn

    # Cost of uplift at origin (cheap station)
    uplift_cost = (total_uplift / 800) * atf.get(origin, 92000)

    # Cost savings at destination (expensive station)
    dest_saving = (extra_kg / 800) * atf.get(dest, 92000)

    return round(dest_saving - uplift_cost, 0)


async def fetch_upcoming_flights(db) -> list[dict]:
    """Pull flights departing in the next 24 hours."""
    today    = date.today()
    tomorrow = today + timedelta(days=1)

    flights = []
    async for fl in db["live_flights"].find(
        {"status": "scheduled"},
        {"_id":1, "origin":1, "destination":1, "departure_date":1, "slot":1, "inventory":1}
    ):
        dep_raw = fl.get("departure_date")
        try:
            if isinstance(dep_raw, datetime):
                dep_date = dep_raw.date()
            elif isinstance(dep_raw, date):
                dep_date = dep_raw
            else:
                dep_date = date.fromisoformat(str(dep_raw)[:10])
        except Exception:
            continue

        if dep_date not in (today, tomorrow):
            continue

        origin = fl.get("origin", "")
        dest   = fl.get("destination", "")
        model  = ROUTE_AIRCRAFT.get(frozenset({origin, dest}), "A320neo")
        burn   = fuel_burn_kg(origin, dest, model)

        flights.append({
            "flight_id":   str(fl["_id"]),
            "origin":      origin,
            "destination": dest,
            "departure":   dep_date.isoformat(),
            "slot":        fl.get("slot", "B"),
            "model":       model,
            "fuel_kg":     burn,
            "fuel_kl":     round(burn / 800, 3),
        })

    return sorted(flights, key=lambda x: (x["departure"], x["slot"]))


# =============================================================================
# STEP 3 — BUILD BRIEF FOR CLAUDE
# =============================================================================

def build_brief(atf: dict, flights: list[dict]) -> str:
    # ATF price table
    cheapest = min(atf, key=atf.get)
    priciest = max(atf, key=atf.get)
    spread   = atf[priciest] - atf[cheapest]

    atf_rows = "\n".join(
        f"  {city}: ₹{price:>10,.2f}/kl  {'← cheapest' if city==cheapest else '← most expensive' if city==priciest else ''}"
        for city, price in sorted(atf.items(), key=lambda x: x[1])
    )

    # Tankering opportunities
    tanker_rows = []
    for (orig, dest), dist in ROUTE_DIST.items():
        if orig >= dest:  # avoid duplicates
            continue
        saving = tanker_saving(orig, dest, atf)
        rev    = tanker_saving(dest, orig, atf)
        if saving > 1000:
            tanker_rows.append(
                f"  {orig}→{dest}: save ₹{saving:,.0f} per tankering leg "
                f"(carry 500kg extra from {orig})"
            )
        if rev > 1000:
            tanker_rows.append(
                f"  {dest}→{orig}: save ₹{rev:,.0f} per tankering leg "
                f"(carry 500kg extra from {dest})"
            )

    # Fuel requirements next 24h
    station_demand: dict[str, float] = {}
    for fl in flights:
        o = fl["origin"]
        station_demand[o] = station_demand.get(o, 0) + fl["fuel_kl"]

    demand_rows = "\n".join(
        f"  {stn}: {kl:.1f} kl  = ₹{kl*atf.get(stn,92000):>12,.0f}"
        for stn, kl in sorted(station_demand.items(), key=lambda x: -x[1])
    )

    total_fuel_kl    = sum(fl["fuel_kl"] for fl in flights)
    total_fuel_cost  = sum(fl["fuel_kl"] * atf.get(fl["origin"], 92000) for fl in flights)
    bulk_discount    = total_fuel_cost * 0.03   # IndiGo 3% bulk discount

    flight_rows = "\n".join(
        f"  {fl['flight_id'][:28]:<28} | {fl['origin']}→{fl['destination']} | "
        f"{fl['departure']} {fl['slot']} | {fl['model']} | "
        f"{fl['fuel_kg']:.0f}kg ({fl['fuel_kl']:.2f}kl) | "
        f"₹{fl['fuel_kl']*atf.get(fl['origin'],92000):>8,.0f}"
        for fl in flights
    ) if flights else "  No flights departing in next 24 hours."

    return f"""You are the AI Fuel Procurement Officer for AeroSync-India.

## CURRENT ATF PRICES (March 2026)
{atf_rows}
  Price spread: ₹{spread:,.0f}/kl ({spread/atf[cheapest]*100:.1f}%)
  Cheapest: {cheapest}  |  Most expensive: {priciest}

## TANKERING OPPORTUNITIES (500kg extra per leg)
{chr(10).join(tanker_rows) if tanker_rows else "  No significant tankering opportunities at current spreads."}

## NEXT 24H FUEL REQUIREMENTS BY STATION
{demand_rows if station_demand else "  No flights in next 24 hours."}

  Total uplift:     {total_fuel_kl:.1f} kl
  Gross cost:       ₹{total_fuel_cost:,.0f}
  After 3% bulk:    ₹{total_fuel_cost - bulk_discount:,.0f}
  Bulk saving:      ₹{bulk_discount:,.0f}

## FLIGHT-LEVEL FUEL PLAN (next 24h)
{flight_rows}

## YOUR TASK
As Fuel Procurement Officer, produce a structured report:

1. PRICE ASSESSMENT: Are current ATF prices high/normal/low vs March 2026 baseline?
2. TANKERING PLAN: Which specific routes should tanker, how much extra fuel, net saving?
3. STATION RISK: Any supply or price risk at specific stations?
4. DAILY BUDGET: Projected fuel spend next 24h with and without tankering
5. RECOMMENDATIONS: 3-5 actionable procurement decisions

## RESPONSE FORMAT
Respond with ONLY a JSON object. No explanation, no markdown.
{{
  "price_assessment": {{
    "overall": "HIGH | NORMAL | LOW",
    "notes": "string"
  }},
  "tankering_plan": [
    {{
      "route":       "DEL→CCU",
      "extra_kg":    500,
      "saving_inr":  2911,
      "action":      "TANKER | SKIP",
      "reason":      "string"
    }}
  ],
  "station_risks": [
    {{"station": "CCU", "risk": "string", "severity": "HIGH|MEDIUM|LOW"}}
  ],
  "daily_budget": {{
    "without_tankering_inr": number,
    "with_tankering_inr":    number,
    "net_saving_inr":        number
  }},
  "recommendations": [
    {{"priority": 1, "action": "string", "expected_saving_inr": number}}
  ]
}}"""


# =============================================================================
# STEP 4 — CALL CLAUDE
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
# STEP 5 — FORMAT + SAVE REPORT
# =============================================================================

def print_report(report: dict, atf: dict) -> None:
    print()
    print("=" * 70)
    print("  AeroSync-India  |  Fuel Procurement Report")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    pa = report.get("price_assessment", {})
    level_icon = {"HIGH": "🔴", "NORMAL": "✅", "LOW": "💚"}.get(pa.get("overall",""), "❓")
    print(f"\nATF PRICE ASSESSMENT: {level_icon} {pa.get('overall','')}")
    print(f"  {pa.get('notes','')}")

    tankers = report.get("tankering_plan", [])
    if tankers:
        print("\nTANKERING PLAN")
        print("-" * 70)
        total_saving = 0
        for t in tankers:
            act  = t.get("action","")
            icon = "✅" if act == "TANKER" else "⏭ "
            saving = t.get("saving_inr", 0)
            total_saving += saving if act == "TANKER" else 0
            print(f"  {icon} {t.get('route',''):<12} +{t.get('extra_kg',0)}kg  "
                  f"save ₹{saving:>6,.0f}  [{act}]  {t.get('reason','')[:45]}")
        print(f"\n  Total tankering saving: ₹{total_saving:,.0f}")

    risks = report.get("station_risks", [])
    if risks:
        print("\nSTATION RISKS")
        print("-" * 70)
        for risk in risks:
            sev_icon = {"HIGH":"🔴","MEDIUM":"⚠️ ","LOW":"ℹ️ "}.get(risk.get("severity",""),"")
            print(f"  {sev_icon} {risk.get('station','')}: {risk.get('risk','')}")

    budget = report.get("daily_budget", {})
    if budget:
        print("\nDAILY FUEL BUDGET")
        print("-" * 70)
        print(f"  Without tankering: ₹{budget.get('without_tankering_inr',0):>12,.0f}")
        print(f"  With tankering:    ₹{budget.get('with_tankering_inr',0):>12,.0f}")
        print(f"  Net saving:        ₹{budget.get('net_saving_inr',0):>12,.0f}")

    recs = report.get("recommendations", [])
    if recs:
        print("\nRECOMMENDATIONS")
        print("-" * 70)
        for r in recs:
            saving = r.get("expected_saving_inr", 0)
            print(f"  [{r.get('priority','')}] {r.get('action','')}")
            if saving:
                print(f"      → Expected saving: ₹{saving:,.0f}")

    print()
    print("=" * 70)


async def save_report(db, report: dict, atf: dict) -> None:
    if DRY_RUN:
        return
    doc = {
        "generated_at":    datetime.now(tz=timezone.utc),
        "atf_prices":      atf,
        "price_assessment": report.get("price_assessment"),
        "tankering_plan":  report.get("tankering_plan"),
        "station_risks":   report.get("station_risks"),
        "daily_budget":    report.get("daily_budget"),
        "recommendations": report.get("recommendations"),
    }
    await db["fuel_reports"].insert_one(doc)
    log.info("Report saved to fuel_reports collection")


# =============================================================================
# MAIN LOOP
# =============================================================================

async def scan_cycle(db) -> None:
    log.info("─" * 60)
    log.info("Fuel Procurement scan starting...")

    atf     = load_atf_prices()
    flights = await fetch_upcoming_flights(db)

    log.info(
        "ATF prices loaded | %d flights in next 24h | "
        "Total uplift: %.1f kl",
        len(flights),
        sum(f["fuel_kl"] for f in flights),
    )

    brief  = build_brief(atf, flights)
    report = await call_claude(brief)

    if not report:
        log.warning("No report from Claude.")
        return

    print_report(report, atf)
    await save_report(db, report, atf)


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'"
        )
        sys.exit(1)

    db = get_db()

    log.info("=" * 60)
    log.info("  AeroSync-India — AI Fuel Procurement Officer")
    log.info("  Model:    %s", MODEL)
    log.info("  Interval: %ds", SCAN_INTERVAL)
    log.info("  Dry run:  %s", DRY_RUN)
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
        log.info("Fuel Procurement Officer stopped.")


if __name__ == "__main__":
    main()
