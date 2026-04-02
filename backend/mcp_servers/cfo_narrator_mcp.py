import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timezone
import motor.motor_asyncio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from google import genai
from google.genai import types

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] CFONarratorMCP — %(message)s")
log = logging.getLogger("mcp.cfo_narrator")

mcp = FastMCP("CFO Narrator")

GEMINI_API_KEY_CFO = os.getenv("GEMINI_API_KEY_CFO", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "aerosync")

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    return client[MONGO_DB]

def fmt_inr(n: float) -> str:
    if n >= 1_00_00_000: return f"₹{n/1_00_00_000:.1f}Cr"
    if n >= 1_00_000: return f"₹{n/1_00_000:.1f}L"
    return f"₹{n:,.0f}"

# =============================================================================
# FINANCE CONTROLLER LOGIC (Stage 1)
# =============================================================================

def estimate_trip_cost(origin: str, dest: str, capacity: int, floor_inr: float) -> float:
    return floor_inr * capacity * 0.856

async def fetch_flight_pl(db):
    today = date.today()
    flights_cursor = db["live_flights"].find(
        {"status": "scheduled", "inventory.sold": {"$gt": 0}},
        {"_id": 1, "origin": 1, "destination": 1, "departure_date": 1, "slot": 1, "inventory": 1, "current_pricing": 1}
    )

    booking_revenue = defaultdict(float)
    async for bk in db["bookings"].find({}, {"flight_id": 1, "price_charged_inr": 1}):
        fid = bk.get("flight_id", "")
        booking_revenue[fid] += bk.get("price_charged_inr", 0) or 0

    flight_pl = []
    route_pl = defaultdict(lambda: {"flights": 0, "revenue": 0.0, "cost": 0.0, "seats_sold": 0, "seats_capacity": 0})

    async for fl in flights_cursor:
        fid = str(fl["_id"])
        inv = fl.get("inventory") or {}
        cp = fl.get("current_pricing") or {}
        cap = inv.get("capacity", 186)
        sold = inv.get("sold", 0)
        fare = cp.get("ml_fare_inr", 0.0)
        floor = cp.get("floor_inr", fare)
        origin = fl.get("origin", "")
        dest = fl.get("destination", "")
        route = f"{origin}-{dest}"

        actual_revenue = booking_revenue.get(fid, 0.0)
        if actual_revenue == 0 and sold > 0:
            actual_revenue = fare * sold

        trip_cost = estimate_trip_cost(origin, dest, cap, floor)
        contrib = actual_revenue - trip_cost
        margin_pct = (contrib / actual_revenue * 100) if actual_revenue > 0 else -999.0
        lf = sold / cap if cap > 0 else 0.0

        dep_raw = fl.get("departure_date")
        try:
            dep_date = dep_raw.date() if isinstance(dep_raw, datetime) else (dep_raw if isinstance(dep_raw, date) else date.fromisoformat(str(dep_raw)[:10]))
            days_out = (dep_date - today).days
        except Exception: days_out = -1

        record = {
            "flight_id": fid, "route": route, "origin": origin, "destination": dest,
            "days_out": days_out, "slot": fl.get("slot", "B"), "capacity": cap, "sold": sold,
            "load_factor": round(lf, 4), "fare_inr": round(fare, 0), "floor_inr": round(floor, 0),
            "revenue_inr": round(actual_revenue, 0), "cost_inr": round(trip_cost, 0),
            "contribution_inr": round(contrib, 0), "margin_pct": round(margin_pct, 2)
        }
        flight_pl.append(record)

        rp = route_pl[route]
        rp["flights"] += 1; rp["revenue"] += actual_revenue; rp["cost"] += trip_cost
        rp["seats_sold"] += sold; rp["seats_capacity"] += cap

    for route, rp in route_pl.items():
        rev = rp["revenue"]; cost = rp["cost"]
        rp["contribution"] = round(rev - cost, 0)
        rp["margin_pct"] = round((rev - cost) / rev * 100, 2) if rev > 0 else -999.0
        rp["avg_lf"] = round(rp["seats_sold"] / rp["seats_capacity"] * 100, 1) if rp["seats_capacity"] > 0 else 0.0
        rp["revenue"] = round(rev, 0)
        rp["cost"] = round(cost, 0)

    return flight_pl, dict(route_pl)

