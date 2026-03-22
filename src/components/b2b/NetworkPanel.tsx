import React from "react";
import { T, AIRPORTS, AIRPORT_CODES } from "../../constants";
import { formatINR } from "../../utils";
import type { Flight } from "../../types";

interface Props {
  flights: Flight[];
}

export const NetworkPanel: React.FC<Props> = ({ flights }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
    {/* ── Airport tiles ── */}
    <div style={{ border: `1px solid ${T.border}`, background: T.panel, padding: "8px 12px" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: T.green, letterSpacing: "0.1em", marginBottom: 8 }}>
        ▌ NETWORK SCOPE
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
        {AIRPORT_CODES.map((code) => {
          const ops = flights.filter((f) => f.from === code || f.to === code).length;
          return (
            <div key={code} style={{ border: `1px solid ${T.border}`, padding: "8px 10px" }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: T.cyan }}>{code}</div>
              <div style={{ fontSize: 9, color: T.textDm }}>{AIRPORTS[code].city}</div>
              <div style={{ fontSize: 9, color: T.textDm, marginTop: 2 }}>
                Terminal {AIRPORTS[code].terminal}
              </div>
              <div style={{ fontSize: 9, color: T.green, marginTop: 2 }}>{ops} FLT</div>
            </div>
          );
        })}
      </div>
    </div>

    {/* ── Revenue snapshot ── */}
    <div style={{ border: `1px solid ${T.border}`, background: T.panel, padding: "8px 12px" }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: T.amber, letterSpacing: "0.1em", marginBottom: 8 }}>
        ▌ REV SNAPSHOT
      </div>
      {flights.map((f) => {
        // Estimated revenue = price × load% × 1.7 (proxy for seat count)
        const estRev = f.price * f.load * 1.7;
        return (
          <div key={f.id} style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "3px 0",
            borderBottom: `1px solid ${T.border}`,
          }}>
            <span style={{ fontSize: 9, color: T.cyan }}>{f.id}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 9, color: T.textDm, fontVariantNumeric: "tabular-nums" }}>
                ₹{formatINR(estRev)}
              </span>
              <span style={{
                fontSize: 9,
                color: f._dir === "up" ? T.green : f._dir === "down" ? T.red : T.textDm,
              }}>
                {f._dir === "up" ? "▲" : f._dir === "down" ? "▼" : "─"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  </div>
);
