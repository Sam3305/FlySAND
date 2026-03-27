import React, { useState } from "react";
import { User, Lock, BarChart3 } from "lucide-react";
import { useAuthStore, useNavStore } from "../../store";

export const AOCCLogin: React.FC = () => {
  const [userId,   setUserId]   = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  const login   = useAuthStore((s) => s.login);
  const setView = useNavStore((s) => s.setView);

  const handleAuth = async () => {
    setLoading(true);
    setError("");
    const ok = await login(userId, password);
    if (ok) {
      setView("aocc");
    } else {
      setError("Invalid credentials. Please try again.");
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #0F3CC9 0%, #1E40AF 40%, #3B82F6 100%)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
    }}>
      <div style={{
        background: "#fff",
        borderRadius: 20,
        padding: "44px 40px",
        width: 380,
        boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
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
            CFO Dashboard
          </h2>
          <p style={{ fontSize: 13, color: "#6B7280" }}>
            Executive intelligence & daily briefings
          </p>
        </div>

        {/* Fields */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={{
              fontSize: 11, fontWeight: 600, color: "#6B7280",
              letterSpacing: "0.06em", marginBottom: 6, display: "block",
            }}>OPERATOR ID</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1.5px solid #E5E7EB", borderRadius: 10,
              padding: "11px 14px",
            }}>
              <User size={14} color="#9CA3AF" />
              <input
                value={userId}
                onChange={(e) => setUserId(e.target.value.toUpperCase())}
                placeholder="AOCC_OPS"
                onKeyDown={(e) => e.key === "Enter" && handleAuth()}
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
            }}>PASSCODE</label>
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              border: "1.5px solid #E5E7EB", borderRadius: 10,
              padding: "11px 14px",
            }}>
              <Lock size={14} color="#9CA3AF" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                onKeyDown={(e) => e.key === "Enter" && handleAuth()}
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
            onClick={handleAuth}
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

          <div style={{ textAlign: "center", fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>
            Demo: AOCC_OPS / 6E_TERMINAL
          </div>

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
