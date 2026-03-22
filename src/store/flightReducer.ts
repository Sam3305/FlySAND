import type { Flight, WsEvent } from "../types";
import { WS_CONFIG } from "../constants";
import { clamp } from "../utils";

// ─── Actions ──────────────────────────────────────────────────────────────────
export interface BatchAction {
  type: "BATCH";
  payload: WsEvent[];
}

export type FlightAction = BatchAction;

// ─── Reducer ──────────────────────────────────────────────────────────────────
export function flightReducer(state: Flight[], action: FlightAction): Flight[] {
  if (action.type !== "BATCH") return state;

  return state.map((flight) => {
    const relevantEvents = action.payload.filter((e) => e.fid === flight.id);
    if (!relevantEvents.length) return flight;

    let updated: Flight = { ...flight };

    for (const event of relevantEvents) {
      if (event.type === "PRICE_UPDATE") {
        updated = {
          ...updated,
          price: clamp(updated.price + event.delta, WS_CONFIG.PRICE_MIN, WS_CONFIG.PRICE_MAX),
          _dir:  event.delta > 0 ? "up" : "down",
          _tick: Date.now() + Math.random(), // unique key trigger
        };
      }

      if (event.type === "SEAT_SOLD") {
        updated = {
          ...updated,
          seats: Math.max(0, updated.seats - event.count),
          load:  Math.min(100, updated.load + event.count * 0.4),
        };
      }
    }

    return updated;
  });
}
