import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timezone
import motor.motor_asyncio
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] NetworkPlannerMCP — %(message)s")
log = logging.getLogger("mcp.network_planner")

mcp = FastMCP("Network Planner")

GEMINI_API_KEY_NETWORK = os.getenv("GEMINI_API_KEY_NETWORK", "")
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "aerosync")

ROUTE_META = {
    "DEL-BOM": {"aircraft": "A321neo", "seats": 222, "dist_km": 1136, "type": "BUSINESS", "tier": 1},
    "BOM-DEL": {"aircraft": "A321neo", "seats": 222, "dist_km": 1136, "type": "BUSINESS", "tier": 1},
    "DEL-MAA": {"aircraft": "A321neo", "seats": 222, "dist_km": 1753, "type": "BUSINESS", "tier": 1},
    "MAA-DEL": {"aircraft": "A321neo", "seats": 222, "dist_km": 1753, "type": "BUSINESS", "tier": 1},
    "DEL-CCU": {"aircraft": "A320neo", "seats": 186, "dist_km": 1305, "type": "LEISURE",  "tier": 2},
    "CCU-DEL": {"aircraft": "A320neo", "seats": 186, "dist_km": 1305, "type": "LEISURE",  "tier": 2},
    "BOM-CCU": {"aircraft": "A320neo", "seats": 186, "dist_km": 1660, "type": "BUSINESS", "tier": 2},
    "CCU-BOM": {"aircraft": "A320neo", "seats": 186, "dist_km": 1660, "type": "BUSINESS", "tier": 2},
    "BOM-MAA": {"aircraft": "A320neo", "seats": 186, "dist_km":  843, "type": "BUSINESS", "tier": 2},
    "MAA-BOM": {"aircraft": "A320neo", "seats": 186, "dist_km":  843, "type": "BUSINESS", "tier": 2},
    "CCU-MAA": {"aircraft": "A320ceo", "seats": 180, "dist_km": 1370, "type": "LEISURE",  "tier": 3},
    "MAA-CCU": {"aircraft": "A320ceo", "seats": 180, "dist_km": 1370, "type": "LEISURE",  "tier": 3},
}

SLOT_TIMES = {"A": "06:00", "B": "12:30", "C": "18:00"}

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    return client[MONGO_DB]

async def fetch_network_state(db) -> dict:
    today = date.today()
    slot_data = defaultdict(lambda: defaultdict(lambda: {"flights": 0, "total_cap": 0, "total_sold": 0, "fares": [], "floors": [], "days_out_list": []}))
    async for fl in db["live_flights"].find({"status": "scheduled"}, {"_id":1, "origin":1, "destination":1, "departure_date":1, "slot":1, "inventory":1, "current_pricing":1}):
        origin, dest = fl.get("origin", ""), fl.get("destination", "")
        route, slot = f"{origin}-{dest}", fl.get("slot", "B")
        inv, cp = fl.get("inventory") or {}, fl.get("current_pricing") or {}
        try:
            dep_raw = fl.get("departure_date")
            dep_date = dep_raw.date() if isinstance(dep_raw, datetime) else (dep_raw if isinstance(dep_raw, date) else date.fromisoformat(str(dep_raw)[:10]))
            days_out = (dep_date - today).days
        except: days_out = 15
        cap, sold = inv.get("capacity", 0), inv.get("sold", 0)
        fare, floor = cp.get("ml_fare_inr", 0), cp.get("floor_inr", 0)
        
        sd = slot_data[route][slot]
        sd["flights"] += 1; sd["total_cap"] += cap; sd["total_sold"] += sold
        sd["fares"].append(fare); sd["floors"].append(floor); sd["days_out_list"].append(days_out)

    network = {}
    for route, slots in slot_data.items():
        network[route] = {}
        for slot, sd in slots.items():
            cap, sold = sd["total_cap"], sd["total_sold"]
            fares, floors = sd["fares"], sd["floors"]
            network[route][slot] = {
                "flights": sd["flights"], "total_cap": cap, "total_sold": sold,
                "avg_lf_pct": round((sold / cap * 100) if cap else 0, 1),
                "avg_fare": round(sum(fares)/len(fares)) if fares else 0,
                "avg_floor": round(sum(floors)/len(floors)) if floors else 0,
                "avg_days_out": round(sum(sd["days_out_list"])/len(sd["days_out_list"]), 1) if sd["days_out_list"] else 15,
            }

    booking_route, booking_slot, booking_type = defaultdict(int), defaultdict(lambda: defaultdict(int)), defaultdict(lambda: defaultdict(int))
    async for bk in db["bookings"].find({}, {"origin":1, "destination":1, "agent_type":1, "flight_id":1, "seats_booked":1}):
        orig, dest, atype, seats = bk.get("origin", ""), bk.get("destination", ""), bk.get("agent_type", "?"), bk.get("seats_booked", 1)
        if not orig or not dest:
            parts = str(bk.get("flight_id", "")).split("_")
            if len(parts) >= 2: booking_slot["?-?"][parts[1]] += seats
            continue
        route = f"{orig}-{dest}"
        booking_route[route] += seats
        booking_type[route][atype] += seats
        parts = str(bk.get("flight_id", "")).split("_")
        if len(parts) >= 2: booking_slot[route][parts[1]] += seats

    return {"network": network, "booking_by_route": dict(booking_route), "booking_by_slot": dict(booking_slot), "booking_by_type": dict(booking_type)}

