import React, { useState, useEffect, useCallback } from "react";
import {
  LogOut, RefreshCw, TrendingUp,
  ArrowUpDown, AlertCircle, Loader, ChevronLeft, ChevronRight,
} from "lucide-react";
import { useNavStore } from "../../store/navStore";
import { AIRPORTS }   from "../../constants";
import { formatINR }  from "../../utils";
import type { AirportCode } from "../../types";
import flysandLogo from "../../assets/flysand_logo.png";

// ─── Types ────────────────────────────────────────────────────────────────────

interface FlightRow {
  flight_id:      string;
  route:          string;
  origin:         AirportCode;
  destination:    AirportCode;
  departure_date: string;
  departure_time: string;
  slot:           string;
  status:         string;
  aircraft_icao:  string;
  capacity:       number;
  sold:           number;
  available:      number;
  load_pct:       number;
  floor_inr:      number;
  ml_fare_inr:    number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const STATUS_STYLE: Record<string, { bg: string; color: string }> = {
  scheduled: { bg: "#EEF2FF", color: "#4338CA" },
  boarding:  { bg: "#FEF3C7", color: "#D97706" },
  airborne:  { bg: "#ECFDF5", color: "#059669" },
  landed:    { bg: "#F3F4F6", color: "#6B7280" },
  cancelled: { bg: "#FEF2F2", color: "#DC2626" },
};

function loadColor(pct: number): string {
  if (pct >= 90) return "#DC2626";
  if (pct >= 70) return "#D97706";
  return "#059669";
}

function mapDoc(doc: Record<string, unknown>): FlightRow {
  const inv     = (doc.inventory        as Record<string, number>) ?? {};
  const pricing = (doc.current_pricing  as Record<string, number>) ?? {};
  const physics = (doc.physics_snapshot as Record<string, unknown>) ?? {};
  const capacity  = inv.capacity  ?? 0;
  const sold      = inv.sold      ?? 0;
  const available = inv.available ?? 0;
  const load_pct  = capacity > 0 ? Math.round((sold / capacity) * 100) : 0;

  return {
    flight_id:      String(doc.flight_id ?? ""),
    route:          String(doc.route ?? ""),
    origin:         String(doc.origin ?? "")      as AirportCode,
    destination:    String(doc.destination ?? "") as AirportCode,
    departure_date: String(doc.departure_date ?? ""),
    departure_time: String(doc.departure_time ?? ""),
    slot:           String(doc.slot ?? ""),
    status:         String(doc.status ?? "scheduled"),
    aircraft_icao:  String(physics.aircraft_icao ?? "—"),
    capacity,
    sold,
    available,
    load_pct,
    floor_inr:   pricing.floor_inr   ?? 0,
    ml_fare_inr: pricing.ml_fare_inr ?? 0,
  };
}

// ─── Main page ────────────────────────────────────────────────────────────────

type SortKey = "departure_date" | "route" | "load_pct" | "available" | "ml_fare_inr";

export const OpsFlightsPage: React.FC = () => {
  const setView = useNavStore((s) => s.setView);

  const [rows,      setRows]      = useState<FlightRow[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState("");
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  // Filters
  const [filterOrigin, setFilterOrigin] = useState("ALL");
  const [filterDest,   setFilterDest]   = useState("ALL");
  const [filterStatus, setFilterStatus] = useState("ALL");

  // Sort
  const [sortKey,  setSortKey]  = useState<SortKey>("departure_date");
  const [sortAsc,  setSortAsc]  = useState(true);

  // Pagination
  const [perPage, setPerPage] = useState(25);
  const [page,    setPage]    = useState(1);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res  = await fetch("http://localhost:8000/api/v1/flights");
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const docs: Record<string, unknown>[] = await res.json();
      setRows(docs.map(mapDoc));
      setLastFetch(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch flights.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // ── Derived data ────────────────────────────────────────────────────────────
  const airports = ["ALL", "DEL", "BOM", "CCU", "MAA"];
  const statuses = ["ALL", "scheduled", "boarding", "airborne", "landed", "cancelled"];

  const filtered = rows
    .filter((r) => filterOrigin === "ALL" || r.origin      === filterOrigin)
    .filter((r) => filterDest   === "ALL" || r.destination === filterDest)
    .filter((r) => filterStatus === "ALL" || r.status      === filterStatus)
    .sort((a, b) => {
      let va: string | number = a[sortKey];
      let vb: string | number = b[sortKey];
      if (sortKey === "departure_date") {
        va = `${a.departure_date}_${a.departure_time}`;
        vb = `${b.departure_date}_${b.departure_time}`;
      }
      if (va < vb) return sortAsc ? -1 :  1;
      if (va > vb) return sortAsc ?  1 : -1;
      return 0;
    });

  const totalSold      = rows.reduce((s, r) => s + r.sold,     0);
  const totalCapacity  = rows.reduce((s, r) => s + r.capacity, 0);
  const avgLoad        = totalCapacity > 0
    ? Math.round((totalSold / totalCapacity) * 100) : 0;
  const fullFlights    = rows.filter((r) => r.available === 0).length;

  const handleSort = (key: SortKey) => {
    if (key === sortKey) setSortAsc((a) => !a);
    else { setSortKey(key); setSortAsc(true); }
  };

  const SortIcon: React.FC<{ k: SortKey }> = ({ k }) => (
    <ArrowUpDown
      size={11}
      color={sortKey === k ? "#0F3CC9" : "#D1D5DB"}
      style={{ marginLeft: 4, flexShrink: 0 }}
    />
  );

  const selectStyle: React.CSSProperties = {
    border: "1.5px solid #E5E7EB", borderRadius: 8,
    padding: "7px 10px", fontSize: 12, color: "#1A1A2E",
    background: "#fff", outline: "none", fontFamily: "Barlow, sans-serif",
  };

  const thStyle: React.CSSProperties = {
    padding: "10px 14px", textAlign: "left",
    fontSize: 10, fontWeight: 700, color: "#6B7280",
    letterSpacing: "0.07em", borderBottom: "2px solid #EEF0F7",
    whiteSpace: "nowrap", userSelect: "none",
  };

  const tdStyle: React.CSSProperties = {
    padding: "11px 14px", fontSize: 13, color: "#1A1A2E",
    borderBottom: "1px solid #F3F4F6", whiteSpace: "nowrap",
  };

  return (
    <div style={{ minHeight: "100vh", background: "#F4F6FB" }}>

      {/* ── Header ── */}
      <div style={{
        background: "#0A1628",
        padding: "0 24px", height: 56,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <img src={flysandLogo} alt="FlySAND" style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }} />
          <span style={{ color: "#fff", fontWeight: 800, fontSize: 18 }}>FlySAND</span>
          <span style={{
            fontSize: 9, color: "#00E5FF", fontFamily: "monospace",
            background: "rgba(0,229,255,0.08)", padding: "2px 7px",
            borderRadius: 2, letterSpacing: "0.1em", marginLeft: 2,
          }}>
            OPS ANALYTICS
          </span>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={() => setView("ops-agents")}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              background: "rgba(0,229,255,0.1)", border: "1px solid rgba(0,229,255,0.2)",
              borderRadius: 6, padding: "6px 14px", fontWeight: 600,
              color: "#00E5FF", fontSize: 12, cursor: "pointer",
              letterSpacing: "0.03em",
            }}
          >
            AI Ensemble
          </button>
          <button
            onClick={() => setView("b2c")}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 6, padding: "6px 12px",
              color: "rgba(255,255,255,0.6)", fontSize: 11, cursor: "pointer",
              letterSpacing: "0.06em",
            }}
          >
            <LogOut size={12} /> EXIT
          </button>
        </div>
      </div>

