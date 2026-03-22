import React from "react";
import { Radio } from "lucide-react";
import { T } from "../../constants";
import { useSwarmEventLog } from "../../hooks/useSwarmEventLog";
import type { Flight } from "../../types";

interface Props {
  swarmActive: boolean;
  eventCount:  number;
  flights:     Flight[];
}

export const SwarmStream: React.FC<Props> = ({ swarmActive, eventCount, flights }) => {
  const log = useSwarmEventLog(swarmActive, flights);

  return (
    <div style={{
      border: `1px solid ${T.border}`,
      background: T.panel,
      display: "flex",
      flexDirection: "column",
      height: "100%",
    }}>
      {/* ── Header ── */}
      <div
        className={swarmActive ? "swarm-active" : ""}
        style={{
          padding: "8px 12px",
          borderBottom: `1px solid ${T.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Radio size={10} color={swarmActive ? T.amber : T.green} />
          <span style={{
            fontSize: 10, fontWeight: 700,
            color: swarmActive ? T.amber : T.green,
            letterSpacing: "0.08em",
          }}>
            {swarmActive ? "⚡ AUTOBOOKING SWARM ACTIVE" : "▌ EVENT STREAM"}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 9, color: T.textDm }}>
            THROTTLE WINDOW: <span style={{ color: T.purple }}>500ms</span>
          </span>
          <span style={{ fontSize: 9, color: T.textDm }}>
            EVT/<span style={{ color: T.cyan }}>{eventCount.toLocaleString()}</span>
          </span>
        </div>
      </div>

      {/* ── Log entries ── */}
      <div style={{
        overflowY: "auto",
        flex: 1,
        padding: "6px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 1,
      }}>
        {log.length === 0 && (
          <div style={{ fontSize: 9, color: T.textDm }}>Awaiting events ···</div>
        )}
        {log.map((entry) => (
          <div
            key={entry.id}
            className="evt-row"
            style={{ display: "flex", gap: 10, fontSize: 9, lineHeight: 1.6 }}
          >
            <span style={{ color: T.textDm, flexShrink: 0, fontVariantNumeric: "tabular-nums" }}>
              {entry.ts}
            </span>
            <span style={{ color: entry.swarm ? T.amber : T.green }}>
              {entry.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
