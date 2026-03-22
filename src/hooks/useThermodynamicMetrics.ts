import { useState, useEffect } from "react";
import type { ThermodynamicMetrics } from "../types";
import { clamp } from "../utils";

const INITIAL: ThermodynamicMetrics = {
  CAPE:     2847,
  HDWIND:   47,
  QNH:      1012.3,
  TEMP:     -58,
  TROPO:    12.4,
  TURB:     "MOD",
  ICING:    "NIL",
  SIGMET:   "ACTIVE",
  WIND_DIR: "270°",
  ROUTES: {
    "DEL-BOM": { hw: 32, tw: 0,  turb: "LGT", eta: +4  },
    "DEL-CCU": { hw: 0,  tw: 28, turb: "NIL", eta: -7  },
    "DEL-MAA": { hw: 67, tw: 0,  turb: "MOD", eta: +12 },
    "BOM-CCU": { hw: 18, tw: 0,  turb: "LGT", eta: +3  },
  },
};

export function useThermodynamicMetrics(): ThermodynamicMetrics {
  const [metrics, setMetrics] = useState<ThermodynamicMetrics>(INITIAL);

  useEffect(() => {
    const timer = setInterval(() => {
      setMetrics((p) => ({
        ...p,
        CAPE:   Math.round(clamp(p.CAPE   + (Math.random() - 0.5) * 180, 400, 5000)),
        HDWIND: Math.round(clamp(p.HDWIND + (Math.random() - 0.5) * 9,   0,   130)),
        QNH:    +(p.QNH + (Math.random() - 0.5) * 0.4).toFixed(1),
        TEMP:   Math.round(p.TEMP + (Math.random() - 0.5) * 2),
      }));
    }, 2_800);

    return () => clearInterval(timer);
  }, []);

  return metrics;
}
