import { useState, useEffect, useMemo } from "react";
import type { CaskRaskDataPoint } from "../types";
import { clamp } from "../utils";

const SEED_POINTS = 25;
const UPDATE_MS   = 1_800;

function seedData(): CaskRaskDataPoint[] {
  return Array.from({ length: SEED_POINTS }, (_, i) => {
    const h = 5 + Math.floor(i / 2);
    const m = i % 2 === 0 ? "00" : "30";
    return {
      t:    `${String(h).padStart(2, "0")}:${m}`,
      CASK: +(3.1 + Math.random() * 0.5).toFixed(3),
      RASK: +(3.7 + Math.random() * 0.7).toFixed(3),
    };
  });
}

export function useCASKRASK(): CaskRaskDataPoint[] {
  const initial = useMemo(seedData, []);
  const [data, setData] = useState<CaskRaskDataPoint[]>(initial);

  useEffect(() => {
    const timer = setInterval(() => {
      setData((prev) => {
        const last = prev[prev.length - 1];
        const now  = new Date();
        const t    = now.toLocaleTimeString("en-IN", { hour12: false });

        const next: CaskRaskDataPoint = {
          t,
          CASK: +clamp(last.CASK + (Math.random() - 0.52) * 0.09, 2.5, 4.5).toFixed(3),
          RASK: +clamp(last.RASK + (Math.random() - 0.42) * 0.11, 2.9, 5.2).toFixed(3),
        };

        return [...prev.slice(-34), next]; // keep a rolling 35-point window
      });
    }, UPDATE_MS);

    return () => clearInterval(timer);
  }, []);

  return data;
}
