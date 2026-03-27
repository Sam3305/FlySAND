import React, { useState } from "react";
import { User, Lock, BarChart3 } from "lucide-react";
import { useNavStore } from "../../store/navStore";
import { OPS_CREDENTIALS } from "../../constants";

export const OpsLogin: React.FC = () => {
  const [user,    setUser]    = useState("");
  const [pass,    setPass]    = useState("");
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);
  const setView = useNavStore((s) => s.setView);

  const handleLogin = async () => {
    setLoading(true);
    setError("");
    await new Promise((r) => setTimeout(r, 600));

    if (user === OPS_CREDENTIALS.user && pass === OPS_CREDENTIALS.pass) {
      setView("ops-flights");
    } else {
      setError("Invalid credentials.");
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "#F4F6FB",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      <div style={{
        background: "#fff",
        borderRadius: 20,
        padding: "44px 40px",
        width: 380,
        boxShadow: "0 20px 60px rgba(0,0,0,0.08)",
        border: "1px solid #EEF0F7",
      }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14,
            background: "#EEF2FF",
            display: "flex", alignItems: "center", justifyContent: "center",
            margin: "0 auto 14px",
          }}>
            <BarChart3 size={24} color="#0F3CC9" />
          </div>
          <h2 style={{ fontSize: 20, fontWeight: 800, color: "#1A1A2E", marginBottom: 4 }}>
            Ops Analytics
          </h2>
          <p style={{ fontSize: 13, color: "#6B7280" }}>
            Flight inventory & booking dashboard
          </p>
        </div>

        {/* Fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{
              fontSize: 11, fontWeight: 600, color: "#6B7280",
              letterSpacing: "0.06em", marginBottom: 6, display: "block",
            }}>USERNAME</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1.5px solid #E5E7EB", borderRadius: 10,
              padding: "11px 14px",
            }}>
              <User size={14} color="#9CA3AF" />
              <input
                value={user}
                onChange={(e) => setUser(e.target.value)}
                placeholder="ops"
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                style={{
                  border: "none", outline: "none", flex: 1,
                  fontSize: 14, color: "#1A1A2E", background: "transparent",
                  fontFamily: "Barlow, sans-serif",
                }}
              />
            </div>
          </div>

          <div>
            <label style={{
              fontSize: 11, fontWeight: 600, color: "#6B7280",
              letterSpacing: "0.06em", marginBottom: 6, display: "block",
            }}>PASSWORD</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1.5px solid #E5E7EB", borderRadius: 10,
              padding: "11px 14px",
            }}>
              <Lock size={14} color="#9CA3AF" />
              <input
                type="password"
                value={pass}
                onChange={(e) => setPass(e.target.value)}
                placeholder="••••••••"
                onKeyDown={(e) => e.key === "Enter" && handleLogin()}
                style={{
                  border: "none", outline: "none", flex: 1,
                  fontSize: 14, color: "#1A1A2E", background: "transparent",
                  fontFamily: "Barlow, sans-serif",
                }}
              />
            </div>
          </div>

          {error && (
            <div style={{
              background: "#FEF2F2", border: "1px solid #FECACA",
              borderRadius: 8, padding: "10px 14px",
              fontSize: 12, color: "#DC2626",
            }}>
              {error}
            </div>
          )}

          <button
            onClick={handleLogin}
            disabled={loading}
            style={{
              background: loading ? "#E5E7EB" : "#0F3CC9",
              color: loading ? "#9CA3AF" : "#fff",
              border: "none", borderRadius: 10,
              padding: "13px 0", fontSize: 14, fontWeight: 700,
              cursor: loading ? "not-allowed" : "pointer",
              width: "100%", marginTop: 4,
              transition: "background 0.2s",
            }}
          >
            {loading ? "Signing in…" : "Sign In →"}
          </button>

          <button
            onClick={() => setView("b2c")}
            style={{
              background: "none", border: "none",
              color: "#9CA3AF", fontSize: 12,
              cursor: "pointer", textAlign: "center",
            }}
          >
            ← Back to booking portal
          </button>
        </div>
      </div>
    </div>
  );
};
