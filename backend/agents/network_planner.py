"""
backend/agents/network_planner.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  AI Network Planner
──────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES
──────────────
A Claude-powered agent that acts as the airline's head of network planning.

Every SCAN_INTERVAL seconds it:
  1. Pulls slot-level performance across all 12 GQ routes
  2. Computes demand patterns: which slots sell, which don't
  3. Analyses aircraft-route fit (right-sizing)
  4. Sends a network brief to Claude
  5. Claude produces:
     - Slot performance ranking (AM vs PM vs EVE per route)
     - Frequency recommendations (add/cut/maintain daily flights)
     - Aircraft swap recommendations (A321neo too big for CCU-MAA?)
     - Market opportunity flags (consistently over-sold = demand for more)
     - Network efficiency score
  6. Saves to MongoDB (network_reports collection)

WHAT "NETWORK PLANNING" MEANS IN PRACTICE
──────────────────────────────────────────
  1. SLOT TIMING
     If DEL-BOM 06:00 always fills but 12:30 never does →
     replace the 12:30 with an 09:00 (business travel peak)

  2. FREQUENCY
     If CCU-MAA consistently hits 90%+ LF across all 3 slots →
     add a 4th daily frequency (grow that route)
     If BOM-CCU never exceeds 15% LF →
     cut from 3 to 2 daily flights

  3. AIRCRAFT RIGHT-SIZING
     CCU-MAA uses A320ceo (180 seats). If LF is 12% →
     that's 21 paying passengers on a 180-seat plane →
     wrong aircraft, wrong frequency

  4. NETWORK CONNECTIVITY
     Flag routes where all slots have different demand patterns —
     suggests different traveller types (business AM, leisure PM)

USAGE
─────
  cd C:\AeroSync-India\backend
  .venv\Scripts\activate
  set ANTHROPIC_API_KEY=sk-ant-...
  python -m agents.network_planner

  Optional env vars:
    SCAN_INTERVAL=900    (15 min default — network doesn't change fast)
    DRY_RUN=true
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

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
log = logging.getLogger("aerosync.network")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SCAN_INTERVAL     = int(os.getenv("SCAN_INTERVAL", "900"))
DRY_RUN           = os.getenv("DRY_RUN", "false").lower() == "true"
MODEL             = "claude-sonnet-4-20250514"

# ── Route metadata ────────────────────────────────────────────────────────────
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
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGO_URI)
    return client[settings.MONGO_DB]


# =============================================================================
# STEP 1 — AGGREGATE SLOT-LEVEL PERFORMANCE
# =============================================================================

async def fetch_network_state(db) -> dict:
    """
    Returns a nested dict:
      route_str → slot_letter → {
        flights, total_cap, total_sold, avg_lf,
        avg_fare, avg_floor, avg_ratio, avg_days_out
      }
    Also returns booking demand patterns per route.
    """
    today = date.today()

    # ── Slot-level aggregation from live_flights ──────────────────────────────
    slot_data: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "flights": 0, "total_cap": 0, "total_sold": 0,
        "fares": [], "floors": [], "days_out_list": [],
    }))

    async for fl in db["live_flights"].find(
        {"status": "scheduled"},
        {"_id":1, "origin":1, "destination":1, "departure_date":1,
         "slot":1, "inventory":1, "current_pricing":1}
    ):
        origin = fl.get("origin", "")
        dest   = fl.get("destination", "")
        route  = f"{origin}-{dest}"
        slot   = fl.get("slot", "B")
        inv    = fl.get("inventory") or {}
        cp     = fl.get("current_pricing") or {}

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
            days_out = 15

        cap  = inv.get("capacity", 0)
        sold = inv.get("sold", 0)
        fare  = cp.get("ml_fare_inr", 0)
        floor = cp.get("floor_inr", 0)

        sd = slot_data[route][slot]
        sd["flights"]       += 1
        sd["total_cap"]     += cap
        sd["total_sold"]    += sold
        sd["fares"].append(fare)
        sd["floors"].append(floor)
        sd["days_out_list"].append(days_out)

    # ── Finalise aggregations ─────────────────────────────────────────────────
    network: dict[str, dict] = {}
    for route, slots in slot_data.items():
        network[route] = {}
        for slot, sd in slots.items():
            cap  = sd["total_cap"]
            sold = sd["total_sold"]
            lf   = sold / cap if cap > 0 else 0
            fares  = sd["fares"]
            floors = sd["floors"]
            network[route][slot] = {
                "flights":     sd["flights"],
                "total_cap":   cap,
                "total_sold":  sold,
                "avg_lf_pct":  round(lf * 100, 1),
                "avg_fare":    round(sum(fares)/len(fares), 0) if fares else 0,
                "avg_floor":   round(sum(floors)/len(floors), 0) if floors else 0,
                "avg_days_out":round(sum(sd["days_out_list"])/len(sd["days_out_list"]),1) if sd["days_out_list"] else 15,
            }

    # ── Booking demand patterns (which routes get most bookings) ──────────────
    booking_by_route: dict[str, int] = defaultdict(int)
    booking_by_slot:  dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    booking_by_type:  dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    async for bk in db["bookings"].find(
        {}, {"origin":1, "destination":1, "agent_type":1, "flight_id":1, "seats_booked":1}
    ):
        orig  = bk.get("origin", "")
        dest  = bk.get("destination", "")
        atype = bk.get("agent_type", "?")
        seats = bk.get("seats_booked", 1)

        if not orig or not dest:
            # Parse from flight_id if missing
            fid = bk.get("flight_id", "")
            parts = fid.split("_")
            if len(parts) >= 2:
                slot_letter = parts[1]
                booking_by_slot[f"?-?"][slot_letter] += seats
            continue

        route = f"{orig}-{dest}"
        booking_by_route[route]       += seats
        booking_by_type[route][atype] += seats

        fid = bk.get("flight_id", "")
        parts = fid.split("_")
        if len(parts) >= 2:
            booking_by_slot[route][parts[1]] += seats

    return {
        "network":          network,
        "booking_by_route": dict(booking_by_route),
        "booking_by_slot":  dict(booking_by_slot),
        "booking_by_type":  dict(booking_by_type),
    }


# =============================================================================
# STEP 2 — BUILD BRIEF FOR CLAUDE
# =============================================================================

def build_brief(state: dict) -> str:
    network   = state["network"]
    bk_route  = state["booking_by_route"]
    bk_slot   = state["booking_by_slot"]
    bk_type   = state["booking_by_type"]

    # ── Per-route summary ─────────────────────────────────────────────────────
    route_rows = []
    for route in sorted(network.keys()):
        meta   = ROUTE_META.get(route, {})
        slots  = network[route]
        all_lf = [s["avg_lf_pct"] for s in slots.values()]
        avg_lf = sum(all_lf) / len(all_lf) if all_lf else 0
        bk_cnt = bk_route.get(route, 0)

        slot_summary = " | ".join(
            f"{slot}({SLOT_TIMES.get(slot,'?')}):{slots[slot]['avg_lf_pct']:.0f}%"
            for slot in sorted(slots.keys())
        )

        # Passenger type mix
        type_mix = bk_type.get(route, {})
        mix_str  = " ".join(f"{k}:{v}" for k, v in sorted(type_mix.items())) or "no data"

        route_rows.append(
            f"  {route:<10} | tier:{meta.get('tier','?')} {meta.get('type',''):<8} | "
            f"ac:{meta.get('aircraft','?'):<8} | "
            f"avg_lf:{avg_lf:>5.1f}% | {slot_summary} | "
            f"bookings:{bk_cnt:>5} | pax_mix:[{mix_str}]"
        )

    # ── Slot comparison summary ───────────────────────────────────────────────
    slot_perf: dict[str, list] = defaultdict(list)
    for route, slots in network.items():
        for slot, sd in slots.items():
            slot_perf[slot].append(sd["avg_lf_pct"])

    slot_rows = []
    for slot in ["A", "B", "C"]:
        lfs = slot_perf.get(slot, [])
        avg = sum(lfs)/len(lfs) if lfs else 0
        slot_rows.append(
            f"  Slot {slot} ({SLOT_TIMES.get(slot,'?')}): avg LF {avg:.1f}% across all routes"
        )

    # ── Key metrics ───────────────────────────────────────────────────────────
    total_routes    = len(network)
    total_flights   = sum(
        sd["flights"] for slots in network.values() for sd in slots.values()
    )
    total_cap       = sum(
        sd["total_cap"] for slots in network.values() for sd in slots.values()
    )
    total_sold      = sum(
        sd["total_sold"] for slots in network.values() for sd in slots.values()
    )
    system_lf       = total_sold / total_cap * 100 if total_cap else 0

    # Over-performing routes (consistently high LF — opportunity to grow)
    hot_routes = [
        route for route, slots in network.items()
        if all(s["avg_lf_pct"] > 50 for s in slots.values())
    ]

    # Under-performing routes (all slots < 10% LF — cut frequency?)
    cold_routes = [
        route for route, slots in network.items()
        if all(s["avg_lf_pct"] < 10 for s in slots.values())
    ]

    return f"""You are the AI Network Planner for AeroSync-India.

