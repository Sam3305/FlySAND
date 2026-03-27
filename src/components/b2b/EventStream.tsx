import React, { useRef, useEffect } from "react";
import { T } from "../../constants";
import type { WsEvent } from "../../types";

interface Props {
  events:    WsEvent[];
  connected: boolean;
}

const eventColor = (type: string) => {
  if (type === "SEAT_SOLD")         return T.green;
  if (type === "PRICE_UPDATE")      return T.amber;
  if (type === "DISRUPTION_RESOLVED") return T.red;
  return T.textDm;
};

const eventLabel = (evt: WsEvent): string => {
  switch (evt.event_type) {
    case "SEAT_SOLD": {
      const e = evt as any;
      return `BOOKING  ${e.flight_id?.split("_")[0] || ""}  ${e.seats_sold}×seat  ₹${(e.price_charged_inr || 0).toLocaleString("en-IN")}  ref:${e.booking_ref || ""}`;
    }
    case "PRICE_UPDATE": {
      const e = evt as any;
      const dir = e.new_fare > e.old_fare ? "▲" : "▼";
      return `REPRICE  ${e.flight_id?.split("_")[0] || ""}  ${dir} ₹${(e.old_fare || 0).toLocaleString("en-IN")} → ₹${(e.new_fare || 0).toLocaleString("en-IN")}  [${e.agent || ""}]`;
    }
    case "DISRUPTION_RESOLVED": {
      const e = evt as any;
      return `DISRUPTION  ${e.route || ""}  ${e.rebooked}↗ ${e.vouchered}✗`;
    }
    default:
      return evt.event_type;
  }
};

export const EventStream: React.FC<Props> = ({ events, connected }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events.length]);

  return (
    <div style={{
      border: `1px solid ${T.border}`,
      background: T.panel,
      display: "flex",
      flexDirection: "column",
      height: "100%",
    }}>
      {/* Header */}
      <div style={{
        padding: "7px 12px",
        borderBottom: `1px solid ${T.border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: T.cyan, letterSpacing: "0.08em" }}>
          ▌ EVENT STREAM
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
          <div style={{
            width: 5, height: 5, borderRadius: "50%",
            background: connected ? T.green : T.red,
            animation: connected ? "pulse 2s infinite" : "none",
          }} />
          <span style={{ fontSize: 9, color: T.textDm }}>
            {connected ? "REDIS LIVE" : "RECONNECTING"}
          </span>
        </div>
      </div>

      {/* Legend */}
      <div style={{
        padding: "4px 12px",
        borderBottom: `1px solid ${T.border}`,
        display: "flex",
        gap: 12,
        flexShrink: 0,
      }}>
        {[["BOOKING", T.green], ["REPRICE", T.amber], ["DISRUPTION", T.red]].map(([l, c]) => (
          <span key={l} style={{ fontSize: 8, color: c as string }}>■ {l}</span>
        ))}
      </div>

      {/* Events */}
      <div style={{
        overflowY: "auto",
        flex: 1,
        padding: "6px 10px",
        display: "flex",
        flexDirection: "column-reverse",
        gap: 1,
      }}>
        {events.length === 0 && (
          <div style={{ fontSize: 9, color: T.textDm }}>
            {connected ? "Waiting for events…" : "Connecting to live stream…"}
          </div>
        )}
        {events.map((evt, i) => {
          const color = eventColor(evt.event_type);
          const label = eventLabel(evt);
          const ts    = (evt as any).timestamp_utc || (evt as any).timestamp || "";
          const time  = ts ? new Date(ts).toLocaleTimeString("en-IN", { hour12: false }) : "";
          return (
            <div key={i} style={{
              display: "flex",
              gap: 8,
              fontSize: 9,
              lineHeight: 1.7,
              borderBottom: `1px solid ${T.border}20`,
              padding: "1px 0",
            }}>
              <span style={{ color: T.textDm, flexShrink: 0, fontVariantNumeric: "tabular-nums", minWidth: 56 }}>
                {time}
              </span>
              <span style={{ color, wordBreak: "break-all" }}>
                {label}
              </span>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>
    </div>
  );
};
