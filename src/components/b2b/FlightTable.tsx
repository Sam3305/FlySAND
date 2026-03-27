import React, { useEffect, useState, useRef } from "react";
import { T, API_BASE, AIRPORTS } from "../../constants";
import type { LiveFlight } from "../../types";

const POLL_MS = 15_000; // refresh every 15s

const lf_color = (lf: number) =>
  lf >= 85 ? T.red : lf >= 60 ? T.amber : lf >= 30 ? T.green : T.textDm;

export const FlightTable: React.FC = () => {
  const [flights, setFlights]   = useState<LiveFlight[]>([]);
  const [loading, setLoading]   = useState(true);
  const [filter,  setFilter]    = useState<string>("all");
  const [changed, setChanged]   = useState<Set<string>>(new Set());
  const prevFares = useRef<Record<string, number>>({});

  const fetchFlights = async () => {
    try {
      const res  = await fetch(`${API_BASE}/api/v1/flights`);
      const data: LiveFlight[] = await res.json();

      // Detect fare changes for flash highlight
      const newChanged = new Set<string>();
      data.forEach((f) => {
        const prev = prevFares.current[f.flight_id];
        const curr = f.current_pricing?.ml_fare_inr;
        if (prev !== undefined && prev !== curr) newChanged.add(f.flight_id);
        if (curr) prevFares.current[f.flight_id] = curr;
      });

      setFlights(data);
      if (newChanged.size > 0) {
        setChanged(newChanged);
        setTimeout(() => setChanged(new Set()), 1200);
      }
    } catch {
      // backend not ready
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFlights();
    const t = setInterval(fetchFlights, POLL_MS);
    return () => clearInterval(t);
  }, []);

  const routes = [...new Set(flights.map((f) => `${f.origin}-${f.destination}`))].sort();
  const shown  = filter === "all" ? flights : flights.filter((f) => `${f.origin}-${f.destination}` === filter);

  return (
    <div style={{
      border: `1px solid ${T.border}`,
      background: T.panel,
      display: "flex",
      flexDirection: "column",
      height: "100%",
    }}>
      {/* Header */}
      <div style={{
        padding: "7px 12px",
        borderBottom: `1px solid ${T.border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexShrink: 0,
      }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: T.green, letterSpacing: "0.08em" }}>
          ▌ LIVE INVENTORY
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 9, color: T.textDm }}>
            {shown.length} flights
          </span>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{
              fontSize: 9, background: T.bg, color: T.text,
              border: `1px solid ${T.border}`, padding: "2px 6px",
              fontFamily: "inherit", cursor: "pointer",
            }}
          >
            <option value="all">All routes</option>
            {routes.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
      </div>

      {/* Table */}
      <div style={{ overflowY: "auto", flex: 1 }}>
        {loading ? (
          <div style={{ padding: 16, fontSize: 9, color: T.textDm }}>
            Loading flights from MongoDB…
          </div>
        ) : (
          <table style={{ width: "100%", fontSize: 9, borderCollapse: "collapse" }}>
            <thead style={{ position: "sticky", top: 0, background: T.panel, zIndex: 1 }}>
              <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                {["FLIGHT", "ROUTE", "DATE", "SLOT", "SOLD/CAP", "LF%", "FLOOR ₹", "FARE ₹"].map((h) => (
                  <th key={h} style={{
                    padding: "5px 10px", fontWeight: 400,
                    color: T.textDm, textAlign: "left", whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((f) => {
                const inv   = f.inventory   || { capacity: 0, sold: 0, available: 0 };
                const cp    = f.current_pricing || { floor_inr: 0, ml_fare_inr: 0 };
                const lf    = inv.capacity ? Math.round(inv.sold / inv.capacity * 100) : 0;
                const flash = changed.has(f.flight_id);
                const city  = (code: string) => (AIRPORTS as any)[code]?.city || code;

                return (
                  <tr
                    key={f.flight_id}
                    style={{
                      borderBottom: `1px solid ${T.border}`,
                      background: flash ? `${T.amber}08` : "transparent",
                      transition: "background 0.4s ease",
                    }}
                  >
                    <td style={{ padding: "5px 10px", color: T.cyan, fontVariantNumeric: "tabular-nums" }}>
                      {f.flight_id.split("_")[0]}
                    </td>
                    <td style={{ padding: "5px 10px", color: T.textBt, fontWeight: 600 }}>
                      {city(f.origin)} → {city(f.destination)}
                    </td>
                    <td style={{ padding: "5px 10px", color: T.text, fontVariantNumeric: "tabular-nums" }}>
                      {typeof f.departure_date === "string" ? f.departure_date.slice(0, 10) : String(f.departure_date).slice(0, 10)}
                    </td>
                    <td style={{ padding: "5px 10px", color: T.textDm }}>
                      {f.slot === "A" ? "06:00" : f.slot === "B" ? "12:30" : "18:00"}
                    </td>
                    <td style={{ padding: "5px 10px", color: T.text, fontVariantNumeric: "tabular-nums" }}>
                      {inv.sold}/{inv.capacity}
                    </td>
                    <td style={{ padding: "5px 10px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                        <div style={{ width: 36, height: 2, background: T.border }}>
                          <div style={{ height: "100%", width: `${lf}%`, background: lf_color(lf) }} />
                        </div>
                        <span style={{ color: lf_color(lf), fontVariantNumeric: "tabular-nums" }}>
                          {lf}%
                        </span>
                      </div>
                    </td>
                    <td style={{ padding: "5px 10px", color: T.textDm, fontVariantNumeric: "tabular-nums" }}>
                      ₹{cp.floor_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                    </td>
                    <td style={{
                      padding: "5px 10px",
                      color: flash ? T.amber : T.text,
                      fontVariantNumeric: "tabular-nums",
                      transition: "color 0.4s ease",
                    }}>
                      ₹{cp.ml_fare_inr.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
