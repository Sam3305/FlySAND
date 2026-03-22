import React from "react";
import { T } from "../../constants";
import { useNavStore, useAuthStore } from "../../store";
import { useClock } from "../../hooks";
import { WsStatusBadge } from "../shared/WsStatusBadge";
import type { LiveFlightState } from "../../types";

interface Props {
  live: LiveFlightState;
}

export const AOCCHeader: React.FC<Props> = ({ live }) => {
  const setView    = useNavStore((s) => s.setView);
  const logout     = useAuthStore((s) => s.logout);
  const operatorId = useAuthStore((s) => s.operatorId);
  const now        = useClock();

  const handleLogout = () => {
    logout();
    setView("b2c");
  };

  return (
    <div style={{
      background: "#040404",
      borderBottom: `1px solid ${T.border}`,
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 14px",
      height: 40,
      flexShrink: 0,
    }}>
      {/* ── Left cluster ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: T.green, letterSpacing: "0.08em" }}>
          ▶ AOCC
        </span>
        <span style={{ color: T.border }}>|</span>
        <span style={{ fontSize: 10, color: T.amber, letterSpacing: "0.1em" }}>INDIGO OPS 6E</span>
        <span style={{ color: T.border }}>|</span>

        <WsStatusBadge
          connected={live.connected}
          eventCount={live.eventCount}
          swarmActive={live.swarmActive}
          variant="b2b"
        />
      </div>

      {/* ── Right cluster ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ fontSize: 10, color: T.textDm }}>
          EVT:<span style={{ color: T.cyan }}> {live.eventCount.toLocaleString()}</span>
        </span>
        <span style={{ fontSize: 10, color: T.textDm }}>
          BATCH:<span style={{ color: live.swarmActive ? T.amber : T.green }}> {live.batchSize}</span>
        </span>
        <span style={{ fontSize: 10, color: T.textDm }}>
          THROTTLE:<span style={{ color: T.purple }}> 500ms</span>
        </span>
        <span style={{ color: T.border }}>|</span>
        <span style={{ fontSize: 11, color: T.textBt, fontVariantNumeric: "tabular-nums" }}>
          {now.toLocaleTimeString("en-IN", { hour12: false })} IST
        </span>
        <span style={{ color: T.border }}>|</span>
        <span style={{ fontSize: 9, color: T.textDm }}>
          OP: <span style={{ color: T.cyan }}>{operatorId}</span>
        </span>
        <button
          onClick={() => setView("b2c")}
          style={{
            fontSize: 9, color: T.textDm, background: "none",
            border: `1px solid ${T.borderBt}`, padding: "3px 8px",
            cursor: "pointer", fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          → B2C
        </button>
        <button
          onClick={handleLogout}
          style={{
            fontSize: 9, color: T.red, background: "none",
            border: `1px solid ${T.red}30`, padding: "3px 8px",
            cursor: "pointer", fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          LOGOUT
        </button>
      </div>
    </div>
  );
};
