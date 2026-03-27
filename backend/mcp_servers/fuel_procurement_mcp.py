import asyncio
import json
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import motor.motor_asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] FuelProcurementMCP — %(message)s")
log = logging.getLogger("mcp.fuel")

mcp = FastMCP("Fuel Procurement")

GEMINI_API_KEY_FUEL = os.getenv("GEMINI_API_KEY_FUEL", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "aerosync")
CONFIG_PATH = Path(__file__).resolve().parent.parent / "app/services/config/atf_prices.json"

AIRCRAFT_BURN = {"A321neo": 1650, "A320neo": 1650, "A320ceo": 1700}
ROUTE_DIST = {
    ("DEL","BOM"): 1136, ("BOM","DEL"): 1136,
    ("DEL","CCU"): 1305, ("CCU","DEL"): 1305,
    ("DEL","MAA"): 1753, ("MAA","DEL"): 1753,
    ("BOM","CCU"): 1660, ("CCU","BOM"): 1660,
    ("BOM","MAA"):  843, ("MAA","BOM"):  843,
    ("CCU","MAA"): 1370, ("MAA","CCU"): 1370,
}
ROUTE_AIRCRAFT = {
    frozenset({"DEL","BOM"}): "A321neo", frozenset({"DEL","MAA"}): "A321neo",
    frozenset({"DEL","CCU"}): "A320neo", frozenset({"BOM","CCU"}): "A320neo",
    frozenset({"BOM","MAA"}): "A320neo", frozenset({"CCU","MAA"}): "A320ceo",
}

def get_db():
    return motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)[MONGO_DB]

def load_atf_prices() -> dict:
    try:
        return json.load(open(CONFIG_PATH)).get("prices_inr_per_kl", {})
    except: return {"DEL": 92323, "BOM": 86352, "CCU": 95378, "MAA": 95770}

def fuel_burn_kg(orig: str, dest: str, model: str) -> float:
    return round(AIRCRAFT_BURN.get(model, 1650) * (ROUTE_DIST.get((orig, dest), 1000) / 780 + 0.55) * 1.10, 0)

def tanker_saving(orig: str, dest: str, atf: dict, extra: float = 500) -> float:
    dist = ROUTE_DIST.get((orig, dest), 1000)
    extra_burn = extra * 0.03 / 1000 * dist
    cost_origin = (extra + extra_burn) / 800 * atf.get(orig, 92000)
    save_dest = extra / 800 * atf.get(dest, 92000)
    return round(save_dest - cost_origin, 0)

async def fetch_flights(db) -> list:
    today, tmrw = date.today(), date.today() + timedelta(days=1)
    flights = []
    async for fl in db["live_flights"].find({"status": "scheduled"}, {"_id":1, "origin":1, "destination":1, "departure_date":1, "slot":1}):
        try:
            raw = fl.get("departure_date")
            d = raw.date() if isinstance(raw, datetime) else (raw if isinstance(raw, date) else date.fromisoformat(str(raw)[:10]))
            if d not in (today, tmrw): continue
        except: continue
        o, dst = fl.get("origin", ""), fl.get("destination", "")
        model = ROUTE_AIRCRAFT.get(frozenset({o, dst}), "A320neo")
        burn = fuel_burn_kg(o, dst, model)
        flights.append({"flight_id": str(fl["_id"]), "origin": o, "destination": dst, "departure": d.isoformat(), "slot": fl.get("slot"), "model": model, "fuel_kg": burn, "fuel_kl": round(burn/800, 3)})
    return sorted(flights, key=lambda x: (x["departure"], x["slot"]))

def build_brief(atf: dict, flights: list) -> str:
    tankers = [f"  {o}→{d}: save ₹{s:,.0f} (carry 500kg extra)" for (o,d) in ROUTE_DIST if o<d and (s := tanker_saving(o,d,atf))>1000] + \
              [f"  {d}→{o}: save ₹{s:,.0f} (carry 500kg extra)" for (o,d) in ROUTE_DIST if o<d and (s := tanker_saving(d,o,atf))>1000]
    
    st_demand = {}
    for f in flights: st_demand[f["origin"]] = st_demand.get(f["origin"], 0) + f["fuel_kl"]
    
    t_kl = sum(f["fuel_kl"] for f in flights)
    t_cost = sum(f["fuel_kl"] * atf.get(f["origin"], 92000) for f in flights)
    
    return f"""You are the AI Fuel Procurement Officer for AeroSync-India.

## ATF PRICES:
{chr(10).join(f"  {k}: {v}" for k,v in atf.items())}

## TANKERING OPPS:
{chr(10).join(tankers) or "None"}

## DEMAND (24h):
  Total uplift: {t_kl:.1f} kl
  Gross cost: ₹{t_cost:,.0f}

Output EXACTLY this JSON format:
{{
  "price_assessment": {{"overall": "HIGH|NORMAL|LOW", "notes": "str"}},
  "tankering_plan": [{{"route": "DEL→CCU", "extra_kg": 500, "saving_inr": 2911, "action": "TANKER|SKIP", "reason": "str"}}],
  "station_risks": [{{"station": "CCU", "risk": "str", "severity": "HIGH|MEDIUM|LOW"}}],
  "daily_budget": {{"without_tankering_inr": {t_cost}, "with_tankering_inr": {t_cost}, "net_saving_inr": 0}},
  "recommendations": [{{"priority": 1, "action": "str", "expected_saving_inr": 0}}]
}}"""

async def call_gemini(brief: str) -> dict | None:
    if not GEMINI_API_KEY_FUEL: return None
    try:
        client = genai.Client(api_key=GEMINI_API_KEY_FUEL)
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
async def optimize_fuel() -> str:
    """Calculates ATF tankering opportunities and produces a fuel procurement JSON report."""
    db = get_db()
    atf = load_atf_prices()
    flights = await fetch_flights(db)
    brief = build_brief(atf, flights)
    report = await call_gemini(brief)
    if not report: return json.dumps({"status": "error"})
    
    doc = report.copy()
    doc["generated_at"] = datetime.now(timezone.utc)
    doc["atf_prices"] = atf
    await db["fuel_reports"].insert_one(doc)
    doc.pop("_id", None)
    doc["generated_at"] = str(doc["generated_at"])
    return json.dumps({"status": "success", "report": doc})

if __name__ == "__main__":
    mcp.run()
