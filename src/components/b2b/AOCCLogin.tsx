import React, { useState } from "react";
import { User, Lock } from "lucide-react";
import { useAuthStore, useNavStore } from "../../store";
import { T } from "../../constants";

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
      setError("AUTH_FAIL — INVALID CREDENTIALS");
      setLoading(false);
    }
  };

  const fieldStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8,
    border: `1px solid ${T.borderBt}`, background: "#050505", padding: "9px 12px",
  };

  const inputStyle: React.CSSProperties = {
    background: "transparent", border: "none", outline: "none",
    color: T.green, fontSize: 13, fontFamily: "'JetBrains Mono', monospace",
    letterSpacing: "0.02em", flex: 1,
  };

  return (
    <div className="b2b" style={{
      minHeight: "100vh", background: "#000",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div className="scanline" />
      <div style={{ width: 360, padding: 32, border: `1px solid ${T.green}30`, background: "#050505" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{ fontSize: 10, color: T.textDm, letterSpacing: "0.15em", marginBottom: 6 }}>
            INDIGO AIRLINES GROUP
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.green, letterSpacing: "0.05em", marginBottom: 4 }}>
            AOCC TERMINAL
          </div>
          <div style={{ fontSize: 9, color: T.textDm, letterSpacing: "0.12em" }}>
            AIRPORT OPERATIONS CONTROL CENTER
          </div>
          <div style={{
            marginTop: 12, display: "inline-flex", alignItems: "center", gap: 6,
            padding: "4px 10px", border: `1px solid ${T.amber}30`, background: `${T.amber}08`,
          }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: T.amber, animation: "pulse 2s ease-in-out infinite" }} />
            <span style={{ fontSize: 9, color: T.amber, letterSpacing: "0.1em" }}>
              SYSTEM ONLINE · CLEARANCE L3
            </span>
          </div>
        </div>

        {/* Form */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div>
            <div style={{ fontSize: 9, color: T.textDm, letterSpacing: "0.12em", marginBottom: 5 }}>OPERATOR ID</div>
            <div style={fieldStyle}>
              <User size={12} color={T.textDm} />
              <input
                value={userId}
                onChange={(e) => setUserId(e.target.value.toUpperCase())}
                placeholder="AOCC_OPS"
                style={inputStyle}
                onKeyDown={(e) => e.key === "Enter" && handleAuth()}
              />
            </div>
          </div>

          <div>
            <div style={{ fontSize: 9, color: T.textDm, letterSpacing: "0.12em", marginBottom: 5 }}>PASSCODE</div>
            <div style={fieldStyle}>
              <Lock size={12} color={T.textDm} />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="············"
                style={inputStyle}
                onKeyDown={(e) => e.key === "Enter" && handleAuth()}
              />
            </div>
          </div>

          {error && (
            <div style={{
              fontSize: 10, color: T.red,
              border: `1px solid ${T.red}30`, background: `${T.red}08`, padding: "8px 12px",
            }}>
              ⚠ {error}
            </div>
          )}

          <button
            onClick={handleAuth}
            disabled={loading}
            style={{
              background: loading ? T.borderBt : `${T.green}18`,
              color: loading ? T.textDm : T.green,
              border: `1px solid ${T.green}35`, padding: "11px",
              fontSize: 13, fontWeight: 700, cursor: "pointer",
              fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.05em",
            }}
          >
            {loading ? "AUTHENTICATING ···" : "AUTHENTICATE →"}
          </button>

          <div style={{ textAlign: "center", fontSize: 10, color: T.textDm }}>
            Demo: AOCC_OPS / 6E_TERMINAL
          </div>
        </div>
      </div>
    </div>
  );
};
