import React from "react";
import { Wind } from "lucide-react";
import { T } from "../../constants";
import { capeColor, capeSeverity, hdwindColor, hdwindLabel, turbColor } from "../../utils";
import type { ThermodynamicMetrics } from "../../types";

interface Props {
  metrics: ThermodynamicMetrics;
}

export const ThermoPanel: React.FC<Props> = ({ metrics: m }) => {
  const rows: [string, string, string, string | null][] = [
    [
      "CAPE INSTABILITY",
      `${Math.round(m.CAPE)} J/kg`,
      capeColor(m.CAPE),
      capeSeverity(m.CAPE),
    ],
    [
      "HEADWIND",
      `${Math.round(m.HDWIND)} kph ${m.WIND_DIR}`,
      hdwindColor(m.HDWIND),
      hdwindLabel(m.HDWIND),
    ],
    ["QNH PRESSURE",  `${m.QNH} hPa`,   T.text,              null],
    ["TEMP @ FL350",  `${m.TEMP}°C`,     T.text,              null],
    ["TROPOPAUSE",    `${m.TROPO} km`,   T.text,              null],
    [
      "TURBULENCE",
      m.TURB,
      turbColor(m.TURB),
      null,
    ],
    [
      "SIGMET",
      m.SIGMET,
      m.SIGMET === "ACTIVE" ? T.amber : T.green,
      null,
    ],
  ];

  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.panel }}>
      {/* ── Header ── */}
      <div style={{
        padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: T.cyan, letterSpacing: "0.1em" }}>
          ▌ THERMODYNAMIC METRICS
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Wind size={10} color={T.textDm} />
          <span style={{ fontSize: 9, color: T.textDm }}>LIVE FEED</span>
        </div>
      </div>

      {/* ── Metric rows ── */}
      <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: 7 }}>
        {rows.map(([label, value, color, badge]) => (
          <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontSize: 9, color: T.textDm, letterSpacing: "0.06em" }}>{label}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color, fontVariantNumeric: "tabular-nums" }}>
                {value}
              </span>
              {badge && (
                <span style={{
                  fontSize: 8, color,
                  background: `${color}12`,
                  padding: "1px 5px",
                  letterSpacing: "0.08em",
                }}>
                  {badge}
                </span>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* ── Route wind impact ── */}
      <div style={{ borderTop: `1px solid ${T.border}`, padding: "8px 12px" }}>
        <div style={{ fontSize: 9, color: T.textDm, marginBottom: 6, letterSpacing: "0.1em" }}>
          ROUTE WIND IMPACT
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {Object.entries(m.ROUTES).map(([route, data]) => (
            <div key={route} style={{ display: "flex", justifyContent: "space-between", fontSize: 9 }}>
              <span style={{ color: T.text }}>{route}</span>
              <span style={{
                color: data.eta > 0 ? T.red : T.green,
                fontVariantNumeric: "tabular-nums",
              }}>
                {data.eta > 0 ? "+" : ""}{data.eta}m
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
