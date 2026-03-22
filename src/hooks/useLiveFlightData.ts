import { useReducer, useEffect, useRef, useCallback, useState } from "react";
import throttle from "lodash/throttle";
import type { LiveFlightState, WsEvent } from "../types";
import { SEED_FLIGHTS, WS_CONFIG } from "../constants";
import { flightReducer } from "../store/flightReducer";

/**
 * useLiveFlightData
 * ─────────────────
 * Simulates a FastAPI WebSocket producing two event types:
 *   • PRICE_UPDATE — fired at ~2/s normally, ~30/s during Autobooking Swarm
 *   • SEAT_SOLD    — fired exclusively during swarm bursts
 *
 * Batching strategy:
 *   Incoming events are pushed to `pendingUpdates` (a ref — no re-render).
 *   `throttledFlush` (lodash throttle, trailing=true, 500ms) drains the
 *   buffer into a single `dispatch({ type: "BATCH", payload })` call.
 *   Result: React sees AT MOST 2 re-renders/sec regardless of event velocity.
 *
 * In production: replace the setInterval simulation with a real WebSocket:
 *   const ws = new WebSocket(WS_ENDPOINT);
 *   ws.onmessage = (e) => enqueue(JSON.parse(e.data));
 */
export function useLiveFlightData(): LiveFlightState {
  const [flights, dispatch] = useReducer(flightReducer, SEED_FLIGHTS);
  const [connected,   setConnected]   = useState(false);
  const [eventCount,  setEventCount]  = useState(0);
  const [swarmActive, setSwarmActive] = useState(false);
  const [batchSize,   setBatchSize]   = useState(0);

  // Mutable buffer — never triggers renders by itself
  const pendingUpdates = useRef<WsEvent[]>([]);
  const evtCountRef    = useRef(0);

  // Keep dispatch ref stable across renders (avoids stale closures in callbacks)
  const dispatchRef = useRef(dispatch);
  dispatchRef.current = dispatch;

  // ── Throttled flush ────────────────────────────────────────────────────────
  // Created once via useRef so the throttle timer is never reset.
  const throttledFlush = useRef(
    throttle(
      () => {
        const batch = pendingUpdates.current.splice(0); // drain atomically
        if (!batch.length) return;
        setBatchSize(batch.length);
        dispatchRef.current({ type: "BATCH", payload: batch });
      },
      WS_CONFIG.THROTTLE_MS,
      { leading: false, trailing: true }
    )
  ).current;

  // ── Enqueue helper ─────────────────────────────────────────────────────────
  const enqueue = useCallback(
    (event: WsEvent) => {
      pendingUpdates.current.push(event);
      evtCountRef.current += 1;
      setEventCount(evtCountRef.current);
      throttledFlush(); // idempotent — lodash handles de-duplication internally
    },
    [throttledFlush]
  );

  // ── Simulated WS feed ──────────────────────────────────────────────────────
  useEffect(() => {
    setConnected(true);

    const pickFlight = () =>
      SEED_FLIGHTS[Math.floor(Math.random() * SEED_FLIGHTS.length)];

    // Normal cadence: random price drift every ~480ms
    const normalTimer = setInterval(() => {
      const f = pickFlight();
      enqueue({
        type:  "PRICE_UPDATE",
        fid:   f.id,
        delta: Math.round((Math.random() - 0.46) * WS_CONFIG.NORMAL_DELTA),
      });
    }, WS_CONFIG.NORMAL_INTERVAL);

    // Swarm: activates every 18s, fires ~30 evt/s for 4s
    const swarmCycleTimer = setInterval(() => {
      setSwarmActive(true);
      let count = 0;

      const burst = setInterval(() => {
        const f = pickFlight();

        enqueue({
          type:  "PRICE_UPDATE",
          fid:   f.id,
          delta: Math.round((Math.random() - 0.28) * WS_CONFIG.SWARM_DELTA),
        });
        enqueue({
          type:  "SEAT_SOLD",
          fid:   f.id,
          count: Math.ceil(Math.random() * 3),
        });

        if (++count >= WS_CONFIG.SWARM_EVENT_COUNT) {
          clearInterval(burst);
          setSwarmActive(false);
        }
      }, WS_CONFIG.SWARM_INTERVAL_MS);
    }, WS_CONFIG.SWARM_CYCLE_MS);

    return () => {
      clearInterval(normalTimer);
      clearInterval(swarmCycleTimer);
      throttledFlush.cancel(); // flush any queued batch on unmount
      setConnected(false);
    };
  }, [enqueue, throttledFlush]);

  return { flights, connected, eventCount, swarmActive, batchSize };
}
