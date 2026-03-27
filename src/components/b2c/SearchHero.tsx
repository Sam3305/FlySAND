import React, { useState } from "react";
import type { AirportCode } from "../../types";
import { AIRPORTS, AIRPORT_CODES } from "../../constants";

interface SearchParams {
  from:      AirportCode;
  to:        AirportCode;
  date:      string;        // YYYY-MM-DD
  passengers: number;
}

interface Props {
  onSearch: (params: SearchParams) => void;
}

const selectStyle: React.CSSProperties = {
  background: "#F4F6FB", border: "none", outline: "none",
  fontSize: 16, fontWeight: 700, color: "#1A1A2E",
  padding: "8px 10px", borderRadius: 8, width: "100%",
  fontFamily: "Barlow, sans-serif",
};

// Default to tomorrow so there are always results in the 30-day seed window
function tomorrow(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

// Min = today, max = today + 30 (matches seed horizon)
function todayStr(): string  { return new Date().toISOString().split("T")[0]; }
function maxDateStr(): string {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().split("T")[0];
}

export const SearchHero: React.FC<Props> = ({ onSearch }) => {
  const [from,       setFrom]       = useState<AirportCode>("DEL");
  const [to,         setTo]         = useState<AirportCode>("BOM");
  const [date,       setDate]       = useState<string>(tomorrow());
  const [passengers, setPassengers] = useState<number>(1);

  const destinationOptions = AIRPORT_CODES.filter((k) => k !== from);

  const handleFromChange = (v: AirportCode) => {
    setFrom(v);
    // Swap if origin === destination
    if (v === to) setTo(AIRPORT_CODES.find((k) => k !== v)!);
  };

  const handleSearch = () => onSearch({ from, to, date, passengers });

  return (
    <div style={{ background: "linear-gradient(145deg,#0F3CC9,#1246e0 55%,#0a2aa0)", padding: "44px 20px 36px" }}>
      <div style={{ maxWidth: 1100, margin: "0 auto" }}>
        <h1 style={{ color: "#fff", fontSize: 28, fontWeight: 800, marginBottom: 4, letterSpacing: "-0.5px" }}>
          Book. Fly. Smile.
        </h1>
        <p style={{ color: "rgba(255,255,255,0.6)", fontSize: 13, marginBottom: 24 }}>
          Live ML-powered pricing · DEL · BOM · CCU · MAA
        </p>

        <div style={{
          background: "#fff", borderRadius: 16, padding: 16,
          display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap",
          boxShadow: "0 20px 60px rgba(0,0,0,0.3)",
        }}>
          {/* From */}
          <div style={{ flex: "1 1 140px", minWidth: 120 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.08em", marginBottom: 4 }}>FROM</div>
            <select value={from} onChange={(e) => handleFromChange(e.target.value as AirportCode)} style={selectStyle}>
              {AIRPORT_CODES.map((k) => (
                <option key={k} value={k}>{k} — {AIRPORTS[k].city}</option>
              ))}
            </select>
          </div>

          {/* To */}
          <div style={{ flex: "1 1 140px", minWidth: 120 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.08em", marginBottom: 4 }}>TO</div>
            <select value={to} onChange={(e) => setTo(e.target.value as AirportCode)} style={selectStyle}>
              {destinationOptions.map((k) => (
                <option key={k} value={k}>{k} — {AIRPORTS[k].city}</option>
              ))}
            </select>
          </div>

          {/* Date */}
          <div style={{ flex: "1 1 140px", minWidth: 120 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.08em", marginBottom: 4 }}>DATE</div>
            <input
              type="date"
              value={date}
              min={todayStr()}
              max={maxDateStr()}
              onChange={(e) => setDate(e.target.value)}
              style={{ ...selectStyle, fontWeight: 500 }}
            />
          </div>

          {/* Passengers */}
          <div style={{ flex: "1 1 120px", minWidth: 100 }}>
            <div style={{ fontSize: 10, fontWeight: 600, color: "#9CA3AF", letterSpacing: "0.08em", marginBottom: 4 }}>PASSENGERS</div>
            <select
              value={passengers}
              onChange={(e) => setPassengers(Number(e.target.value))}
              style={selectStyle}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n} Adult{n > 1 ? "s" : ""}</option>
              ))}
            </select>
          </div>

          <button
            onClick={handleSearch}
            style={{
              flex: "0 0 auto", background: "#FF6B00", color: "#fff", border: "none",
              borderRadius: 10, padding: "12px 28px", fontSize: 15, fontWeight: 700,
              cursor: "pointer", fontFamily: "Barlow, sans-serif", whiteSpace: "nowrap",
            }}
          >
            Search Flights
          </button>
        </div>
      </div>
    </div>
  );
};
