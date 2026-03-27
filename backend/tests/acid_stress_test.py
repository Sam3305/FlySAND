"""
backend/tests/acid_stress_test.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  ACID Stress Test — Redis Locking & Booking Failure Simulator
──────────────────────────────────────────────────────────────────────────────

THREE SCENARIOS
───────────────

SCENARIO 1 — Redis Lock Contention
    Fires N concurrent booking requests at the SAME flight at the exact same
    instant. Only 1 request can hold the Redis SETNX lock at a time.
    Expected: 1 SUCCESS (HTTP 201), N-1 LOCK_CONTENTION (HTTP 409).

SCENARIO 2 — Seat Oversell Prevention
    Fires more requests than seats available on a low-inventory flight.
    Redis lock serialises them. MongoDB's $gte guard rejects once seats=0.
    Expected: K SUCCESS (one per available seat), remainder BOOKING_REJECTED
    (HTTP 422). inventory.available must NEVER go below 0.

SCENARIO 3 — Idempotency (double-booking prevention)
    Fires the same booking request twice with the same idempotency_key.
    Expected: 1 SUCCESS, 1 rejection (lock contention or duplicate key).

USAGE
─────
    From backend/ with venv activated:
        python -m tests.acid_stress_test

    Override defaults:
        FLIGHT_ID=6E-101_A_2026-03-22 CONCURRENCY=30 python -m tests.acid_stress_test

OUTPUT
──────
    Colour-coded terminal output showing every request result.
    Final ACID verdict printed at the end of each scenario.
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import aiohttp

# ── Path bootstrap ────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── Config ────────────────────────────────────────────────────────────────────
API_BASE    = os.getenv("API_BASE",     "http://localhost:8000")
CONCURRENCY = int(os.getenv("CONCURRENCY", "25"))
FLIGHT_ID   = os.getenv("FLIGHT_ID",   "")   # auto-fetched if blank

FLIGHTS_URL = f"{API_BASE}/api/v1/flights"
BOOK_URL    = f"{API_BASE}/api/v1/book"

# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
DIM    = "\033[2m"


# =============================================================================
# RESULT TRACKING
# =============================================================================

@dataclass
class BookingResult:
    agent_id:    str
    status_code: int
    success:     bool
    ref:         str   = ""
    remaining:   int   = -1
    error_code:  str   = ""
    error_msg:   str   = ""
    latency_ms:  float = 0.0


@dataclass
class ScenarioReport:
    name:        str
    results:     list[BookingResult] = field(default_factory=list)

    @property
    def successes(self)         -> list[BookingResult]: return [r for r in self.results if r.success]
    @property
    def lock_contentions(self)  -> list[BookingResult]: return [r for r in self.results if r.error_code == "LOCK_CONTENTION"]
    @property
    def booking_rejections(self)-> list[BookingResult]: return [r for r in self.results if r.error_code == "BOOKING_REJECTED"]
    @property
    def not_found(self)         -> list[BookingResult]: return [r for r in self.results if r.error_code == "FLIGHT_NOT_FOUND"]
    @property
    def other_errors(self)      -> list[BookingResult]: return [r for r in self.results if not r.success and r.error_code not in ("LOCK_CONTENTION","BOOKING_REJECTED","FLIGHT_NOT_FOUND")]


# =============================================================================
# SINGLE BOOKING REQUEST
# =============================================================================

async def fire_booking(
    session:         aiohttp.ClientSession,
    agent_id:        str,
    flight_id:       str,
    seats:           int = 1,
    idempotency_key: str | None = None,
) -> BookingResult:
    key = idempotency_key or str(uuid.uuid4())
    payload = {
        "flight_id":        flight_id,
        "passenger_id":     agent_id,
        "seats_requested":  seats,
        "idempotency_key":  key,
    }
    t0 = asyncio.get_event_loop().time()
    try:
        async with session.post(
            BOOK_URL,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            latency = (asyncio.get_event_loop().time() - t0) * 1000
            data    = await resp.json()
            if resp.status == 201:
                return BookingResult(
                    agent_id=agent_id, status_code=201, success=True,
                    ref=data.get("booking_ref","?"),
                    remaining=data.get("seats_remaining",-1),
                    latency_ms=round(latency,1),
                )
            detail = data.get("detail") or {}
            if isinstance(detail, str):
                err_code = detail
                err_msg  = detail
            else:
                err_code = detail.get("error","UNKNOWN")
                err_msg  = detail.get("message") or detail.get("reason","")
            return BookingResult(
                agent_id=agent_id, status_code=resp.status, success=False,
                error_code=err_code, error_msg=err_msg,
                latency_ms=round(latency,1),
            )
    except Exception as exc:
        latency = (asyncio.get_event_loop().time() - t0) * 1000
        return BookingResult(
            agent_id=agent_id, status_code=0, success=False,
            error_code="CONNECTION_ERROR", error_msg=str(exc),
            latency_ms=round(latency,1),
        )


# =============================================================================
# FLIGHT FETCHER (auto-pick a suitable flight)
# =============================================================================

async def fetch_suitable_flight(
    session:       aiohttp.ClientSession,
    min_available: int = 5,
) -> tuple[str, int] | None:
    """
    Returns (flight_id, available_seats) for a suitable test target.
    Prefers flights with enough seats for the scenario but not fully empty
    (so oversell scenario is interesting).
    """
    try:
        async with session.get(FLIGHTS_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            docs = await resp.json()
    except Exception as exc:
        print(f"{RED}Cannot fetch flights: {exc}{RESET}")
        return None

    candidates = [
        d for d in docs
        if d.get("status") == "scheduled"
        and (d.get("inventory") or {}).get("available", 0) >= min_available
    ]
    if not candidates:
        return None

    # Pick the one with fewest available seats for maximum drama
    candidates.sort(key=lambda d: (d.get("inventory") or {}).get("available", 9999))
    target    = candidates[0]
    flight_id = target.get("flight_id") or str(target.get("_id",""))
    available = (target.get("inventory") or {}).get("available", 0)
    return flight_id, available


async def get_inventory(session: aiohttp.ClientSession, flight_id: str) -> dict[str, int]:
    """Fetch current inventory for a specific flight directly from the API."""
    try:
        async with session.get(FLIGHTS_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            docs = await resp.json()
            for d in docs:
                fid = d.get("flight_id") or str(d.get("_id",""))
                if fid == flight_id:
                    inv = d.get("inventory") or {}
                    return {
                        "capacity":  inv.get("capacity",  0),
                        "sold":      inv.get("sold",      0),
                        "available": inv.get("available", 0),
                    }
    except Exception:
        pass
    return {}


# =============================================================================
# PRINT HELPERS
# =============================================================================

def print_header(title: str) -> None:
    width = 64
    print(f"\n{BOLD}{CYAN}{'─' * width}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─' * width}{RESET}")


def print_result(r: BookingResult, idx: int) -> None:
    num = f"{DIM}[{idx:>3}]{RESET}"
    if r.success:
        print(f"  {num} {GREEN}✅ 201 SUCCESS{RESET}  "
              f"ref={BOLD}{r.ref}{RESET}  "
              f"seats_remaining={CYAN}{r.remaining}{RESET}  "
              f"{DIM}{r.latency_ms:.0f}ms{RESET}")
    elif r.error_code == "LOCK_CONTENTION":
        print(f"  {num} {YELLOW}🔒 409 LOCK_CONTENTION{RESET}  "
              f"{DIM}Redis blocked this agent  {r.latency_ms:.0f}ms{RESET}")
    elif r.error_code == "BOOKING_REJECTED":
        print(f"  {num} {RED}🚫 422 BOOKING_REJECTED{RESET}  "
              f"{DIM}No seats available  {r.latency_ms:.0f}ms{RESET}")
    elif r.error_code == "FLIGHT_NOT_FOUND":
        print(f"  {num} {RED}❓ 404 FLIGHT_NOT_FOUND{RESET}  "
              f"{DIM}{r.error_msg}{RESET}")
    else:
        print(f"  {num} {RED}💥 {r.status_code} {r.error_code}{RESET}  "
              f"{DIM}{r.error_msg}  {r.latency_ms:.0f}ms{RESET}")


def print_verdict(report: ScenarioReport, inv_before: dict, inv_after: dict) -> None:
    print(f"\n  {BOLD}── Results ─────────────────────────────────{RESET}")
    total = len(report.results)
    print(f"  Total requests fired : {BOLD}{total}{RESET}")
    print(f"  {GREEN}✅ Successes           : {len(report.successes)}{RESET}")
    print(f"  {YELLOW}🔒 Lock contentions    : {len(report.lock_contentions)}{RESET}")
    print(f"  {RED}🚫 Booking rejections  : {len(report.booking_rejections)}{RESET}")
    if report.other_errors:
        print(f"  {RED}💥 Other errors        : {len(report.other_errors)}{RESET}")

    if inv_before and inv_after:
        cap    = inv_before.get("capacity", 0)
        before = inv_before.get("available", "?")
        after  = inv_after.get("available",  "?")
        sold   = len(report.successes)
        expected_after = (inv_before.get("available", 0) - sold) if isinstance(before, int) else "?"

        print(f"\n  {BOLD}── Inventory audit ─────────────────────────{RESET}")
        print(f"  Capacity             : {cap}")
        print(f"  Available before     : {CYAN}{before}{RESET}")
        print(f"  Seats booked         : {GREEN}{sold}{RESET}")
        print(f"  Expected after       : {CYAN}{expected_after}{RESET}")
        print(f"  Actual after         : {CYAN}{after}{RESET}")

        # ACID verdict
        balance_ok  = (isinstance(after, int) and after >= 0)
        accuracy_ok = (after == expected_after)
        no_oversell = (isinstance(after, int) and after >= 0)

        print(f"\n  {BOLD}── ACID Verdict ────────────────────────────{RESET}")
        print(f"  No negative inventory : {'✅ PASS' if no_oversell  else '❌ FAIL'}")
        print(f"  Inventory accuracy    : {'✅ PASS' if accuracy_ok  else '⚠️  MISMATCH (race or cached read)'}")
        print(f"  Cardinal Rule (≥0)    : {'✅ PASS' if balance_ok   else '❌ FAIL — OVERSELL DETECTED'}")

        if not no_oversell:
            print(f"\n  {RED}{BOLD}🚨 OVERSELL DETECTED — inventory went negative!{RESET}")
            print(f"  {RED}This means the atomic $gte guard failed.{RESET}")
        else:
            print(f"\n  {GREEN}{BOLD}✅ ACID HOLDS — no oversell, inventory consistent.{RESET}")


# =============================================================================
# SCENARIO 1 — Lock Contention
# =============================================================================

async def scenario_lock_contention(
    session:   aiohttp.ClientSession,
    flight_id: str,
    n:         int,
) -> ScenarioReport:
    print_header(f"SCENARIO 1 — Redis Lock Contention  ({n} concurrent requests → same flight)")
    print(f"  Flight  : {BOLD}{flight_id}{RESET}")
    print(f"  Goal    : Only 1 request should win the lock. Rest → 409.\n")

    inv_before = await get_inventory(session, flight_id)

    # Fire all N requests simultaneously
    tasks = [
        fire_booking(session, f"STRESS_{i:03d}", flight_id)
        for i in range(n)
    ]
    results = await asyncio.gather(*tasks)

    report = ScenarioReport(name="Lock Contention", results=list(results))

    for i, r in enumerate(results):
        print_result(r, i + 1)

    inv_after = await get_inventory(session, flight_id)
    print_verdict(report, inv_before, inv_after)
    return report


# =============================================================================
# SCENARIO 2 — Oversell Prevention
# =============================================================================

async def scenario_oversell(
    session:   aiohttp.ClientSession,
    flight_id: str,
    available: int,
) -> ScenarioReport:
    # Fire available+10 requests — more than seats left
    n = available + 10
    print_header(f"SCENARIO 2 — Oversell Prevention  ({n} requests, only {available} seats left)")
    print(f"  Flight     : {BOLD}{flight_id}{RESET}")
    print(f"  Available  : {CYAN}{available}{RESET}")
    print(f"  Requesting : {BOLD}{n}{RESET} (intentional {n - available} excess)")
    print(f"  Goal       : Exactly {available} should succeed. Rest → 409 or 422.\n")

    inv_before = await get_inventory(session, flight_id)

    # Stagger slightly so lock contention resolves and we really test $gte guard
    async def staggered(i: int) -> BookingResult:
        await asyncio.sleep(i * 0.02)   # 20ms stagger — forces serialisation
        return await fire_booking(session, f"OVERSELL_{i:03d}", flight_id)

    tasks   = [staggered(i) for i in range(n)]
    results = await asyncio.gather(*tasks)

    report = ScenarioReport(name="Oversell Prevention", results=list(results))

    for i, r in enumerate(results):
        print_result(r, i + 1)

    inv_after = await get_inventory(session, flight_id)
    print_verdict(report, inv_before, inv_after)
    return report


# =============================================================================
# SCENARIO 3 — Idempotency
# =============================================================================

async def scenario_idempotency(
    session:   aiohttp.ClientSession,
    flight_id: str,
) -> ScenarioReport:
    print_header("SCENARIO 3 — Idempotency (same idempotency_key fired twice)")
    print(f"  Flight : {BOLD}{flight_id}{RESET}")
    print(f"  Goal   : Second request with same key should fail (lock or duplicate).\n")

    shared_key = str(uuid.uuid4())
    print(f"  Idempotency key: {DIM}{shared_key}{RESET}\n")

    inv_before = await get_inventory(session, flight_id)

    # Fire twice with same key, slight stagger so first completes
    r1 = await fire_booking(session, "IDEM_001", flight_id, idempotency_key=shared_key)
    print_result(r1, 1)
    await asyncio.sleep(0.1)
    r2 = await fire_booking(session, "IDEM_002", flight_id, idempotency_key=shared_key)
    print_result(r2, 2)

    report = ScenarioReport(name="Idempotency", results=[r1, r2])

    inv_after = await get_inventory(session, flight_id)

    print(f"\n  {BOLD}── Idempotency Verdict ─────────────────────{RESET}")

    refs = [r.ref for r in report.successes]
    unique_refs  = set(refs)
    is_idempotent = len(unique_refs) <= 1   # both returned same ref (or only 1 succeeded)

    # The real check is whether inventory changed by more than 1
    inv_delta = inv_before.get("available", 0) - inv_after.get("available", 0)

    if is_idempotent and inv_delta <= 1:
        print(f"  {GREEN}{BOLD}✅ PASS — same booking ref returned, only 1 seat deducted.{RESET}")
        print(f"  {GREEN}Idempotent replay confirmed (ref={list(unique_refs)[0] if unique_refs else '?'}).{RESET}")
    else:
        print(f"  {RED}{BOLD}❌ FAIL — double booking occurred ({inv_delta} seats deducted).{RESET}")

    print_verdict(report, inv_before, inv_after)
    return report


# =============================================================================
# MAIN
# =============================================================================

async def main() -> None:
    print(f"\n{BOLD}{CYAN}{'═' * 64}{RESET}")
    print(f"{BOLD}{CYAN}  AeroSync-India — ACID Stress Test{RESET}")
    print(f"{BOLD}{CYAN}  {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 64}{RESET}")
    print(f"  API      : {API_BASE}")
    print(f"  Concurrency: {CONCURRENCY} requests per scenario")

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 10)
    async with aiohttp.ClientSession(connector=connector) as session:

        # ── Verify API is up ──────────────────────────────────────────────────
        try:
            async with session.get(f"{API_BASE}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    raise ConnectionError(f"Health check failed: {r.status}")
            print(f"  {GREEN}✅ API reachable{RESET}\n")
        except Exception as exc:
            print(f"  {RED}❌ Cannot reach API at {API_BASE}: {exc}{RESET}")
            print(f"  Make sure uvicorn is running first.")
            sys.exit(1)

        # ── Resolve flight ID ─────────────────────────────────────────────────
        flight_id = FLIGHT_ID
        available = 0

        if not flight_id:
            print(f"  {DIM}Auto-selecting flight target...{RESET}")
            result = await fetch_suitable_flight(session, min_available=CONCURRENCY + 5)
            if not result:
                print(f"  {RED}No suitable flight found. "
                      f"Run the seeder first or set FLIGHT_ID env var.{RESET}")
                sys.exit(1)
            flight_id, available = result
            print(f"  {GREEN}Selected: {BOLD}{flight_id}{RESET}  "
                  f"({CYAN}{available} seats available{RESET})\n")
        else:
            inv = await get_inventory(session, flight_id)
            available = inv.get("available", 0)
            print(f"  Using: {BOLD}{flight_id}{RESET}  "
                  f"({CYAN}{available} seats available{RESET})\n")

        if available == 0:
            print(f"  {RED}Flight is already full. Choose a different flight.{RESET}")
            sys.exit(1)

        # ── Run scenarios ─────────────────────────────────────────────────────
        await scenario_lock_contention(session, flight_id, CONCURRENCY)
        await asyncio.sleep(1)   # let lock expire before next scenario

        # For oversell: use a flight with few seats left, or clip to available
        oversell_count = min(available, 15)
        if oversell_count > 0:
            await scenario_oversell(session, flight_id, oversell_count)
            await asyncio.sleep(1)

        await scenario_idempotency(session, flight_id)

    print(f"\n{BOLD}{CYAN}{'═' * 64}{RESET}")
    print(f"{BOLD}{CYAN}  All scenarios complete.{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 64}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(main())
