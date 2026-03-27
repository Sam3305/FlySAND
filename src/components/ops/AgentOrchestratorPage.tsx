import React, { useState, useEffect, useCallback } from "react";
import { useNavStore } from "../../store/navStore";
import {
  LogOut, ArrowLeft, Play, RefreshCw, FileText, Activity,
  Bot, TrendingUp, DollarSign, MapPin, Fuel, ChevronRight, Circle
} from "lucide-react";

interface AgentLog {
  filename: string;
  timestamp: number;
  content: string;
}

interface AgentStatus {
  status: string;
  last_run: string | null;
  last_result?: string | null;
}

interface AllStatus {
  [key: string]: AgentStatus;
}

const AGENTS = [
  { key: "yield",   label: "Yield Manager",      icon: TrendingUp, color: "#059669", bg: "#ECFDF5", desc: "Dynamic pricing & margin optimization" },
  { key: "cfo",     label: "CFO Narrator",        icon: DollarSign, color: "#D97706", bg: "#FEF3C7", desc: "Financial health & revenue analysis" },
  { key: "network", label: "Network Planner",     icon: MapPin,     color: "#4338CA", bg: "#EEF2FF", desc: "Route scheduling & aircraft right-sizing" },
  { key: "fuel",    label: "Fuel Procurement",    icon: Fuel,       color: "#DC2626", bg: "#FEF2F2", desc: "Tankering economics & ATF analysis" },
] as const;

const STATUS_COLORS: Record<string, { bg: string; color: string; label: string }> = {
  idle:         { bg: "#F3F4F6", color: "#6B7280", label: "IDLE" },
  initializing: { bg: "#FEF3C7", color: "#D97706", label: "STARTING" },
  online:       { bg: "#ECFDF5", color: "#059669", label: "ONLINE" },
  queried:      { bg: "#EEF2FF", color: "#4338CA", label: "QUERIED" },
  responded:    { bg: "#ECFDF5", color: "#059669", label: "RESPONDED" },
  running:      { bg: "#FEF3C7", color: "#D97706", label: "RUNNING" },
  completed:    { bg: "#ECFDF5", color: "#059669", label: "COMPLETED" },
  error:        { bg: "#FEF2F2", color: "#DC2626", label: "ERROR" },
};