def build_brief(state: dict) -> str:
    network = state["network"]
    route_rows, slot_perf = [], defaultdict(list)
    total_flights = total_cap = total_sold = 0

    for route, slots in sorted(network.items()):
        total_flights += sum(s["flights"] for s in slots.values())
        total_cap += sum(s["total_cap"] for s in slots.values())
        total_sold += sum(s["total_sold"] for s in slots.values())
        for slot, s in slots.items(): slot_perf[slot].append(s["avg_lf_pct"])
        
        all_lf = [s["avg_lf_pct"] for s in slots.values()]
        avg_lf = sum(all_lf) / len(all_lf) if all_lf else 0
        mix = " ".join(f"{k}:{v}" for k, v in sorted(state["booking_by_type"].get(route, {}).items())) or "no data"
        slot_str = " | ".join(f"{st}({SLOT_TIMES.get(st,'?')}):{spt['avg_lf_pct']}%" for st, spt in sorted(slots.items()))
        meta = ROUTE_META.get(route, {})
        route_rows.append(f"  {route:<10} | tier:{meta.get('tier','?')} {meta.get('type',''):<8} | ac:{meta.get('aircraft','?'):<8} | avg_lf:{avg_lf:>5.1f}% | {slot_str} | bookings:{state['booking_by_route'].get(route, 0):>5} | pax_mix:[{mix}]")

    slot_rows = [f"  Slot {st} ({SLOT_TIMES.get(st)}): avg LF {sum(lfs)/len(lfs):.1f}%" for st in ["A", "B", "C"] if (lfs := slot_perf.get(st))]
    hot_routes = [r for r, s in network.items() if all(x["avg_lf_pct"] > 50 for x in s.values())]
    cold_routes = [r for r, s in network.items() if all(x["avg_lf_pct"] < 10 for x in s.values())]

    return f"""You are the AI Network Planner for AeroSync-India.

## NETWORK OVERVIEW
  Routes active:    {len(network)}
  Total flights:    {total_flights}
  Total capacity:   {total_cap:,}
  Seats sold:       {total_sold:,} ({(total_sold/total_cap*100) if total_cap else 0:.1f}% LF)

## SLOT PERFORMANCE
{chr(10).join(slot_rows)}

## ROUTE PERFORMANCE
{chr(10).join(route_rows)}
## HOT ROUTES: {', '.join(hot_routes) or 'None'}
## COLD ROUTES: {', '.join(cold_routes) or 'None'}

## YOUR TASK
Produce a JSON array of network planning decisions. Output EXACTLY this JSON schema:
{{
  "slot_analysis": [{{"route": "str", "best_slot": "str", "worst_slot": "str", "finding": "str"}}],
  "frequency_decisions": [{{"route": "str", "current": 3, "recommended": 2, "action": "CUT|ADD|MAINTAIN", "reason": "str"}}],
  "aircraft_changes": [{{"route": "str", "current": "str", "proposed": "str", "action": "UPGRADE|DOWNGRADE|MAINTAIN", "reason": "str"}}],
  "growth_opportunities": [{{"route": "str", "finding": "str", "action": "str"}}],
  "network_efficiency_score": {{"score": 7, "out_of": 10, "justification": "str"}},
  "executive_summary": "str"
}}"""

async def call_gemini(brief: str) -> dict | None:
    if not GEMINI_API_KEY_NETWORK: return None
    try:
        client = genai.Client(api_key=GEMINI_API_KEY_NETWORK)
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
async def plan_network() -> str:
    """Evaluates slot-level performance across all routes and produces a network planning JSON report."""
    db = get_db()
    state = await fetch_network_state(db)
    if not state["network"]: return json.dumps({"status": "no_data"})
    brief = build_brief(state)
    report = await call_gemini(brief)
    if not report: return json.dumps({"status": "error"})
    
    doc = report.copy()
    doc["generated_at"] = datetime.now(timezone.utc)
    await db["network_reports"].insert_one(doc)
    doc.pop("_id", None)
    doc["generated_at"] = str(doc["generated_at"])
    return json.dumps({"status": "success", "report": doc})

if __name__ == "__main__":
    mcp.run()