## NETWORK OVERVIEW
  Routes active:    {total_routes} directional routes (12 GQ pairs)
  Total flights:    {total_flights} scheduled in 30-day horizon
  Total capacity:   {total_cap:,} seats
  Seats sold:       {total_sold:,} ({system_lf:.1f}% system LF)
  Frequencies:      3 daily departures per route (AM 06:00 / PM 12:30 / EVE 18:00)

## SLOT PERFORMANCE (system-wide)
{chr(10).join(slot_rows)}

## ROUTE-LEVEL PERFORMANCE
  route      | tier | type     | aircraft | avg_lf | slots (A=AM B=PM C=EVE) | bookings | pax_mix
{chr(10).join(route_rows)}

## HOT ROUTES (LF >50% across all slots — demand exceeding supply)
  {', '.join(hot_routes) if hot_routes else 'None'}

## COLD ROUTES (LF <10% across all slots — severe underperformance)
  {', '.join(cold_routes) if cold_routes else 'None'}

## AIRLINE CONTEXT
- We operate exactly 3 slots per route per day (AM/PM/EVE)
- Aircraft are fixed per route: A321neo (222Y), A320neo (186Y), A320ceo (180Y)
- We are an LCC — empty seats are pure cost, never recovered
- Our target system LF: 85% (IndiGo FY25 benchmark)
- Current system LF is {system_lf:.1f}% — {"BELOW" if system_lf < 85 else "AT/ABOVE"} target

