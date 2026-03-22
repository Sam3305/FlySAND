import React from "react";
import { T } from "../../constants";
import { useCASKRASK, useThermodynamicMetrics } from "../../hooks";
import type { LiveFlightState } from "../../types";

import { AOCCHeader }   from "./AOCCHeader";
import { StatsBar }     from "./StatsBar";
import { FlightTable }  from "./FlightTable";
import { CASKRASKPanel } from "./CASKRASKPanel";
import { ThermoPanel }  from "./ThermoPanel";
import { SwarmStream }  from "./SwarmStream";
import { NetworkPanel } from "./NetworkPanel";

interface Props {
  live: LiveFlightState;
}

export const AOCCDashboard: React.FC<Props> = ({ live }) => {
  const caskData = useCASKRASK();
  const thermo   = useThermodynamicMetrics();

  return (
    <div
      className="b2b"
      style={{
        minHeight: "100vh",
        background: T.bg,
        display: "flex",
        flexDirection: "column",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* CRT scan-line effect */}
      <div className="scanline" />

      <AOCCHeader live={live} />
      <StatsBar flights={live.flights} swarmActive={live.swarmActive} />

      {/*
       * Main grid — 3-column layout:
       *   Col 1+2  → Flight table (row 1), CASK/RASK chart (row 2)
       *   Col 3    → Thermo + Network panels (spans rows 1–2)
       *   Col 1–3  → Swarm event stream (row 3, full width)
       */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        gridTemplateRows: "auto auto 1fr",
        gap: 8,
        padding: 8,
        flex: 1,
        minHeight: 0,
      }}>
        {/* ── Row 1: Flight table ── */}
        <div style={{ gridColumn: "1 / 3", minHeight: 280 }}>
          <FlightTable flights={live.flights} />
        </div>

        {/* ── Col 3 rows 1–2: Thermo + Network ── */}
        <div style={{ gridRow: "1 / 3", display: "flex", flexDirection: "column", gap: 8 }}>
          <ThermoPanel metrics={thermo} />
          <NetworkPanel flights={live.flights} />
        </div>

        {/* ── Row 2: CASK/RASK chart ── */}
        <div style={{ gridColumn: "1 / 3" }}>
          <CASKRASKPanel data={caskData} />
        </div>

        {/* ── Row 3: Autobooking Swarm event stream ── */}
        <div style={{ gridColumn: "1 / 4", minHeight: 170 }}>
          <SwarmStream
            swarmActive={live.swarmActive}
            eventCount={live.eventCount}
            flights={live.flights}
          />
        </div>
      </div>
    </div>
  );
};
