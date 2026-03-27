import React from "react";
import { T } from "../../constants";
import type { DashboardStats } from "../../types";

interface Props {
  stats:   DashboardStats | null;
  loading: boolean;
}

const fmt = (n: number) =>
  n >= 1_00_00_000 ? `₹${(n / 1_00_00_000).toFixed(1)}Cr`
  : n >= 1_00_000  ? `₹${(n / 1_00_000).toFixed(1)}L`
  : `₹${n.toLocaleString("en-IN")}`;

export const StatsBar: React.FC<Props> = ({ stats: s, loading }) => {
  if (loading || !s) {
    return (
      <div style={{
        background: "#040608", borderBottom: `1px solid ${T.border}`,
        height: 30, display: "flex", alignItems: "center", padding: "0 14px",
      }}>
        <span style={{ fontSize: 9, color: T.textDm }}>Loading metrics…</span>
      </div>
    );
  }

  const healthColor = s.margin_pct >= 10 ? T.green : s.margin_pct >= 0 ? T.amber : T.red;

  const items: [string, string, string][] = [
    ["FLIGHTS",    s.total_flights.toLocaleString(),           T.cyan],
    ["SEATS SOLD", s.total_sold.toLocaleString(),              T.text],
    ["SYSTEM LF",  `${s.system_lf_pct.toFixed(1)}%`,          s.system_lf_pct >= 80 ? T.green : s.system_lf_pct >= 50 ? T.amber : T.red],
    ["ROUTES",     s.active_routes.toString(),                 T.text],
    ["BOOKINGS",   s.total_bookings.toLocaleString(),          T.text],
    ["REVENUE",    fmt(s.total_revenue_inr),                   T.amber],
    ["MARGIN",     `${s.margin_pct >= 0 ? "+" : ""}${s.margin_pct.toFixed(1)}%`, healthColor],
  ];

  return (
    <div style={{
      background: "#040608",
      borderBottom: `1px solid ${T.border}`,
      display: "flex",
      alignItems: "center",
      padding: "0 14px",
      height: 30,
      flexShrink: 0,
      gap: 0,
      overflowX: "auto",
    }}>
      {items.map(([label, value, color], i) => (
        <React.Fragment key={label}>
          {i > 0 && <span style={{ color: T.border, margin: "0 12px" }}>│</span>}
          <span style={{ fontSize: 9, color: T.textDm, whiteSpace: "nowrap" }}>
            {label}:{" "}
          </span>
          <span style={{ fontSize: 9, fontWeight: 700, color, marginLeft: 4, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
            {value}
          </span>
        </React.Fragment>
      ))}
    </div>
  );
};