      <div style={{ maxWidth: 1300, margin: "0 auto", padding: "24px 20px 60px" }}>

        {/* ── Summary cards ── */}
        <div style={{ display: "flex", gap: 14, marginBottom: 24, flexWrap: "wrap" }}>
          {[
            { label: "Total flights",      value: rows.length.toLocaleString(),        sub: "across all routes & dates" },
            { label: "Total seats sold",   value: totalSold.toLocaleString(),           sub: `of ${totalCapacity.toLocaleString()} capacity` },
            { label: "System load factor", value: `${avgLoad}%`,                        sub: "seats sold / total capacity", accent: loadColor(avgLoad) },
            { label: "Full flights",       value: fullFlights.toLocaleString(),         sub: "0 seats remaining" },
          ].map(({ label, value, sub, accent }) => (
            <div key={label} style={{
              flex: "1 1 180px",
              background: "#fff", borderRadius: 14,
              border: "1px solid #EEF0F7", padding: "16px 20px",
            }}>
              <div style={{ fontSize: 11, color: "#6B7280", marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: accent ?? "#0F3CC9" }}>{value}</div>
              <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 2 }}>{sub}</div>
            </div>
          ))}
        </div>

        {/* ── Table card ── */}
        <div style={{
          background: "#fff", borderRadius: 16,
          border: "1px solid #EEF0F7",
          boxShadow: "0 1px 4px rgba(0,0,0,0.04)",
        }}>

          {/* Table toolbar */}
          <div style={{
            padding: "16px 20px",
            display: "flex", alignItems: "center",
            justifyContent: "space-between", flexWrap: "wrap", gap: 12,
            borderBottom: "1px solid #EEF0F7",
          }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: "#1A1A2E", marginBottom: 2 }}>
                Live Flight Inventory
              </h2>
              <p style={{ fontSize: 12, color: "#6B7280" }}>
                {filtered.length} flight{filtered.length !== 1 ? "s" : ""} shown
                {lastFetch && ` · last updated ${lastFetch.toLocaleTimeString()}`}
              </p>
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {/* Filters */}
              <select value={filterOrigin} onChange={(e) => setFilterOrigin(e.target.value)} style={selectStyle}>
                {airports.map((a) => (
                  <option key={a} value={a}>{a === "ALL" ? "All origins" : `From ${a} — ${AIRPORTS[a as AirportCode]?.city ?? ""}`}</option>
                ))}
              </select>
              <select value={filterDest} onChange={(e) => setFilterDest(e.target.value)} style={selectStyle}>
                {airports.map((a) => (
                  <option key={a} value={a}>{a === "ALL" ? "All destinations" : `To ${a} — ${AIRPORTS[a as AirportCode]?.city ?? ""}`}</option>
                ))}
              </select>
              <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} style={selectStyle}>
                {statuses.map((s) => (
                  <option key={s} value={s}>{s === "ALL" ? "All statuses" : s.charAt(0).toUpperCase() + s.slice(1)}</option>
                ))}
              </select>
              <button
                onClick={fetchAll}
                disabled={loading}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  background: "#EEF2FF", border: "none", borderRadius: 8,
                  padding: "7px 14px", fontSize: 12, fontWeight: 600,
                  color: "#0F3CC9", cursor: "pointer",
                }}
              >
                <RefreshCw size={12} style={{ animation: loading ? "spin 1s linear infinite" : "none" }} />
                Refresh
              </button>
            </div>
          </div>

          {/* ── Pagination ── */}
          {!loading && !error && filtered.length > 0 && (
            <div style={{
              padding: "10px 20px", borderBottom: "1px solid #EEF0F7",
              display: "flex", justifyContent: "space-between", alignItems: "center",
              background: "#FAFBFC",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 12, color: "#6B7280" }}>Show</span>
                <select
                  value={perPage}
                  onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1); }}
                  style={{
                    border: "1.5px solid #E5E7EB", borderRadius: 6,
                    padding: "5px 8px", fontSize: 12, color: "#1A1A2E",
                    background: "#fff", outline: "none", fontFamily: "Barlow, sans-serif",
                  }}
                >
                  {[10, 25, 50, 100, 250].map(n => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
                <span style={{ fontSize: 12, color: "#6B7280" }}>per page</span>
              </div>

              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 12, color: "#6B7280", marginRight: 8 }}>
                  {Math.min((page - 1) * perPage + 1, filtered.length)}–{Math.min(page * perPage, filtered.length)} of {filtered.length}
                </span>
                <button
                  disabled={page <= 1}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    width: 30, height: 30, borderRadius: 6,
                    background: page <= 1 ? "#F3F4F6" : "#EEF2FF",
                    border: "none", cursor: page <= 1 ? "default" : "pointer",
                    color: page <= 1 ? "#D1D5DB" : "#0F3CC9",
                  }}
                >
                  <ChevronLeft size={14} />
                </button>
                <button
                  disabled={page * perPage >= filtered.length}
                  onClick={() => setPage(p => p + 1)}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    width: 30, height: 30, borderRadius: 6,
                    background: page * perPage >= filtered.length ? "#F3F4F6" : "#EEF2FF",
                    border: "none", cursor: page * perPage >= filtered.length ? "default" : "pointer",
                    color: page * perPage >= filtered.length ? "#D1D5DB" : "#0F3CC9",
                  }}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div style={{ textAlign: "center", padding: 60, color: "#6B7280" }}>
              <Loader size={28} style={{ opacity: 0.4, marginBottom: 10, animation: "spin 1s linear infinite" }} />
              <p style={{ fontSize: 14 }}>Loading flights…</p>
            </div>
          )}

          {/* Error */}
          {!loading && error && (
            <div style={{
              margin: 20, display: "flex", gap: 10, alignItems: "center",
              background: "#FEF2F2", border: "1px solid #FECACA",
              borderRadius: 10, padding: "14px 18px",
              fontSize: 13, color: "#DC2626",
            }}>
              <AlertCircle size={16} />
              {error}
            </div>
          )}

          {/* Table */}
          {!loading && !error && (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ background: "#FAFAFA" }}>
                    <th style={thStyle}>FLIGHT</th>
                    <th
                      style={{ ...thStyle, cursor: "pointer" }}
                      onClick={() => handleSort("route")}
                    >
                      <span style={{ display: "flex", alignItems: "center" }}>
                        ROUTE <SortIcon k="route" />
                      </span>
                    </th>
                    <th
                      style={{ ...thStyle, cursor: "pointer" }}
                      onClick={() => handleSort("departure_date")}
                    >
                      <span style={{ display: "flex", alignItems: "center" }}>
                        DATE & TIME <SortIcon k="departure_date" />
                      </span>
                    </th>
                    <th style={thStyle}>AIRCRAFT</th>
                    <th style={thStyle}>STATUS</th>
                    <th
                      style={{ ...thStyle, cursor: "pointer" }}
                      onClick={() => handleSort("available")}
                    >
                      <span style={{ display: "flex", alignItems: "center" }}>
                        SEATS LEFT <SortIcon k="available" />
                      </span>
                    </th>
                    <th
                      style={{ ...thStyle, cursor: "pointer" }}
                      onClick={() => handleSort("load_pct")}
                    >
                      <span style={{ display: "flex", alignItems: "center" }}>
                        LOAD <SortIcon k="load_pct" />
                      </span>
                    </th>
                    <th
                      style={{ ...thStyle, cursor: "pointer" }}
                      onClick={() => handleSort("ml_fare_inr")}
                    >
                      <span style={{ display: "flex", alignItems: "center" }}>
                        LIVE FARE <SortIcon k="ml_fare_inr" />
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ ...tdStyle, textAlign: "center", padding: 48, color: "#9CA3AF" }}>
                        No flights match the current filters.
                      </td>
                    </tr>
                  )}
                  {filtered.slice((page - 1) * perPage, page * perPage).map((r) => {
                    const st = STATUS_STYLE[r.status] ?? STATUS_STYLE["scheduled"];
                    return (
                      <tr
                        key={r.flight_id}
                        style={{ transition: "background 0.1s" }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#F9FAFB")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                      >
                        {/* Flight ID */}
                        <td style={tdStyle}>
                          <span style={{
                            fontFamily: "'JetBrains Mono', monospace",
                            fontSize: 12, fontWeight: 600, color: "#0F3CC9",
                          }}>
                            {r.flight_id.split("_")[0]}
                          </span>
                          <span style={{ fontSize: 10, color: "#9CA3AF", marginLeft: 6 }}>
                            {r.slot === "A" ? "AM" : r.slot === "B" ? "PM" : "EVE"}
                          </span>
                        </td>

                        {/* Route */}
                        <td style={tdStyle}>
                          <div style={{ fontWeight: 700, fontSize: 13 }}>
                            {r.origin} → {r.destination}
                          </div>
                          <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 1 }}>
                            {AIRPORTS[r.origin]?.city} → {AIRPORTS[r.destination]?.city}
                          </div>
                        </td>

                        {/* Date & Time */}
                        <td style={tdStyle}>
                          <div style={{ fontWeight: 600 }}>{r.departure_date}</div>
                          <div style={{ fontSize: 11, color: "#9CA3AF", marginTop: 1 }}>
                            {r.departure_time} IST
                          </div>
                        </td>

                        {/* Aircraft */}
                        <td style={{ ...tdStyle, fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>
                          {r.aircraft_icao}
                        </td>

                        {/* Status */}
                        <td style={tdStyle}>
                          <span style={{
                            padding: "3px 10px", borderRadius: 20,
                            fontSize: 11, fontWeight: 600,
                            background: st.bg, color: st.color,
                          }}>
                            {r.status.charAt(0).toUpperCase() + r.status.slice(1)}
                          </span>
                        </td>

                        {/* Seats left */}
                        <td style={tdStyle}>
                          <span style={{
                            fontWeight: 700, fontSize: 14,
                            color: r.available === 0 ? "#DC2626"
                                 : r.available <= 10 ? "#D97706"
                                 : "#059669",
                          }}>
                            {r.available === 0 ? "FULL" : r.available}
                          </span>
                          <span style={{ fontSize: 11, color: "#9CA3AF", marginLeft: 4 }}>
                            / {r.capacity}
                          </span>
                        </td>

                        {/* Load bar */}
                        <td style={tdStyle}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{
                              width: 64, height: 5, background: "#F3F4F6",
                              borderRadius: 3, overflow: "hidden",
                            }}>
                              <div style={{
                                height: "100%",
                                width: `${r.load_pct}%`,
                                background: loadColor(r.load_pct),
                                borderRadius: 3,
                                transition: "width 0.4s ease",
                              }} />
                            </div>
                            <span style={{
                              fontSize: 12, fontWeight: 600,
                              color: loadColor(r.load_pct),
                            }}>
                              {r.load_pct}%
                            </span>
                          </div>
                        </td>

                        {/* Live fare */}
                        <td style={tdStyle}>
                          <div style={{ fontWeight: 700, fontSize: 14, color: "#1A1A2E" }}>
                            ₹{formatINR(r.ml_fare_inr)}
                          </div>
                          <div style={{ fontSize: 10, color: "#9CA3AF", marginTop: 1 }}>
                            floor ₹{formatINR(r.floor_inr)}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

        </div>

        {/* Profit margin indicator */}
        {!loading && rows.length > 0 && (
          <div style={{
            marginTop: 16, display: "flex", alignItems: "center", gap: 8,
            fontSize: 12, color: "#6B7280",
          }}>
            <TrendingUp size={13} color="#059669" />
            All fares shown include physics-derived cost floor and early-bird discount.
            Floor = break-even + taxes. Fare ≥ floor enforced by Cardinal Rule.
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
};
