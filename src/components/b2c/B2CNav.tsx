import React from "react";
import { Plane, BarChart3 } from "lucide-react";
import { useNavStore } from "../../store";

export const B2CNav: React.FC = () => {
  const setView = useNavStore((s) => s.setView);

  return (
    <nav style={{ background: "#0F3CC9", position: "sticky", top: 0, zIndex: 50 }}>
      <div style={{
        maxWidth: 1100, margin: "0 auto", padding: "0 20px",
        height: 56, display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 32, height: 32, borderRadius: "50%",
              background: "#FF6B00", display: "flex", alignItems: "center", justifyContent: "center",
            }}>
              <Plane size={15} color="#fff" />
            </div>
            <span style={{ color: "#fff", fontWeight: 800, fontSize: 20, letterSpacing: "-0.3px" }}>
              IndiGo
            </span>
          </div>
          {["Book", "Manage", "Check-In", "Offers"].map((t) => (
            <button key={t} style={{
              color: "rgba(255,255,255,0.7)", background: "none", border: "none",
              cursor: "pointer", fontSize: 14, fontWeight: 500, fontFamily: "Barlow, sans-serif",
            }}>
              {t}
            </button>
          ))}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {/* Ops Analytics link */}
          <button
            onClick={() => setView("ops-login")}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 12, fontFamily: "Barlow, sans-serif",
              color: "rgba(255,255,255,0.8)",
              background: "rgba(255,255,255,0.10)",
              border: "1px solid rgba(255,255,255,0.18)",
              padding: "6px 13px", cursor: "pointer", borderRadius: 6,
            }}
          >
            <BarChart3 size={13} /> Ops
          </button>

          {/* AOCC terminal link */}
          <button
            onClick={() => setView("login")}
            style={{
              fontSize: 11, fontFamily: "'JetBrains Mono', monospace",
              color: "rgba(255,255,255,0.7)", background: "rgba(255,255,255,0.08)",
              border: "1px solid rgba(255,255,255,0.2)", padding: "6px 12px",
              cursor: "pointer", borderRadius: 4,
            }}
          >
            → AOCC TERMINAL
          </button>
        </div>
      </div>
    </nav>
  );
};
