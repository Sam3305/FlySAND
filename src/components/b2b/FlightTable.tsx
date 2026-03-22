import React from "react";
import { T } from "../../constants";
import { statusColor, loadColor, formatINR } from "../../utils";
import type { Flight } from "../../types";

interface Props {
  flights: Flight[];
}

const COL_HEADERS = ["FLT#", "ROUTE", "DEP", "ARR", "STATUS", "AIRCRAFT", "SEATS", "LOAD", "PRICE ₹"];

export const FlightTable: React.FC<Props> = ({ flights }) => (
  <div style={{
    border: `1px solid ${T.border}`,
    background: T.panel,
    display: "flex",
    flexDirection: "column",
    height: "100%",
  }}>
    {/* ── Panel header ── */}
    <div style={{
      padding: "8px 12px",
      borderBottom: `1px solid ${T.border}`,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      flexShrink: 0,
    }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: T.green, letterSpacing: "0.1em" }}>
        ▌ LIVE FLIGHT STATUS
      </span>
      <span style={{ fontSize: 9, color: T.textDm }}>DEL · BOM · CCU · MAA</span>
    </div>

    {/* ── Scrollable table ── */}
    <div style={{ overflowY: "auto", flex: 1 }}>
      <table style={{ width: "100%", fontSize: 10, borderCollapse: "collapse" }}>
        <thead style={{ position: "sticky", top: 0, background: T.panel, zIndex: 1 }}>
          <tr style={{ borderBottom: `1px solid ${T.border}` }}>
            {COL_HEADERS.map((h) => (
              <th key={h} style={{
                padding: "6px 10px", fontWeight: 400,
                color: T.textDm, textAlign: "left", whiteSpace: "nowrap",
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {flights.map((f) => (
            <tr key={f.id} style={{ borderBottom: `1px solid ${T.border}` }}>
              <td style={{ padding: "7px 10px", color: T.cyan, fontVariantNumeric: "tabular-nums" }}>
                {f.id}
              </td>
              <td style={{ padding: "7px 10px", color: T.textBt, fontWeight: 600 }}>
                {f.from}→{f.to}
              </td>
              <td style={{ padding: "7px 10px", color: T.text, fontVariantNumeric: "tabular-nums" }}>
                {f.dep}
              </td>
              <td style={{ padding: "7px 10px", color: T.text, fontVariantNumeric: "tabular-nums" }}>
                {f.arr}
              </td>
              <td style={{ padding: "7px 10px", color: statusColor(f.status), fontWeight: 700 }}>
                {f.status}
              </td>
              <td style={{ padding: "7px 10px", color: T.textDm }}>
                {f.aircraft}
              </td>
              <td style={{
                padding: "7px 10px",
                color: f.seats < 15 ? T.red : T.text,
                fontVariantNumeric: "tabular-nums",
              }}>
                {f.seats}
              </td>
              {/* ── Load bar ── */}
              <td style={{ padding: "7px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 44, height: 2, background: T.border, borderRadius: 1 }}>
                    <div style={{
                      height: "100%",
                      width: `${f.load}%`,
                      background: loadColor(f.load),
                      borderRadius: 1,
                      transition: "width 0.6s ease",
                    }} />
                  </div>
                  <span style={{ color: f.load > 85 ? T.red : T.text, fontVariantNumeric: "tabular-nums" }}>
                    {Math.round(f.load)}%
                  </span>
                </div>
              </td>
              {/* ── Price with direction indicator ── */}
              <td style={{ padding: "7px 10px", color: T.amber, fontVariantNumeric: "tabular-nums" }}>
                {formatINR(f.price)}
                <span style={{
                  marginLeft: 5,
                  fontSize: 9,
                  color: f._dir === "up" ? T.red : f._dir === "down" ? T.green : T.textDm,
                }}>
                  {f._dir === "up" ? "↑" : f._dir === "down" ? "↓" : "·"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  </div>
);