export const AgentOrchestratorPage: React.FC = () => {
  const setView = useNavStore((s) => s.setView);
  const [agentStatus, setAgentStatus] = useState<AllStatus | null>(null);
  const [masterLogs, setMasterLogs] = useState<AgentLog[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentLogs, setAgentLogs] = useState<AgentLog[]>([]);
  const [selectedLog, setSelectedLog] = useState<AgentLog | null>(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);

  const API = "http://localhost:8000/api/v1/orchestrator";

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/status`);
      if (res.ok) {
        const data = await res.json();
        setAgentStatus(data);
        if (data.master?.status === "running") setRunning(true);
        else setRunning(false);
      }
    } catch {}
  }, []);

  const fetchMasterLogs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/logs`);
      if (res.ok) {
        const data = await res.json();
        setMasterLogs(data.logs || []);
      }
    } catch {}
    setLoading(false);
  }, []);

  const fetchAgentLogs = useCallback(async (agent: string) => {
    try {
      const res = await fetch(`${API}/logs/${agent}`);
      if (res.ok) {
        const data = await res.json();
        setAgentLogs(data.logs || []);
      }
    } catch {}
  }, []);

  useEffect(() => {
    fetchStatus();
    fetchMasterLogs();
    const inv = setInterval(() => { fetchStatus(); fetchMasterLogs(); }, 5000);
    return () => clearInterval(inv);
  }, [fetchStatus, fetchMasterLogs]);

  useEffect(() => {
    if (selectedAgent) fetchAgentLogs(selectedAgent);
  }, [selectedAgent, fetchAgentLogs]);

  const handleRunEnsemble = async () => {
    if (!window.confirm("Execute the Quad-Node Gemini Agent Ensemble?\nThis queries 5 LLMs and commits DB transactions.")) return;
    setRunning(true);
    try { await fetch(`${API}/run`, { method: "POST" }); } catch {}
  };

  const getStatus = (key: string) => {
    if (!agentStatus) return STATUS_COLORS["idle"];
    const s = agentStatus?.[key]?.status || "idle";
    return STATUS_COLORS[s] || STATUS_COLORS["idle"];
  };

  const getLastRun = (key: string) => {
    if (!agentStatus) return "Never";
    const lr = agentStatus?.[key]?.last_run;
    return lr ? new Date(lr).toLocaleString() : "Never";
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0B0F1A", display: "flex", flexDirection: "column", fontFamily: "'Inter', 'Segoe UI', sans-serif" }}>
      {/* ── Header ── */}
      <div style={{
        background: "linear-gradient(135deg, #0F172A 0%, #1E293B 100%)",
        padding: "0 28px", height: 64,
        display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0,
        borderBottom: "1px solid rgba(255,255,255,0.06)"
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button onClick={() => setView("ops-flights")} style={{
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)", color: "#94A3B8",
            display: "flex", alignItems: "center", justifyContent: "center",
            width: 34, height: 34, borderRadius: 8, cursor: "pointer", transition: "all 0.15s"
          }}>
            <ArrowLeft size={16} />
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              background: "linear-gradient(135deg, #F97316, #FB923C)",
              display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 20px rgba(249,115,22,0.3)"
            }}>
              <Bot size={20} color="#fff" />
            </div>
            <div>
              <div style={{ color: "#F1F5F9", fontWeight: 700, fontSize: 16, lineHeight: 1.2 }}>FlySAND Quad-Node</div>
              <div style={{ color: "#64748B", fontSize: 11, fontWeight: 500 }}>Master Orchestrator Terminal</div>
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={handleRunEnsemble} disabled={running} style={{
            display: "flex", alignItems: "center", gap: 8, border: "none",
            background: running ? "rgba(255,255,255,0.06)" : "linear-gradient(135deg, #059669, #10B981)",
            borderRadius: 8, padding: "9px 20px", fontWeight: 600,
            color: "#fff", fontSize: 13, cursor: running ? "default" : "pointer",
            boxShadow: running ? "none" : "0 0 20px rgba(5,150,105,0.3)", transition: "all 0.2s"
          }}>
            {running ? <RefreshCw size={14} className="spin-anim" /> : <Play size={14} fill="#fff" />}
            {running ? "Dispatching..." : "Execute Full Ensemble"}
          </button>
          <button onClick={() => setView("b2c")} style={{
            display: "flex", alignItems: "center", gap: 6,
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 8, padding: "9px 16px", fontWeight: 500,
            color: "#94A3B8", fontSize: 12, cursor: "pointer",
          }}>
            <LogOut size={13} /> Exit
          </button>
        </div>
      </div>

      {/* ── KPI Cards ── */}
      <div style={{ padding: "20px 28px 0", display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
        {AGENTS.map(({ key, label, icon: Icon, color, bg, desc }) => {
          const st = getStatus(key);
          const isSelected = selectedAgent === key;
          return (
            <button key={key} onClick={() => { setSelectedAgent(key === selectedAgent ? null : key); setSelectedLog(null); }}
              style={{
                background: isSelected ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.03)",
                border: isSelected ? `1px solid ${color}44` : "1px solid rgba(255,255,255,0.06)",
                borderRadius: 14, padding: "18px 20px", cursor: "pointer",
                textAlign: "left", transition: "all 0.2s", position: "relative", overflow: "hidden"
              }}
            >
              {/* Status dot */}
              <div style={{ position: "absolute", top: 14, right: 14, display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
                  padding: "3px 8px", borderRadius: 20,
                  background: st.bg, color: st.color
                }}>{st.label}</span>
              </div>

              <div style={{
                width: 38, height: 38, borderRadius: 10, marginBottom: 12,
                background: bg, display: "flex", alignItems: "center", justifyContent: "center"
              }}>
                <Icon size={18} color={color} />
              </div>

              <div style={{ fontSize: 14, fontWeight: 700, color: "#E2E8F0", marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 11, color: "#64748B", marginBottom: 10, lineHeight: 1.4 }}>{desc}</div>

              <div style={{ fontSize: 10, color: "#475569", display: "flex", alignItems: "center", gap: 4 }}>
                <Circle size={6} fill={st.color} color={st.color} />
                Last: {getLastRun(key)}
              </div>

              {isSelected && (
                <div style={{
                  position: "absolute", bottom: 0, left: 0, right: 0, height: 3,
                  background: `linear-gradient(90deg, ${color}, transparent)`
                }} />
              )}
            </button>
          );
        })}
      </div>

      {/* ── Main Body ── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", margin: "16px 28px 28px", gap: 14 }}>

        {/* Sidebar */}
        <div style={{
          width: 300, background: "rgba(255,255,255,0.02)", borderRadius: 14,
          border: "1px solid rgba(255,255,255,0.06)",
          display: "flex", flexDirection: "column", overflowY: "auto"
        }}>
          <div style={{
            padding: "14px 18px", borderBottom: "1px solid rgba(255,255,255,0.06)",
            display: "flex", justifyContent: "space-between", alignItems: "center"
          }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B", letterSpacing: "0.1em", textTransform: "uppercase" }}>
              {selectedAgent ? `${selectedAgent.toUpperCase()} Logs` : "Master Logs"}
            </span>
            <button onClick={() => selectedAgent ? fetchAgentLogs(selectedAgent) : fetchMasterLogs()}
              style={{ background: "none", border: "none", cursor: "pointer", color: "#475569" }}>
              <RefreshCw size={13} className={loading ? "spin-anim" : ""} />
            </button>
          </div>

          <div style={{ padding: "10px", display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
            {(selectedAgent ? agentLogs : masterLogs).length === 0 && (
              <div style={{ textAlign: "center", padding: "40px 16px", color: "#475569", fontSize: 12 }}>
                <Activity size={22} style={{ margin: "0 auto 10px", opacity: 0.3 }} />
                No logs found yet.
              </div>
            )}

            {(selectedAgent ? agentLogs : masterLogs).map(log => {
              const isSel = selectedLog?.filename === log.filename;
              return (
                <button key={log.filename} onClick={() => setSelectedLog(log)} style={{
                  display: "flex", alignItems: "center", gap: 10, width: "100%",
                  background: isSel ? "rgba(99,102,241,0.1)" : "transparent",
                  border: isSel ? "1px solid rgba(99,102,241,0.2)" : "1px solid transparent",
                  borderRadius: 8, padding: "10px 12px", cursor: "pointer",
                  textAlign: "left", transition: "all 0.1s"
                }}>
                  <FileText size={14} color={isSel ? "#818CF8" : "#475569"} style={{ flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: isSel ? "#C7D2FE" : "#CBD5E1", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {log.filename.replace(/_/g, " ").replace(".md", "")}
                    </div>
                    <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>
                      {new Date(log.timestamp * 1000).toLocaleString()}
                    </div>
                  </div>
                  <ChevronRight size={12} color="#475569" />
                </button>
              );
            })}
          </div>
        </div>

        {/* Content Panel */}
        <div style={{
          flex: 1, background: "rgba(255,255,255,0.02)", borderRadius: 14,
          border: "1px solid rgba(255,255,255,0.06)", overflowY: "auto"
        }}>
          {selectedLog ? (
            <>
              <div style={{
                padding: "16px 22px", borderBottom: "1px solid rgba(255,255,255,0.06)",
                display: "flex", justifyContent: "space-between", alignItems: "center", background: "rgba(255,255,255,0.02)"
              }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#E2E8F0" }}>
                    {selectedLog.filename.replace(/_/g, " ").replace(".md", "")}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748B", marginTop: 2 }}>
                    {new Date(selectedLog.timestamp * 1000).toLocaleString()}
                  </div>
                </div>
                <div style={{ background: "rgba(16,185,129,0.15)", color: "#34D399", fontSize: 10, fontWeight: 700, padding: "4px 10px", borderRadius: 20, letterSpacing: "0.05em" }}>
                  COMPLETED
                </div>
              </div>
              <div style={{ padding: "22px 24px" }}>
                <pre style={{
                  margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word",
                  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
                  fontSize: 12.5, lineHeight: 1.7, color: "#CBD5E1"
                }}>
                  {selectedLog.content}
                </pre>
              </div>
            </>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", color: "#475569" }}>
              <Bot size={44} style={{ opacity: 0.15, marginBottom: 14 }} />
              <div style={{ fontSize: 14, fontWeight: 600, color: "#64748B" }}>
                {selectedAgent ? `Select a ${selectedAgent} log to inspect` : "System Ready for Orchestration"}
              </div>
              <div style={{ fontSize: 12, maxWidth: 320, textAlign: "center", marginTop: 6, color: "#475569", lineHeight: 1.5 }}>
                Click an agent card above to filter its logs, or select a log entry from the sidebar.
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .spin-anim { animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.15); }
        button:hover { opacity: 0.95; }
      `}</style>
    </div>
  );
};
