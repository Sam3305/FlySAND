import React, { useState, useEffect, useMemo } from "react";
import { Plane, TrendingUp, TrendingDown } from "lucide-react";
import type { Flight } from "../../types";
import { AIRPORTS } from "../../constants";
import { calcDuration, statusBg, statusColor, loadColor, formatINR } from "../../utils";
import { useBookingStore } from "../../store/bookingStore";
import { useNavStore }    from "../../store/navStore";

interface Props {
  flight: Flight;
  passengerCount?: number;
}

export const FlightCard: React.FC<Props> = ({ flight, passengerCount = 1 }) => {
  // Bump key each time a price tick arrives to replay CSS animation
  const [animKey, setAnimKey] = useState(0);
  useEffect(() => {
    if (flight._tick) setAnimKey((k) => k + 1);
  }, [flight._tick]);

  const selectFlight = useBookingStore((s) => s.selectFlight);
  const setView      = useNavStore((s) => s.setView);

  const handleBook = () => {
    selectFlight(flight, passengerCount);
    setView("seat-selection");
  };

  const duration  = useMemo(() => calcDuration(flight.dep, flight.arr), [flight.dep, flight.arr]);
  const priceColor = flight._dir === "down" ? "#00A36C" : flight._dir === "up" ? "#E63946" : "#1A1A2E";

  return (
    <div className="flight-card" style={{
      background: "#fff", borderRadius: 14,
      border: "1px solid #EEF0F7", padding: "18px 22px",
    }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>

        {/* ── Airline logo + flight number ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ textAlign: "center" }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10, background: "#0F3CC9",
              display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 4,
            }}>
              <Plane size={18} color="#fff" />
            </div>
            <span style={{ fontSize: 10, fontFamily: "'JetBrains Mono',monospace", color: "#9CA3AF" }}>
              {flight.id}
            </span>
          </div>

          {/* ── Route block ── */}
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {[
              { code: flight.from, time: flight.dep },
              null,
              { code: flight.to,   time: flight.arr },
            ].map((item, _i) =>
              item === null ? (
                <div key="mid" style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 11, color: "#9CA3AF", fontFamily: "'JetBrains Mono',monospace" }}>{duration}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 4, margin: "4px 0" }}>
                    <div style={{ width: 50, height: 1, background: "#E5E7EB" }} />
                    <Plane size={11} color="#D1D5DB" style={{ transform: "rotate(90deg)" }} />
                    <div style={{ width: 50, height: 1, background: "#E5E7EB" }} />
                  </div>
                  <div style={{ fontSize: 10, color: "#9CA3AF" }}>Nonstop</div>
                </div>
              ) : (
                <div key={item.code} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 22, fontWeight: 800, color: "#1A1A2E" }}>{item.time}</div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: "#0F3CC9" }}>{item.code}</div>
                  <div style={{ fontSize: 11, color: "#9CA3AF" }}>{AIRPORTS[item.code].city}</div>
                </div>
              )
            )}
          </div>

          {/* ── Load meter ── */}
          <div style={{ minWidth: 90 }}>
            <div style={{ fontSize: 10, color: "#9CA3AF", marginBottom: 4 }}>{flight.aircraft}</div>
            <div style={{ height: 4, background: "#F3F4F6", borderRadius: 2, overflow: "hidden", width: 80 }}>
              <div style={{
                height: "100%", width: `${flight.load}%`,
                background: loadColor(flight.load), borderRadius: 2,
                transition: "width 0.6s ease",
              }} />
            </div>
            <div style={{ fontSize: 11, color: loadColor(flight.load), marginTop: 3 }}>
              {flight.seats} seats · {Math.round(flight.load)}%
            </div>
          </div>
        </div>

        {/* ── Price + Status + CTA ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <span style={{
            fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 20,
            background: statusBg(flight.status), color: statusColor(flight.status),
          }}>
            {flight.status}
          </span>

          {/* Price re-mounts on each tick to replay pricePop animation */}
          <div key={animKey} className="price-pop" style={{ textAlign: "right" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 4 }}>
              {flight._dir === "up"   && <TrendingUp   size={12} color="#E63946" />}
              {flight._dir === "down" && <TrendingDown size={12} color="#00A36C" />}
              <span style={{ fontSize: 26, fontWeight: 800, color: priceColor, transition: "color 0.3s" }}>
                ₹{formatINR(flight.price)}
              </span>
            </div>
            <div style={{ fontSize: 10, color: "#9CA3AF" }}>per person · incl. taxes</div>
          </div>

          <button
            onClick={handleBook}
            style={{
              background: "#FF6B00", color: "#fff", border: "none",
              borderRadius: 10, padding: "12px 22px", fontSize: 14,
              fontWeight: 700, cursor: "pointer", fontFamily: "Barlow, sans-serif",
              whiteSpace: "nowrap",
            }}
          >
            Book Now
          </button>
        </div>
      </div>
    </div>
  );
};
