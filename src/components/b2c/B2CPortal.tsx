import React, { useState, useCallback } from "react";
import { Plane, Loader } from "lucide-react";
import type { AirportCode, Flight, FlightStatus, LiveFlightState } from "../../types";
import { AIRPORTS } from "../../constants";
import { B2CNav }      from "./B2CNav";
import { SearchHero }  from "./SearchHero";
import { FlightCard }  from "./FlightCard";
import { WsStatusBadge } from "../shared/WsStatusBadge";

interface SearchParams {
  from:       AirportCode;
  to:         AirportCode;
  date:       string;
  passengers: number;
}

interface Props {
  live: LiveFlightState;
}

// Slot → departure/arrival times (IST)
const SLOT_TIMES: Record<string, { dep: string; arr: string }> = {
  A: { dep: "06:00", arr: "08:30" },
  B: { dep: "12:30", arr: "15:00" },
  C: { dep: "18:00", arr: "20:30" },
};

// Map a raw MongoDB live_flight doc → frontend Flight shape
function docToFlight(doc: Record<string, unknown>): Flight {
  const slot       = String(doc.slot ?? "A");
  const times      = SLOT_TIMES[slot] ?? SLOT_TIMES["A"];
  const inventory  = (doc.inventory  as Record<string, number>)  ?? {};
  const pricing    = (doc.current_pricing as Record<string, number>) ?? {};
  const physics    = (doc.physics_snapshot as Record<string, unknown>) ?? {};

  const capacity  = inventory.capacity  ?? 180;
  const available = inventory.available ?? 0;
  const load      = capacity > 0 ? Math.round(((capacity - available) / capacity) * 100) : 0;

  const statusMap: Record<string, FlightStatus> = {
    scheduled: "ON TIME",
    boarding:  "BOARDING",
    airborne:  "ON TIME",
    landed:    "ON TIME",
    cancelled: "CANCELLED",
  };

  return {
    id:       String(doc.flight_id ?? doc._id ?? ""),
    from:     String(doc.origin      ?? "") as AirportCode,
    to:       String(doc.destination ?? "") as AirportCode,
    dep:      times.dep,
    arr:      times.arr,
    price:    Math.round(pricing.ml_fare_inr ?? pricing.floor_inr ?? 0),
    seats:    available,
    aircraft: String(physics.aircraft_icao ?? "A20N"),
    status:   statusMap[String(doc.status ?? "scheduled")] ?? "ON TIME",
    load,
  };
}

export const B2CPortal: React.FC<Props> = ({ live }) => {
  const [flights,    setFlights]    = useState<Flight[]>([]);
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState("");
  const [searched,   setSearched]   = useState(false);
  const [lastSearch, setLastSearch] = useState<SearchParams | null>(null);

  const handleSearch = useCallback(async (params: SearchParams) => {
    setLoading(true);
    setError("");
    setSearched(true);
    setLastSearch(params);

    try {
      const url = new URL("http://localhost:8000/api/v1/flights");
      url.searchParams.set("origin",         params.from);
      url.searchParams.set("destination",    params.to);
      url.searchParams.set("departure_date", params.date);

      const res = await fetch(url.toString());
      if (!res.ok) throw new Error(`API error ${res.status}`);

      const docs: Record<string, unknown>[] = await res.json();
      // Filter only bookable statuses and sort by departure slot
      const mapped = docs
        .filter((d) => d.status !== "cancelled")
        .map(docToFlight)
        .sort((a, b) => a.dep.localeCompare(b.dep));

      setFlights(mapped);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch flights.");
      setFlights([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fromCity = lastSearch ? AIRPORTS[lastSearch.from]?.city : "";
  const toCity   = lastSearch ? AIRPORTS[lastSearch.to]?.city   : "";

  return (
    <div className="b2c" style={{ minHeight: "100vh", background: "#F4F6FB" }}>
      <B2CNav />
      <SearchHero onSearch={handleSearch} />

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "20px 20px 60px" }}>

        {/* Sub-header — only shown after first search */}
        {searched && (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
            <div>
              <h2 style={{ fontSize: 18, fontWeight: 700, color: "#1A1A2E" }}>
                {fromCity} → {toCity}
                {lastSearch && (
                  <span style={{ fontWeight: 400, fontSize: 14, color: "#6B7280", marginLeft: 10 }}>
                    {lastSearch.date} · {lastSearch.passengers} passenger{lastSearch.passengers > 1 ? "s" : ""}
                  </span>
                )}
              </h2>
              {!loading && (
                <p style={{ fontSize: 13, color: "#6B7280" }}>
                  {flights.length} flight{flights.length !== 1 ? "s" : ""} found
                </p>
              )}
            </div>
            <WsStatusBadge
              connected={live.connected}
              eventCount={live.eventCount}
              swarmActive={live.swarmActive}
              variant="b2c"
            />
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div style={{ textAlign: "center", padding: 60, color: "#6B7280" }}>
            <Loader size={32} style={{ opacity: 0.4, marginBottom: 12, animation: "spin 1s linear infinite" }} />
            <p style={{ fontSize: 15 }}>Searching flights…</p>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div style={{
            background: "#FEF2F2", border: "1px solid #FECACA",
            borderRadius: 12, padding: "16px 20px", color: "#DC2626", fontSize: 14,
          }}>
            {error}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && searched && flights.length === 0 && (
          <div style={{ textAlign: "center", padding: 60, color: "#9CA3AF" }}>
            <Plane size={44} style={{ opacity: 0.2, marginBottom: 12 }} />
            <p style={{ fontSize: 15 }}>No flights found for this route and date.</p>
            <p style={{ fontSize: 13, marginTop: 6 }}>Try a different date within the next 30 days.</p>
          </div>
        )}

        {/* Prompt before first search */}
        {!loading && !searched && (
          <div style={{ textAlign: "center", padding: 60, color: "#9CA3AF" }}>
            <Plane size={44} style={{ opacity: 0.2, marginBottom: 12 }} />
            <p style={{ fontSize: 15 }}>Select your route and date above to see live flights.</p>
          </div>
        )}

        {/* Flight list */}
        {!loading && !error && flights.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {flights.map((f) => (
              <FlightCard
                key={f.id}
                flight={f}
                passengerCount={lastSearch?.passengers ?? 1}
              />
            ))}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
};
