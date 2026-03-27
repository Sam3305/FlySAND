import React from "react";
import { useNavStore } from "../../store";
import flysandLogo from "../../assets/flysand_logo.png";

export const B2CNav: React.FC = () => {
  const setView = useNavStore((s) => s.setView);

  return (
    <nav style={{ background: "#0A1628", position: "sticky", top: 0, zIndex: 50 }}>
      <div style={{
        maxWidth: 1100, margin: "0 auto", padding: "0 20px",
        height: 56, display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        {/* Brand */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <img src={flysandLogo} alt="FlySAND" style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }} />
          <span style={{
            color: "#fff", fontWeight: 800, fontSize: 18,
            letterSpacing: "-0.2px", fontFamily: "system-ui, sans-serif",
          }}>
            FlySAND
          </span>
          <span style={{
            fontSize: 9, color: "#00E5FF", fontFamily: "monospace",
            background: "rgba(0,229,255,0.08)", padding: "2px 7px",
            borderRadius: 2, letterSpacing: "0.1em", marginLeft: 2,
          }}>
            AI OPERATED
          </span>
        </div>

        {/* Right side */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            onClick={() => setView("login")}
            style={{
              fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
              color: "rgba(255,255,255,0.6)",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.12)",
              padding: "6px 14px",
              cursor: "pointer", borderRadius: 4,
              letterSpacing: "0.06em",
            }}
          >
            CREW LOGIN
          </button>
        </div>
      </div>
    </nav>
  );
};
