"""
app/websockets/live_ops.py
/ws/live-ops — WebSocket endpoint.

Architecture:
  • A single shared Redis Pub/Sub subscription fans out to ALL connected WS clients.
  • ConnectionManager tracks active sockets and handles clean disconnections.
  • A dedicated asyncio task per server process bridges the Redis channel → all sockets.
  • Handles: SEAT_SOLD · PRICE_UPDATE · DISRUPTION_ALERT (and any future event_type).
"""

import asyncio
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.core.redis_client import create_pubsub

logger = logging.getLogger("orchestrator.websocket")
ws_router = APIRouter()

# Recognised inbound event types forwarded to clients
BROADCAST_EVENT_TYPES: Set[str] = {"SEAT_SOLD", "PRICE_UPDATE", "DISRUPTION_ALERT"}


# ─── Connection Manager ───────────────────────────────────────────────────────

class ConnectionManager:
    """Thread-safe registry of live WebSocket connections."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("WS client connected  (total=%d)", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("WS client disconnected (total=%d)", len(self._connections))

    async def broadcast(self, message: str) -> None:
        """Send *message* to every connected client; silently drop dead sockets."""
        dead: list[WebSocket] = []

        async with self._lock:
            targets = list(self._connections)

        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
            except Exception as exc:
                logger.debug("Failed to send to client, marking dead: %s", exc)
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


# ─── Redis → WebSocket bridge (singleton background task) ────────────────────

_bridge_task: asyncio.Task | None = None


async def _redis_to_ws_bridge() -> None:
    """
    Subscribes to REDIS_BROADCAST_CHANNEL.
    For every valid JSON message whose event_type is in BROADCAST_EVENT_TYPES,
    fan-out to all connected WebSocket clients.
    Reconnects automatically on transient Redis errors.
    """
    RECONNECT_DELAY = 2  # seconds

    while True:
        pubsub = None
        try:
            pubsub = await create_pubsub()
            await pubsub.subscribe(settings.REDIS_BROADCAST_CHANNEL)
            logger.info(
                "Redis Pub/Sub subscribed to channel '%s'",
                settings.REDIS_BROADCAST_CHANNEL,
            )

            async for raw_message in pubsub.listen():
                # pubsub.listen() yields control-messages (type='subscribe') first
                if raw_message["type"] != "message":
                    continue

                data: str = raw_message.get("data", "")
                try:
                    payload: dict = json.loads(data)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON payload on bus (ignored): %r", data)
                    continue

                event_type = payload.get("event_type", "UNKNOWN")
                if event_type not in BROADCAST_EVENT_TYPES:
                    logger.debug("Unrecognised event_type=%r — skipping WS broadcast", event_type)
                    continue

                if manager.client_count == 0:
                    continue  # no-op: nobody is listening

                await manager.broadcast(json.dumps(payload))
                logger.debug(
                    "Broadcast %s → %d client(s)", event_type, manager.client_count
                )

        except asyncio.CancelledError:
            logger.info("Redis→WS bridge task cancelled")
            break

        except Exception as exc:
            logger.error(
                "Redis Pub/Sub bridge error: %s — reconnecting in %ds …",
                exc,
                RECONNECT_DELAY,
            )
            await asyncio.sleep(RECONNECT_DELAY)

        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(settings.REDIS_BROADCAST_CHANNEL)
                    await pubsub.aclose()
                except Exception:
                    pass


def ensure_bridge_running() -> None:
    """Lazily start the bridge task the first time a WS client connects."""
    global _bridge_task
    if _bridge_task is None or _bridge_task.done():
        _bridge_task = asyncio.create_task(_redis_to_ws_bridge())
        logger.info("Redis→WS bridge task started")


# ─── WebSocket endpoint ───────────────────────────────────────────────────────

@ws_router.websocket("/ws/live-ops")
async def live_ops_ws(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time flight-ops events.

    Clients receive JSON frames with the following shape:

        {
          "event_type": "SEAT_SOLD" | "PRICE_UPDATE" | "DISRUPTION_ALERT",
          ... event-specific fields ...
        }

    The server sends a welcome frame immediately on connection, and echoes a
    pong frame for any incoming `{"type":"ping"}` message.
    """
    ensure_bridge_running()
    await manager.connect(websocket)

    # Welcome frame — lets clients know they're live
    await websocket.send_json(
        {
            "event_type": "CONNECTED",
            "message": "Live-ops stream active. Subscribed to SEAT_SOLD · PRICE_UPDATE · DISRUPTION_ALERT.",
        }
    )

    try:
        while True:
            # Keep the connection alive; handle client-side pings
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    msg = json.loads(raw)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                except json.JSONDecodeError:
                    pass  # non-JSON client messages are silently ignored

            except asyncio.TimeoutError:
                # Send a server-side keepalive ping to detect dead TCP connections
                try:
                    await websocket.send_json({"type": "keepalive"})
                except Exception:
                    break  # socket is dead

    except WebSocketDisconnect as exc:
        logger.info("WS client disconnected cleanly (code=%s)", exc.code)
    except Exception as exc:
        logger.warning("WS client disconnected with error: %s", exc)
    finally:
        await manager.disconnect(websocket)
