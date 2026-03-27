/**
 * useLiveFlightData
 * Connects to the real FastAPI WebSocket at /ws/live-ops.
 * Receives real SEAT_SOLD and PRICE_UPDATE events from Redis.
 * Polls /api/v1/dashboard/stats every 30s for aggregate KPIs.
 */
import { useEffect, useRef, useState, useCallback } from "react";
import type { WsEvent, DashboardStats } from "../types";
import { WS_URL, API_BASE } from "../constants";

export interface LiveOpsState {
  connected:   boolean;
  eventCount:  number;
  events:      WsEvent[];         // last 100 events
  stats:       DashboardStats | null;
  statsLoading: boolean;
}

const MAX_EVENTS = 100;

export function useLiveFlightData(): LiveOpsState {
  const [connected,    setConnected]    = useState(false);
  const [eventCount,   setEventCount]   = useState(0);
  const [events,       setEvents]       = useState<WsEvent[]>([]);
  const [stats,        setStats]        = useState<DashboardStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);

  const wsRef      = useRef<WebSocket | null>(null);
  const countRef   = useRef(0);
  const reconnectT = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Stats polling ────────────────────────────────────────────────────────
  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/dashboard/stats`);
      if (res.ok) {
        const data = await res.json();
        setStats(data);
      }
    } catch {
      // backend not ready yet — ignore
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
    const t = setInterval(fetchStats, 30_000);
    return () => clearInterval(t);
  }, [fetchStats]);

  // ── WebSocket ─────────────────────────────────────────────────────────────
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
    };

    ws.onmessage = (e) => {
      try {
        const evt: WsEvent = JSON.parse(e.data);
        if ((evt as any).type === "keepalive" || (evt as any).type === "pong") return;
        if (evt.event_type === "CONNECTED") return;

        countRef.current += 1;
        setEventCount(countRef.current);
        setEvents((prev) => [evt, ...prev].slice(0, MAX_EVENTS));

        // Refresh stats after a SEAT_SOLD so numbers stay current
        if (evt.event_type === "SEAT_SOLD") {
          setTimeout(fetchStats, 500);
        }
      } catch {
        // non-JSON keepalive frame — ignore
      }
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      // Reconnect after 3s
      reconnectT.current = setTimeout(connect, 3_000);
    };

    // Ping every 20s to keep alive
    const pingT = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, 20_000);

    return () => clearInterval(pingT);
  }, [fetchStats]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectT.current) clearTimeout(reconnectT.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, eventCount, events, stats, statsLoading };
}
