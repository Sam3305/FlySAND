"""
app/main.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  FastAPI Application Orchestrator
──────────────────────────────────────────────────────────────────────────────

Responsibilities:
  1. Application factory — single ``app`` instance consumed by Uvicorn.
  2. Lifespan manager    — ordered startup/shutdown of Motor + game-loop task.
  3. Middleware          — CORS configured from ``settings.CORS_ORIGINS``.
  4. Router mounting     — booking, flights read, and WebSocket live-ops.

Lifespan sequence
──────────────────
  Startup:
    connect_mongo()              — Motor client + connection ping
    asyncio.create_task(
      start_game_loop()          — Redis Pub/Sub → pricing pipeline daemon
    )

  Shutdown:
    close_mongo()                — graceful Motor teardown

  The game-loop task is fire-and-forget; asyncio cancels it automatically
  when the event loop is shut down by Uvicorn's signal handler.

Router prefixes
───────────────
  /api/v1/book     ← booking.router     (POST)
  /api/v1/flights  ← flights.router     (GET)
  /ws/live-ops     ← live_ops.ws_router (WebSocket, no prefix — path is absolute)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.db import close_mongo, connect_mongo
from app.tasks.game_loop import start_game_loop

# Route modules
from app.api.routes.booking import router as booking_router
from app.api.routes.flights import router as flights_router
from app.websockets.live_ops import ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("orchestrator.main")


# ---------------------------------------------------------------------------
# Lifespan — replaces the deprecated @app.on_event("startup/shutdown") pattern
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Async context manager executed once per process lifetime by Uvicorn.

    Everything *before* ``yield`` runs at startup;
    everything *after* ``yield`` runs at shutdown.
    """

    # ── STARTUP ──────────────────────────────────────────────────────────────
    logger.info("AeroSync-India starting up …")

    # 1. Motor client — must be ready before any request is processed.
    await connect_mongo()
    logger.info("✅  MongoDB client connected.")

    # 2. Game-loop daemon — subscribes to WEATHER_SEVERE events and drives
    #    the repricing pipeline.  Created as a background task so startup
    #    is not blocked by the subscription handshake.
    game_loop_task = asyncio.create_task(start_game_loop())
    logger.info("✅  Game-loop task spawned (task_id=%s).", id(game_loop_task))

    # Hand control back to Uvicorn — the application is now live.
    yield

    # ── SHUTDOWN ─────────────────────────────────────────────────────────────
    logger.info("AeroSync-India shutting down …")

    # Cancel the game-loop task explicitly so it can unsubscribe from Redis
    # and close its PubSub connection cleanly before the event loop tears down.
    if not game_loop_task.done():
        game_loop_task.cancel()
        try:
            await game_loop_task
        except asyncio.CancelledError:
            pass  # expected; the loop handles CancelledError internally
        logger.info("Game-loop task cancelled.")

    # Close the Motor client last — game-loop may still write to Mongo during
    # its final repricing cycle.
    await close_mongo()
    logger.info("✅  MongoDB client closed. Shutdown complete.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AeroSync-India",
    description=(
        "Async airline simulation backend — Async FastAPI + MongoDB + Redis. "
        "Real-time seat inventory, physics-derived fare floors, and ML dynamic pricing "
        "for IndiGo's Golden Quadrilateral routes."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# REST endpoints under /api/v1
app.include_router(booking_router, prefix="/api/v1", tags=["Booking"])
app.include_router(flights_router, prefix="/api/v1", tags=["Flights"])

# WebSocket endpoint — ws_router already defines the full path "/ws/live-ops"
app.include_router(ws_router, tags=["Live Ops"])


# ---------------------------------------------------------------------------
# Health probe — lightweight liveness check for load balancers / K8s probes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Ops"], summary="Liveness probe")
async def health() -> dict[str, str]:
    """Returns ``{"status": "ok"}`` when the process is alive."""
    return {"status": "ok"}
