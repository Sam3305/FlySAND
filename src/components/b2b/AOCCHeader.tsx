import React from "react";
import { useNavStore, useAuthStore } from "../../store";
import { LogOut } from "lucide-react";
import flysandLogo from "../../assets/flysand_logo.png";

export const AOCCHeader: React.FC = () => {
  const setView    = useNavStore((s) => s.setView);
  const logout     = useAuthStore((s) => s.logout);
  const operatorId = useAuthStore((s) => s.operatorId);

  return (
    <div style={{
      background: "linear-gradient(135deg, #0F3CC9 0%, #1E40AF 50%, #0B2A8A 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "0 24px",
      height: 54,
      flexShrink: 0,
    }}>
      {/* Left */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <img src={flysandLogo} alt="FlySAND" style={{ width: 32, height: 32, borderRadius: 8, objectFit: "cover" }} />
        <span style={{ fontSize: 15, fontWeight: 800, color: "#fff", letterSpacing: "0.04em" }}>
          FlySAND
        </span>
        <span style={{
          fontSize: 9, fontWeight: 700, color: "#fff",
          background: "rgba(255,255,255,0.15)",
          padding: "3px 8px", borderRadius: 4,
          letterSpacing: "0.08em",
        }}>
          CFO DASHBOARD
        </span>
      </div>

      {/* Right */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        {operatorId && (
          <span style={{ fontSize: 12, color: "rgba(255,255,255,0.7)" }}>
            {operatorId}
          </span>
        )}
        <button
          onClick={() => setView("b2c")}
          style={{
            fontSize: 11, color: "rgba(255,255,255,0.8)",
            background: "rgba(255,255,255,0.1)",
            border: "1px solid rgba(255,255,255,0.2)",
            padding: "6px 14px", borderRadius: 6,
            cursor: "pointer", fontFamily: "inherit",
          }}
        >
          B2C PORTAL
        </button>
        <button
          onClick={() => setView("ops-login")}
          style={{
            fontSize: 11, color: "rgba(255,255,255,0.8)",
            background: "rgba(255,255,255,0.1)",
            border: "1px solid rgba(255,255,255,0.2)",
            padding: "6px 14px", borderRadius: 6,
            cursor: "pointer", fontFamily: "inherit",
          }}
        >
          OPS PORTAL
        </button>
        <button
          onClick={() => { logout(); setView("b2c"); }}
          style={{
            fontSize: 11, color: "#FCA5A5",
            background: "rgba(239,68,68,0.15)",
            border: "1px solid rgba(239,68,68,0.3)",
            padding: "6px 12px", borderRadius: 6,
            cursor: "pointer", fontFamily: "inherit",
            display: "flex", alignItems: "center", gap: 4,
          }}
        >
          <LogOut size={12} /> LOGOUT
        </button>
      </div>
    </div>
  );
};
