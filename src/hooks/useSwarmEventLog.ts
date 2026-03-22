import { useState, useEffect, useRef } from "react";
import type { Flight } from "../types";

export interface SwarmLogEntry {
  id:    number;
  text:  string;
  swarm: boolean;
  ts:    string;
}

const MAX_ENTRIES = 40;

type TemplateFn = (f: Flight) => string;

const TEMPLATES: TemplateFn[] = [
  (f) => `BOT_${String(Math.floor(Math.random() * 9999)).padStart(4, "0")}: LOCK ${f.id} ROW${Math.floor(Math.random() * 32) + 1}${["A","B","C","D","E","F"][Math.floor(Math.random() * 6)]}`,
  (f) => `PRICE_ENGINE: ${f.id} ${Math.round(f.price)} → ${Math.round(f.price + (Math.random() - 0.5) * 220)}`,
  (f) => `SEAT_SOLD: ${f.id}·PAX_ANON·${["1A","14C","22D","31F"][Math.floor(Math.random() * 4)]}`,
  (f) => `ML_SURGE: ${f.from}-${f.to} demand_multiplier=${+(Math.random() * 1.8 + 0.4).toFixed(2)}x`,
  (f) => `YIELD_CTRL: ${f.id} fare_class=${["Y","B","M","H","Q","V"][Math.floor(Math.random() * 6)]} adjusted`,
];

let _id = 0;

export function useSwarmEventLog(swarmActive: boolean, flights: Flight[]): SwarmLogEntry[] {
  const [log, setLog] = useState<SwarmLogEntry[]>([]);

  // Keep flights ref stable — we don't want the interval to restart on every render
  const flightsRef = useRef(flights);
  flightsRef.current = flights;

  useEffect(() => {
    const interval = setInterval(() => {
      if (Math.random() < 0.3) return; // occasional quiet ticks

      const f = flightsRef.current[Math.floor(Math.random() * flightsRef.current.length)];
      const tmpl = TEMPLATES[Math.floor(Math.random() * TEMPLATES.length)];

      const entry: SwarmLogEntry = {
        id:    ++_id,
        text:  tmpl(f),
        swarm: swarmActive,
        ts:    new Date().toLocaleTimeString("en-IN", { hour12: false }),
      };

      setLog((prev) => [entry, ...prev.slice(0, MAX_ENTRIES - 1)]);
    }, swarmActive ? 110 : 520);

    return () => clearInterval(interval);
  }, [swarmActive]); // re-create interval only when swarm state changes

  return log;
}
