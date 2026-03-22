import React from "react";
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import { T } from "../../constants";
import type { CaskRaskDataPoint } from "../../types";

// ── Custom tooltip ──────────────────────────────────────────────────────────
interface TooltipProps {
  active?:  boolean;
  payload?: { dataKey: string; value: number; color: string }[];
  label?:   string;
}

const CASKTooltip: React.FC<TooltipProps> = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;

  const spread = payload.length === 2
    ? Math.abs(payload[1].value - payload[0].value)
    : 0;

  return (
    <div style={{
      background: "#0a0a0a", border: `1px solid ${T.borderBt}`,
      padding: "8px 12px", fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
    }}>
      <div style={{ color: T.textDm, marginBottom: 4 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.dataKey}: {p.value.toFixed(3)} ₹/ASK
        </div>
      ))}
      {payload.length === 2 && (
        <div style={{
          marginTop: 4, paddingTop: 4,
          borderTop: `1px solid ${T.border}`,
          color: spread > 0.3 ? T.red : T.green,
        }}>
          SPREAD: {(spread * 1000).toFixed(1)} paisa
        </div>
      )}
    </div>
  );
};

// ── Chart axis tick style ──────────────────────────────────────────────────
const TICK_STYLE = {
  fill:       T.textDm,
  fontSize:   8,
  fontFamily: "'JetBrains Mono', monospace",
};

// ── Panel ──────────────────────────────────────────────────────────────────
interface Props {
  data: CaskRaskDataPoint[];
}

export const CASKRASKPanel: React.FC<Props> = ({ data }) => {
  const last   = data[data.length - 1];
  const spread = last ? (last.RASK - last.CASK).toFixed(3) : "—";
  const spreadNum = last ? last.RASK - last.CASK : 0;

  return (
    <div style={{ border: `1px solid ${T.border}`, background: T.panel, display: "flex", flexDirection: "column" }}>
      {/* ── Header ── */}
      <div style={{
        padding: "8px 12px", borderBottom: `1px solid ${T.border}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <div>
          <span style={{ fontSize: 10, fontWeight: 700, color: T.amber, letterSpacing: "0.1em" }}>
            ▌ CASK vs RASK
          </span>
          <span style={{ fontSize: 9, color: T.textDm, marginLeft: 8 }}>
            COST / REVENUE PER AVAILABLE SEAT KM
          </span>
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 9, alignItems: "center" }}>
          <span style={{ color: T.red }}>■ CASK</span>
          <span style={{ color: T.cyan }}>■ RASK</span>
          <span style={{
            color: spreadNum > 0 ? T.green : T.red,
            background: spreadNum > 0 ? `${T.green}12` : `${T.red}12`,
            padding: "2px 6px",
          }}>
            SPREAD {spreadNum > 0 ? "+" : ""}{spread}
          </span>
        </div>
      </div>

      {/* ── Recharts line chart ──
          isAnimationActive={false} is critical — without it, every new data
          point triggers a full SVG re-draw animation, causing visible flicker
          at the 1.8s update cadence.
      ── */}
      <div style={{ padding: "8px 4px 4px", height: 200 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, left: -24, bottom: 0 }}>
            <CartesianGrid strokeDasharray="2 4" stroke={T.border} vertical={false} />
            <XAxis
              dataKey="t"
              tick={TICK_STYLE}
              tickLine={false}
              axisLine={{ stroke: T.border }}
              interval="preserveStartEnd"
            />
            <YAxis
              tick={TICK_STYLE}
              tickLine={false}
              axisLine={{ stroke: T.border }}
              domain={["auto", "auto"]}
              tickFormatter={(v) => v.toFixed(2)}
            />
            <Tooltip content={<CASKTooltip />} />
            <ReferenceLine y={0} stroke={T.border} />
            <Line
              type="monotone"
              dataKey="CASK"
              stroke={T.red}
              dot={false}
              strokeWidth={1.5}
              isAnimationActive={false}   // ← prevents DOM thrash on tick
            />
            <Line
              type="monotone"
              dataKey="RASK"
              stroke={T.cyan}
              dot={false}
              strokeWidth={1.5}
              isAnimationActive={false}   // ← prevents DOM thrash on tick
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