## YOUR TASK
As Network Planner, produce a structured strategic review:

1. SLOT ANALYSIS: Which slot (AM/PM/EVE) consistently outperforms/underperforms, route by route?
2. FREQUENCY DECISIONS: Which routes should ADD a 4th daily frequency? Which should DROP to 2?
3. AIRCRAFT RIGHT-SIZING: Is the current aircraft assignment (tier 1/2/3) appropriate?
   - If a route consistently has low LF with large aircraft → downgrade
   - If a route is sold out with small aircraft → upgrade or add frequency
4. DEMAND PATTERNS: What do the passenger type mixes tell us? (BUSINESS/LEISURE/STUDENT)
5. GROWTH OPPORTUNITIES: Which routes are clearly underserved?
6. NETWORK EFFICIENCY SCORE: Rate 1-10 with justification.

## RESPONSE FORMAT
Respond with ONLY a JSON object. No explanation, no markdown.
{{
  "slot_analysis": [
    {{
      "route":          "DEL-BOM",
      "best_slot":      "A",
      "worst_slot":     "B",
      "finding":        "string"
    }}
  ],
  "frequency_decisions": [
    {{
      "route":      "CCU-MAA",
      "current":    3,
      "recommended": 2,
      "action":     "CUT | ADD | MAINTAIN",
      "reason":     "string"
    }}
  ],
  "aircraft_changes": [
    {{
      "route":    "CCU-MAA",
      "current":  "A320ceo",
      "proposed": "A320neo",
      "action":   "UPGRADE | DOWNGRADE | MAINTAIN",
      "reason":   "string"
    }}
  ],
  "growth_opportunities": [
    {{
      "route":   "DEL-CCU",
      "finding": "string",
      "action":  "string"
    }}
  ],
  "network_efficiency_score": {{
    "score":         7,
    "out_of":        10,
    "justification": "string"
  }},
  "executive_summary": "string (2-3 sentences)"
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
                if raw.startswith("json"): raw = raw[4:]
            return json.loads(raw.strip())
    except Exception as e:
        log.error("Claude call failed: %s", e)
        return None


# =============================================================================
# STEP 4 — FORMAT + SAVE
# =============================================================================

def print_report(report: dict) -> None:
    score = report.get("network_efficiency_score", {})

    print()
    print("=" * 70)
    print("  AeroSync-India  |  Network Planner Report")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    score_val = score.get("score", "?")
    score_bar = "█" * int(score_val) + "░" * (10 - int(score_val)) if isinstance(score_val, int) else ""
    print(f"  Network Efficiency: {score_val}/10  {score_bar}")
    print("=" * 70)

    print(f"\n{report.get('executive_summary','')}")

    # Slot analysis
    slots = report.get("slot_analysis", [])
    if slots:
        print("\nSLOT ANALYSIS")
        print("-" * 70)
        for s in slots:
            print(f"  {s.get('route',''):<10}  best:{s.get('best_slot','?')}  "
                  f"worst:{s.get('worst_slot','?')}  — {s.get('finding','')}")

    # Frequency decisions
    freqs = report.get("frequency_decisions", [])
    if freqs:
        print("\nFREQUENCY DECISIONS")
        print("-" * 70)
        for f in freqs:
            action = f.get("action","")
            icon   = {"ADD":"➕","CUT":"✂️ ","MAINTAIN":"✅"}.get(action,"")
            print(f"  {icon} {f.get('route',''):<10}  {f.get('current','?')}→{f.get('recommended','?')} daily  "
                  f"[{action}]  {f.get('reason','')[:55]}")

    # Aircraft changes
    ac = report.get("aircraft_changes", [])
    if ac:
        print("\nAIRCRAFT RIGHT-SIZING")
        print("-" * 70)
        for a in ac:
            action = a.get("action","")
            icon   = {"UPGRADE":"⬆️ ","DOWNGRADE":"⬇️ ","MAINTAIN":"✅"}.get(action,"")
            print(f"  {icon} {a.get('route',''):<10}  {a.get('current',''):<10}→{a.get('proposed',''):<10}  "
                  f"[{action}]  {a.get('reason','')[:45]}")

    # Growth opportunities
    growth = report.get("growth_opportunities", [])
    if growth:
        print("\nGROWTH OPPORTUNITIES")
        print("-" * 70)
        for g in growth:
            print(f"  🚀 {g.get('route',''):<10}  {g.get('finding','')}")
            print(f"      Action: {g.get('action','')}")

    if score:
        print(f"\nEFFICIENCY SCORE: {score.get('score','?')}/10")
        print(f"  {score.get('justification','')}")

    print()
    print("=" * 70)


async def save_report(db, report: dict, state: dict) -> None:
    if DRY_RUN:
        return
    doc = {
        "generated_at":            datetime.now(tz=timezone.utc),
        "network_efficiency_score": report.get("network_efficiency_score"),
        "executive_summary":        report.get("executive_summary"),
        "slot_analysis":            report.get("slot_analysis"),
        "frequency_decisions":      report.get("frequency_decisions"),
        "aircraft_changes":         report.get("aircraft_changes"),
        "growth_opportunities":     report.get("growth_opportunities"),
        "routes_analysed":          len(state["network"]),
        "system_lf_pct":            round(
            sum(s["total_sold"] for slots in state["network"].values() for s in slots.values()) /
            max(sum(s["total_cap"] for slots in state["network"].values() for s in slots.values()), 1) * 100,
            1
        ),
    }
    await db["network_reports"].insert_one(doc)
    log.info("Report saved to network_reports collection")


# =============================================================================
# MAIN LOOP
# =============================================================================

async def scan_cycle(db) -> None:
    log.info("─" * 60)
    log.info("Network Planner scan starting...")

    state = await fetch_network_state(db)

    routes_with_data = len(state["network"])
    total_bookings   = sum(state["booking_by_route"].values())

    log.info(
        "Analysing %d routes | %d total seat bookings",
        routes_with_data, total_bookings,
    )

    if routes_with_data == 0:
        log.info("No route data found — seed flights first.")
        return

    brief  = build_brief(state)
    report = await call_claude(brief)

    if not report:
        log.warning("No report from Claude.")
        return

    print_report(report)
    await save_report(db, report, state)


async def run() -> None:
    if not ANTHROPIC_API_KEY:
        log.critical(
            "ANTHROPIC_API_KEY not set.\n"
            "  Windows: $env:ANTHROPIC_API_KEY='sk-ant-...'"
        )
        sys.exit(1)

    db = get_db()

    log.info("=" * 60)
    log.info("  AeroSync-India — AI Network Planner")
    log.info("  Model:    %s", MODEL)
    log.info("  Interval: %ds  (%.0f min)", SCAN_INTERVAL, SCAN_INTERVAL/60)
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
        log.info("Network Planner stopped.")


if __name__ == "__main__":
    main()
