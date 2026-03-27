import type { Flight } from "../types";
import { WS_CONFIG } from "../constants";

// ─── Action shapes (mirror actual WS event_type values) ───────────────────────
export type FlightAction =
  | { type: "PRICE_UPDATE"; fid: string; delta: number }
  | { type: "SEAT_SOLD";    fid: string; count: number };

export interface BatchAction {
  type:    "BATCH";
  payload: FlightAction[];
}

// ─── Pure reducer ─────────────────────────────────────────────────────────────
export function flightReducer(flights: Flight[], action: BatchAction): Flight[] {
  if (action.payload.length === 0) return flights;

  // Build a mutable map for O(1) lookups
  const map = new Map<string, Flight>(flights.map((f) => [f.id, { ...f }]));

  for (const evt of action.payload) {
    const f = map.get(evt.fid);
    if (!f) continue;

    if (evt.type === "PRICE_UPDATE") {
      const raw = f.price + evt.delta;
      const clamped = Math.max(WS_CONFIG.PRICE_MIN, Math.min(WS_CONFIG.PRICE_MAX, raw));
      f._dir  = evt.delta > 0 ? "up" : evt.delta < 0 ? "down" : "flat";
      f._tick = (f._tick ?? 0) + 1;
      f.price = clamped;
    }

    if (evt.type === "SEAT_SOLD") {
      const newSeats = Math.max(0, f.seats - evt.count);
      // Derive total capacity from available seats + current load percentage
      // load = (sold / capacity) * 100 = ((capacity - available) / capacity) * 100
      // → capacity = available / (1 - load/100)
      const loadFrac = f.load / 100;
      const capacity = loadFrac < 1
        ? Math.round(f.seats / (1 - loadFrac))
        : f.seats + evt.count;
      f.seats = newSeats;
      // Use Math.ceil so that selling seats always strictly increases the load %
      f.load  = capacity > 0
        ? Math.min(100, Math.ceil(((capacity - newSeats) / capacity) * 100))
        : 100;
    }

    map.set(evt.fid, f);
  }

  return flights.map((f) => map.get(f.id) ?? f);
}