def build_finance_brief(flight_pl: list[dict], route_pl: dict) -> str:
    routes_sorted = sorted(route_pl.items(), key=lambda x: x[1]["contribution"], reverse=True)
    route_rows = []
    for route, rp in routes_sorted:
        margin_flag = " ⚠ LOSS" if rp["margin_pct"] < 0 else " ⚠ THIN" if rp["margin_pct"] < 5 else ""
        route_rows.append(f"  {route:<10} | flights: {rp['flights']:>3} | LF: {rp['avg_lf']:>5.1f}% | rev: ₹{rp['revenue']:>12,.0f} | cost: ₹{rp['cost']:>12,.0f} | margin: {rp['margin_pct']:>+7.1f}%{margin_flag}")

    loss_flights = sorted([f for f in flight_pl if f["margin_pct"] < 5], key=lambda x: x["margin_pct"])[:10]
    loss_rows = []
    for f in loss_flights:
        loss_rows.append(f"  {f['flight_id'][:28]:<28} | {f['route']:<10} | D+{f['days_out']:02d} | LF {f['load_factor']*100:>5.1f}% | margin {f['margin_pct']:>+7.1f}% | rev ₹{f['revenue_inr']:>8,.0f} | cost ₹{f['cost_inr']:>8,.0f}")

    total_rev = sum(rp["revenue"] for rp in route_pl.values())
    total_cost = sum(rp["cost"] for rp in route_pl.values())
    total_cont = total_rev - total_cost
    system_margin = total_cont / total_rev * 100 if total_rev > 0 else 0

    return f"""You are the AI Finance Controller for AeroSync-India.
## SYSTEM P&L SUMMARY
Total Revenue: ₹{total_rev:>14,.0f}
Total Cost: ₹{total_cost:>14,.0f}
Contribution: ₹{total_cont:>14,.0f}
System Margin: {system_margin:>+.1f}%

## ROUTE P&L TABLE (sorted by contribution)
{chr(10).join(route_rows)}

## WORST-MARGIN FLIGHTS (margin < 5%)
{chr(10).join(loss_rows) if loss_rows else "None"}

Write a FINANCE REPORT in JSON matching exactly this schema:
{{
  "executive_summary": "string",
  "route_ranking": {{ "star": ["route1"], "acceptable": ["route2"], "problem": ["route3"] }},
  "margin_warnings": [ {{"flight_id": "...", "route": "...", "issue": "...", "severity": "HIGH|MEDIUM|LOW"}} ],
  "revenue_leakage": {{ "estimated_inr": number, "explanation": "string" }},
  "recommendations": [ {{"priority": 1, "action": "string", "expected_impact": "string"}} ],
  "overall_health": "HEALTHY|CAUTION|CRITICAL"
}}"""

# =============================================================================
# CFO NARRATOR LOGIC (Stage 2)
# =============================================================================

async def gather_cfo_inputs(db) -> dict:
    finance = await db["finance_reports"].find_one({}, sort=[("generated_at", -1)])
    network = await db["network_reports"].find_one({}, sort=[("generated_at", -1)])
    fuel    = await db["fuel_reports"].find_one({}, sort=[("generated_at", -1)])

    flights = await db["live_flights"].find({}, {"inventory": 1, "current_pricing": 1, "status": 1, "origin": 1, "destination": 1}).to_list(length=None)
    bookings = await db["bookings"].find({}, {"price_charged_inr": 1, "seats_booked": 1}).to_list(length=None)

    total_capacity = sum(f.get("inventory", {}).get("capacity", 0) for f in flights)
    total_sold     = sum(f.get("inventory", {}).get("sold", 0) for f in flights)
    system_lf      = round(total_sold / total_capacity * 100, 1) if total_capacity else 0.0
    total_revenue  = sum(b.get("price_charged_inr", 0) or 0 for b in bookings)
    total_cost = sum((f.get("current_pricing", {}).get("floor_inr", 0) or 0) * (f.get("inventory", {}).get("capacity", 0) or 0) * 0.856 for f in flights if f.get("inventory", {}).get("sold", 0) > 0)
    contribution = total_revenue - total_cost
    margin_pct   = round(contribution / total_revenue * 100, 1) if total_revenue else 0.0

    def clean_doc(doc):
        if not doc: return None
        doc.pop("_id", None)
        if "generated_at" in doc and hasattr(doc["generated_at"], "isoformat"):
            doc["generated_at"] = doc["generated_at"].isoformat()
        return doc

    return {
        "stats": {
            "total_flights": len(flights), "system_lf_pct": system_lf,
            "total_bookings": len(bookings), "total_revenue_inr": round(total_revenue),
            "total_cost_inr": round(total_cost), "contribution_inr": round(contribution), "margin_pct": margin_pct,
        },
        "finance_report": clean_doc(finance),
        "network_report": clean_doc(network),
        "fuel_report": clean_doc(fuel),
    }

