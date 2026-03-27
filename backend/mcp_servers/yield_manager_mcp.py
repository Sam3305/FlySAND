import asyncio
import json
import logging
import math
import os
import sys
from datetime import date, datetime, timezone
from typing import List, Dict, Any

import httpx
import motor.motor_asyncio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from google import genai
from google.genai import types

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] YieldManagerMCP — %(message)s",
)
log = logging.getLogger("mcp.yield_mgr")

# Create the MCP Server
mcp = FastMCP("Yield Manager")

GEMINI_API_KEY_YIELD = os.getenv("GEMINI_API_KEY_YIELD", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "aerosync")

BUSINESS_ROUTES = {
    frozenset({"DEL", "BOM"}), frozenset({"DEL", "MAA"}),
    frozenset({"BOM", "CCU"}), frozenset({"BOM", "MAA"}),
}

def route_type(origin: str, dest: str) -> str:
    return "BUSINESS" if frozenset({origin, dest}) in BUSINESS_ROUTES else "LEISURE"

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    return client[MONGO_DB]

def build_brief(flights: list[dict]) -> str:
    rows = []
    for f in flights:
        lf_pct = f["load_factor"] * 100
        rows.append(
            f"  {f['flight_id'][:28]:<28} | {f['origin']}->{f['destination']:<3} | "
            f"D+{f['days_out']:02d} | {f['route_type']:<8} | "
            f"LF {lf_pct:5.1f}% | "
            f"fare ₹{f['fare_inr']:>6,.0f} | floor ₹{f['floor_inr']:>6,.0f} | "
            f"ratio {f['ratio']:.3f} | cap ₹{f['cap_inr']:>6,.0f}"
        )
    table = "\n".join(rows)

    return f"""You are the AI Yield Manager for AeroSync-India, a fully AI-operated airline.

## OUR PRICING STRATEGY
- We win by volume, not margin. Lower fares than competitors to build trust.
- Hard price cap: 1.40× floor. We NEVER exceed this — even for last-minute seats.
- Target margins: 2–15% above floor on most flights.
- Business routes (DEL-BOM, DEL-MAA, BOM-CCU, BOM-MAA): demand is inelastic, flat pricing.
- Leisure routes (DEL-CCU, CCU-MAA): DOW-sensitive, price-elastic travellers.

## YOUR JOB
Analyse each flight below and decide the optimal new fare.
You must balance two competing goals:
  1. Fill seats (revenue = fare × seats sold, empty seat = zero revenue)
  2. Maximize revenue per seat (within our 1.40× cap)

## HARD CONSTRAINTS (non-negotiable)
- new_fare >= floor_inr (cardinal rule — never fly below cost)
- new_fare <= floor_inr × 1.40 (strategy cap — no gouging)
- Max change per cycle: ±20% of current fare
- If current fare is already optimal → HOLD (don't change)

## DECISION HEURISTICS
Load factor vs days-to-departure guidance:
  - LF >80%, D+1-7:   RAISE aggressively (near-full, last seats)
  - LF >60%, D+1-14:  RAISE moderately
  - LF >40%, D+15-30: HOLD or RAISE slightly
  - LF <20%, D+1-7:   LOWER significantly (need to move seats fast)
  - LF <20%, D+8-21:  LOWER slightly (still time, but stimulate)
  - LF <10%, D+22+:   LOWER to near-floor (early-bird pricing)
  - ratio > 1.50:      Consider LOWER unless LF is high
  - ratio < 1.02:      HOLD (already at floor, can't go lower)

## FLIGHT TABLE
  flight_id                     | route      | DTD  | type     | LF      | fare    | floor   | ratio | cap
{table}

## RESPONSE FORMAT
Respond with ONLY a JSON array. No explanation, no markdown.
Each object must have exactly these fields:
  "flight_id": string (exact match from table)
  "action":    "RAISE" | "LOWER" | "HOLD" | "FLOOR"
  "new_fare":  number (INR, integer, must satisfy constraints above)
  "reason":    string (one concise sentence explaining why)
"""

async def call_gemini(brief: str) -> list[dict]:
    if not GEMINI_API_KEY_YIELD:
        log.error("GEMINI_API_KEY_YIELD not set")
        return []

    try:
        client = genai.Client(api_key=GEMINI_API_KEY_YIELD)
        resp = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=brief,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        raw = resp.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        decisions = json.loads(raw)
        return decisions

    except Exception as e:
        with open("mcp_debug.log", "a") as f: f.write(f"YM ERROR: {e}\n")
        log.error(f"Gemini API call failed: {e}")
        return []

@mcp.tool()
async def evaluate_route_yields(max_flights: int = 50) -> str:
    """
    Evaluates current flight schedules, computes load factors, and queries Claude 
    for recommended fare adjustments.
    
    Args:
        max_flights: The maximum number of flights to evaluate in one batch.
        
    Returns:
        A JSON string containing an array of Claude's proposed pricing strategies.
        Each object contains flight_id, action (RAISE/LOWER/HOLD), new_fare, and reason.
    """
    log.info("Master Agent requested yield evaluation.")
    db = get_db()
    today = date.today()

    cursor = db["live_flights"].find(
        {"status": "scheduled"},
        {"_id": 1, "origin": 1, "destination": 1, "departure_date": 1, "inventory": 1, "current_pricing": 1}
    )

    flights = []
    async for doc in cursor:
        inv = doc.get("inventory") or {}
        cap = inv.get("capacity", 0)
        sold = inv.get("sold", 0)
        if cap <= 0: continue

        dep_raw = doc.get("departure_date")
        try:
            if isinstance(dep_raw, datetime): dep_date = dep_raw.date()
            elif isinstance(dep_raw, date): dep_date = dep_raw
            else: dep_date = date.fromisoformat(str(dep_raw)[:10])
        except Exception: continue

        days_out = (dep_date - today).days
        if days_out <= 0: continue

        cp = doc.get("current_pricing") or {}
        fare = cp.get("ml_fare_inr", 0.0)
        floor = cp.get("floor_inr", fare)
        lf = sold / cap

        flights.append({
            "flight_id": str(doc["_id"]),
            "origin": doc.get("origin", ""),
            "destination": doc.get("destination", ""),
            "days_out": days_out,
            "load_factor": round(lf, 4),
            "fare_inr": round(fare, 0),
            "floor_inr": round(floor, 0),
            "ratio": round(fare / floor, 3) if floor else 1.0,
            "route_type": route_type(doc.get("origin",""), doc.get("destination","")),
            "cap_inr": round(floor * 1.40, 0),
        })

    flights.sort(key=lambda f: (f["days_out"], -f["load_factor"]))
    candidates = flights[:max_flights]
    
    if not candidates:
        return json.dumps({"status": "no_flights_found", "decisions": []})

    brief = build_brief(candidates)
    log.info("Sending brief to Gemini LLM inside MCP Server...")
    decisions = await call_gemini(brief)
    
    return json.dumps({
        "status": "success",
        "evaluated_count": len(candidates),
        "decisions": decisions
    })

if __name__ == "__main__":
    mcp.run()
