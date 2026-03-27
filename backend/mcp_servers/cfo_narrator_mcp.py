import json
import logging
import os
from datetime import datetime, timezone
import httpx
import motor.motor_asyncio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from google import genai
from google.genai import types

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] CFONarratorMCP — %(message)s",
)
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

async def gather_inputs(db) -> dict:
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

def build_brief(inputs: dict) -> str:
    s = inputs["stats"]
    fin = inputs["finance_report"]
    net = inputs["network_report"]
    fuel = inputs["fuel_report"]

    fin_section = f"Finance Report: {json.dumps(fin)}" if fin else "No finance report."
    net_section = f"Network Report: {json.dumps(net)}" if net else "No network report."
    fuel_section = f"Fuel Report: {json.dumps(fuel)}" if fuel else "No fuel report."

    return f"""You are the CFO Dashboard Narrator for AeroSync.
## LIVE DASHBOARD KPIs
System Load: {s['system_lf_pct']}%
Total Bookings: {s['total_bookings']:,}
Total Revenue: {fmt_inr(s['total_revenue_inr'])}
Margin: {s['margin_pct']:+.1f}%

## AGENT REPORTS
{fin_section}
{net_section}
{fuel_section}

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
        with open("mcp_debug.log", "a") as f: f.write(f"CFO ERROR: {e}\n")
        log.error(f"Gemini call failed: {e}")
        return None

@mcp.tool()
async def draft_financial_brief() -> str:
    """
    Synthesizes current database metrics and sub-agent reports into a single 
    CFO executive briefing. Returns a JSON string of the briefing.
    """
    log.info("Master Agent requested CFO Briefing.")
    db = get_db()
    inputs = await gather_inputs(db)
    brief = build_brief(inputs)
    briefing = await call_gemini(brief)
    if not briefing:
        return json.dumps({"status": "error", "message": "Failed to generate briefing."})
    return json.dumps({"status": "success", "briefing": briefing})

if __name__ == "__main__":
    mcp.run()
