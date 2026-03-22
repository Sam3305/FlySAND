import React from "react";
import { Zap } from "lucide-react";
import { T } from "../../constants";

interface Props {
  connected:   boolean;
  eventCount:  number;
  swarmActive: boolean;
  variant?: "b2c" | "b2b";
}

export const WsStatusBadge: React.FC<Props> = ({
  connected,
  eventCount,
  swarmActive,
  variant = "b2c",
}) => {
  if (variant === "b2b") {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div
          style={{
            width: 5, height: 5, borderRadius: "50%",
            background: connected ? T.green : T.red,
            animation: connected ? "pulse 2s infinite" : "none",
          }}
        />
        <span style={{ fontSize: 10, color: connected ? T.green : T.red }}>
          {connected ? "WS:LIVE" : "WS:OFFLINE"}
        </span>
        {swarmActive && (
          <div
            className="swarm-active"
            style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "2px 8px", border: `1px solid ${T.amber}40`,
            }}
          >
            <Zap size={10} color={T.amber} />
            <span style={{ fontSize: 9, color: T.amber, letterSpacing: "0.1em" }}>
              AUTOBOOKING SWARM
            </span>
          </div>
        )}
      </div>
    );
  }

  // B2C variant
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{
        width: 6, height: 6, borderRadius: "50%",
        background: connected ? "#00C853" : "#EF4444",
      }} />
      <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono',monospace", color: "#6B7280" }}>
        {swarmActive ? "⚡ AUTOBOOKING SURGE" : "ML pricing live"}
      </span>
      <span style={{ fontSize: 11, fontFamily: "'JetBrains Mono',monospace", color: "#9CA3AF" }}>
        {eventCount.toLocaleString()} evt
      </span>
    </div>
  );
};
