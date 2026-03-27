import React, { useState } from "react";
import { User, Lock } from "lucide-react";
import { useAuthStore, useNavStore } from "../store";
import { AOCC_CREDENTIALS, OPS_CREDENTIALS } from "../constants";
import flysandLogo from "../assets/flysand_logo.png";

export const UnifiedLogin: React.FC = () => {
  const [user,    setUser]    = useState("");
  const [pass,    setPass]    = useState("");
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const login   = useAuthStore((s) => s.login);
  const setView = useNavStore((s) => s.setView);

  const handleLogin = async () => {
    setLoading(true);
    setError("");
    await new Promise((r) => setTimeout(r, 600));

    const upperUser = user.toUpperCase();

    // Route 1: OPS credentials → Ops Analytics
    if (user === OPS_CREDENTIALS.user && pass === OPS_CREDENTIALS.pass) {
      setView("ops-flights");
      return;
    }

    // Route 2: AOCC credentials → CFO Command Centre
    if (upperUser === AOCC_CREDENTIALS.user && pass === AOCC_CREDENTIALS.pass) {
      const ok = await login(upperUser, pass);
      if (ok) {
        setView("aocc");
        return;
      }
    }

    setError("Invalid credentials. Please try again.");
    setLoading(false);
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0A1628",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      {/* Subtle background grid */}
      <div style={{
        position: "absolute", inset: 0, opacity: 0.03,
        backgroundImage: "radial-gradient(circle at 1px 1px, #fff 1px, transparent 0)",
        backgroundSize: "40px 40px",
      }} />

      <div style={{
        background: "rgba(255,255,255,0.04)",
        backdropFilter: "blur(20px)",
        borderRadius: 24,
        padding: "48px 44px",
        width: 400,
        boxShadow: "0 25px 80px rgba(0,0,0,0.4)",
        border: "1px solid rgba(255,255,255,0.08)",
        position: "relative",
      }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <img
            src={flysandLogo}
            alt="FlySAND"
            style={{
              width: 56, height: 56, borderRadius: 16, objectFit: "cover",
              margin: "0 auto 16px", display: "block",
              boxShadow: "0 0 30px rgba(0,229,255,0.2)",
            }}
          />
          <h2 style={{ fontSize: 22, fontWeight: 800, color: "#F1F5F9", marginBottom: 4, letterSpacing: "-0.3px" }}>
            FlySAND
          </h2>
          <p style={{ fontSize: 12, color: "#64748B", lineHeight: 1.5 }}>
            Control Centre &amp; Operations Portal
          </p>
        </div>

        {/* Fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{
              fontSize: 10, fontWeight: 700, color: "#475569",
              letterSpacing: "0.1em", marginBottom: 6, display: "block",
            }}>USERNAME</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10,
              padding: "12px 14px", background: "rgba(255,255,255,0.03)",
              transition: "border-color 0.2s",
            }}>
              <User size={14} color="#475569" />
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder="Enter your username"
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                style={{
                  border: "none", outline: "none", flex: 1,
                  fontSize: 14, color: "#E2E8F0", background: "transparent",
                  fontFamily: "'Inter', system-ui, sans-serif",
                }}
              />
            </div>
          </div>

          <div>
            <label style={{
              fontSize: 10, fontWeight: 700, color: "#475569",
              letterSpacing: "0.1em", marginBottom: 6, display: "block",
            }}>PASSWORD</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1px solid rgba(255,255,255,0.1)", borderRadius: 10,
              padding: "12px 14px", background: "rgba(255,255,255,0.03)",
            }}>
              <Lock size={14} color="#475569" />
              <input
                type="password"
                value={pass}
                onChange={(e) => setPass(e.target.value)}
                placeholder="••••••••"
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                style={{
                  border: "none", outline: "none", flex: 1,
                  fontSize: 14, color: "#E2E8F0", background: "transparent",
                  fontFamily: "'Inter', system-ui, sans-serif",
                }}
              />
            </div>
          </div>

          {error && (
            <div style={{
              background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.2)",
              borderRadius: 8, padding: "10px 14px",
              fontSize: 12, color: "#F87171",
            }}>
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={loading}
            style={{
              background: loading ? "rgba(255,255,255,0.05)" : "linear-gradient(135deg, #059669, #10B981)",
              color: loading ? "#64748B" : "#fff",
              border: "none", borderRadius: 10,
              padding: "14px 0", fontSize: 14, fontWeight: 700,
              cursor: loading ? "not-allowed" : "pointer",
              width: "100%", marginTop: 4,
              boxShadow: loading ? "none" : "0 0 24px rgba(5,150,105,0.3)",
              transition: "all 0.2s",
              letterSpacing: "0.02em",
            }}
          >
            {loading ? "Authenticating…" : "Sign In →"}
          </button>

          <div style={{ textAlign: "center", fontSize: 10, color: "#475569", marginTop: 4, lineHeight: 1.6 }}>
            <span style={{ color: "#00E5FF" }}>OPS</span>: ops / ops@123 &nbsp;&nbsp;·&nbsp;&nbsp;
            <span style={{ color: "#F59E0B" }}>CFO</span>: AOCC_OPS / 6E_TERMINAL
          </div>

          <button
            onClick={() => setView("b2c")}
            style={{
              background: "none", border: "none",
              color: "#475569", fontSize: 12,
              cursor: "pointer", textAlign: "center",
              transition: "color 0.15s",
            }}
          >
            ← Back to booking portal
          </button>
        </div>
      </div>
    </div>
  );
};
