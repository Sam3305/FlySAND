import React from "react";
import { T } from "../../constants";
import type { Flight } from "../../types";

interface Props {
  flights:     Flight[];
  swarmActive: boolean;
}

export const StatsBar: React.FC<Props> = ({ flights, swarmActive }) => {
  const avgLoad = flights.length
    ? Math.round(flights.reduce((a, f) => a + f.load, 0) / flights.length)
    : 0;

  const stats: [string, string | number, string][] = [
    ["ACTIVE FLT",  flights.length,                                               T.cyan],
    ["DELAYED",     flights.filter((f) => f.status === "DELAYED").length,         T.amber],
    ["BOARDING",    flights.filter((f) => f.status === "BOARDING").length,        T.green],
    ["AVG LOAD",    `${avgLoad}%`,                                                T.text],
    ["SEATS TOT",   flights.reduce((a, f) => a + f.seats, 0),                    T.text],
    ["FLIGHTS",     `${flights.filter((f) => f.status === "ON TIME").length} OTP`,T.green],
    ["EVT RATE",    swarmActive ? "~30/s" : "~2/s",                               swarmActive ? T.amber : T.green],
  ];

  return (
    <div style={{
      background: "#040404",
      borderBottom: `1px solid ${T.border}`,
      display: "flex",
      alignItems: "center",
      padding: "0 14px",
      height: 32,
      flexShrink: 0,
      overflowX: "auto",
      gap: 0,
    }}>
      {stats.map(([label, value, color], i) => (
        <div key={label} style={{ display: "flex", alignItems: "center" }}>
          {i > 0 && <span style={{ color: T.border, margin: "0 12px" }}>│</span>}
          <span style={{ fontSize: 10, color: T.textDm }}>{label}: </span>
          <span style={{ fontSize: 10, fontWeight: 600, color, marginLeft: 4, fontVariantNumeric: "tabular-nums" }}>
            {value}
          </span>
        </div>
      ))}
    </div>
  );
};