def build_cfo_brief(inputs: dict) -> str:
    s = inputs["stats"]
    fin = inputs["finance_report"]
    net = inputs["network_report"]
    fuel = inputs["fuel_report"]

    fin_str = json.dumps(fin) if fin else "None"
    net_str = json.dumps(net) if net else "None"
    fuel_str = json.dumps(fuel) if fuel else "None"

    return f"""You are the CFO Dashboard Narrator for AeroSync.
## LIVE DASHBOARD KPIs
System Load: {s['system_lf_pct']}%
Total Bookings: {s['total_bookings']:,}
Total Revenue: {fmt_inr(s['total_revenue_inr'])}
Margin: {s['margin_pct']:+.1f}%

## SUB-AGENT REPORTS
Finance Report: {fin_str}
Network Report: {net_str}
Fuel Report: {fuel_str}

Write a DAILY EXECUTIVE BRIEFING in JSON matching exactly this schema:
{{
  "headline": "str",
  "financial_snapshot": "str",
  "route_performance": "str",
  "network_intelligence": "str",
  "risk_flags": "str",
  "recommendations": "str",
  "overall_health": "HEALTHY | CAUTION | CRITICAL"
}}"""

async def call_gemini(brief: str) -> dict | None:
    if not GEMINI_API_KEY_CFO: return None
    try:
        client = genai.Client(api_key=GEMINI_API_KEY_CFO)
        resp = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=brief,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        raw = resp.text.strip()
        if raw.startswith("```"): raw = raw.split("```")[1]
        if raw.startswith("json"): raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        log.error(f"Gemini call failed: {e}")
        return None

@mcp.tool()
async def draft_financial_brief() -> str:
    """
    Computes system P&L, drafts Finance Report, and synthesizes into a CFO briefing.
    """
    log.info("Master Agent requested CFO Briefing. [Stage 1: Finance Report]")
    db = get_db()
    
    # Stage 1: Finance
    flight_pl, route_pl = await fetch_flight_pl(db)
    if flight_pl:
        fin_prompt = build_finance_brief(flight_pl, route_pl)
        fin_report = await call_gemini(fin_prompt)
        if fin_report:
            fin_doc = fin_report.copy()
            fin_doc["generated_at"] = datetime.now(timezone.utc)
            fin_doc["route_pl_snapshot"] = route_pl
            fin_doc["flights_analysed"] = len(flight_pl)
            fin_doc["total_revenue"] = sum(f["revenue_inr"] for f in flight_pl)
            fin_doc["total_cost"] = sum(f["cost_inr"] for f in flight_pl)
            await db["finance_reports"].insert_one(fin_doc)
            log.info("Saved Finance Report to DB.")

    # Stage 2: CFO
    log.info("[Stage 2: CFO Narrator Briefing]")
    inputs = await gather_cfo_inputs(db)
    cfo_prompt = build_cfo_brief(inputs)
    briefing = await call_gemini(cfo_prompt)
    
    if not briefing:
        return json.dumps({"status": "error", "message": "Failed to generate briefing."})
    
    doc = briefing.copy()
    doc["generated_at"] = datetime.now(timezone.utc)
    await db["cfo_briefings"].insert_one(doc)
    doc.pop("_id", None)
    doc["generated_at"] = str(doc["generated_at"])
    
    return json.dumps({"status": "success", "briefing": doc})

if __name__ == "__main__":
    mcp.run()
