import React, { useMemo } from "react";
import { Plane, ArrowLeft, Users, Info } from "lucide-react";
import type { Flight } from "../../types";
import { AIRPORTS } from "../../constants";
import { formatINR } from "../../utils";
import { useBookingStore } from "../../store/bookingStore";
import { useNavStore }    from "../../store/navStore";

// ─── Aircraft cabin configs ───────────────────────────────────────────────────
const CABIN_CONFIG: Record<string, { rows: number; cols: string[]; exitRows: number[] }> = {
  "A321neo": { rows: 37, cols: ["A","B","C","D","E","F"], exitRows: [1,12,27] },
  "A321":    { rows: 37, cols: ["A","B","C","D","E","F"], exitRows: [1,12,27] },
  "A320neo": { rows: 31, cols: ["A","B","C","D","E","F"], exitRows: [1,11,24] },
  "A320":    { rows: 30, cols: ["A","B","C","D","E","F"], exitRows: [1,10,23] },
  "A320ceo": { rows: 30, cols: ["A","B","C","D","E","F"], exitRows: [1,10,23] },
  "ATR 72":  { rows: 13, cols: ["A","B","C","D"],         exitRows: [1,7]     },
};

const DEFAULT_CONFIG = { rows: 31, cols: ["A","B","C","D","E","F"], exitRows: [1,11,24] };

// Deterministic pseudo-random occupied set seeded by flight id + load
function buildOccupiedSet(flight: Flight, rows: number, cols: string[]): Set<string> {
  const totalSeats = rows * cols.length;
  const occupiedCount = Math.round((flight.load / 100) * totalSeats);
  const seed = flight.id.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const all: string[] = [];
  for (let r = 1; r <= rows; r++)
    for (const c of cols) all.push(`${r}${c}`);

  // Fisher-Yates with seeded LCG
  const shuffled = [...all];
  let s = seed;
  for (let i = shuffled.length - 1; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    const j = Math.abs(s) % (i + 1);
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return new Set(shuffled.slice(0, occupiedCount));
}

// ─── Colours ─────────────────────────────────────────────────────────────────
const CLR = {
  available: "#EEF2FF",
  availBorder: "#C7D2FE",
  selected:  "#0F3CC9",
  occupied:  "#E5E7EB",
  occupBorder:"#D1D5DB",
  exit:      "#FEF3C7",
  exitBorder:"#FCD34D",
  text:      "#1A1A2E",
  muted:     "#9CA3AF",
};

interface SeatProps {
  label: string;
  state: "available" | "selected" | "occupied";
  onClick: () => void;
}

const Seat: React.FC<SeatProps> = ({ label, state, onClick }) => (
  <div
    onClick={state !== "occupied" ? onClick : undefined}
    title={label}
    style={{
      width: 28, height: 28, borderRadius: 6,
      background: state === "selected" ? CLR.selected
                : state === "occupied"  ? CLR.occupied
                : CLR.available,
      border: `1.5px solid ${
        state === "selected" ? CLR.selected
      : state === "occupied"  ? CLR.occupBorder
      : CLR.availBorder}`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontSize: 9, fontWeight: 600,
      color: state === "selected" ? "#fff"
           : state === "occupied"  ? CLR.muted
           : "#4338CA",
      cursor: state === "occupied" ? "not-allowed" : "pointer",
      transition: "all 0.15s",
      userSelect: "none",
    }}
  >
    {state !== "occupied" ? label : ""}
  </div>
);

// ─── Main page ────────────────────────────────────────────────────────────────
interface Props { flight: Flight }

export const SeatSelectionPage: React.FC<Props> = ({ flight }) => {
  const { selectedSeats, passengerCount, toggleSeat } = useBookingStore();
  const setView = useNavStore((s) => s.setView);

  const cfg      = CABIN_CONFIG[flight.aircraft] ?? DEFAULT_CONFIG;
  const occupied = useMemo(() => buildOccupiedSet(flight, cfg.rows, cfg.cols), [flight]);

  const totalPrice = flight.price * selectedSeats.length;
  const canContinue = selectedSeats.length === passengerCount;

  return (
    <div style={{ minHeight: "100vh", background: "#F4F6FB" }}>

      {/* ── Header ── */}
      <div style={{
        background: "linear-gradient(145deg,#0F3CC9,#1246e0)",
        padding: "18px 24px", display: "flex", alignItems: "center", gap: 16,
      }}>
        <button
          onClick={() => setView("b2c")}
          style={{
            background: "rgba(255,255,255,0.15)", border: "none", borderRadius: 8,
            padding: "8px 12px", color: "#fff", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, fontSize: 13,
          }}
        >
          <ArrowLeft size={14} /> Back
        </button>

        <div style={{ flex: 1 }}>
          <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 11, marginBottom: 2 }}>
            SELECT SEATS — {flight.id}
          </div>
          <div style={{ color: "#fff", fontSize: 16, fontWeight: 700 }}>
            {AIRPORTS[flight.from]?.city} → {AIRPORTS[flight.to]?.city}
            <span style={{ fontWeight: 400, fontSize: 13, marginLeft: 10, opacity: 0.8 }}>
              {flight.dep} · {flight.aircraft}
            </span>
          </div>
        </div>

        <div style={{ textAlign: "right" }}>
          <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 11 }}>per person</div>
          <div style={{ color: "#fff", fontWeight: 800, fontSize: 20 }}>
            ₹{formatINR(flight.price)}
          </div>
        </div>
      </div>

      {/* ── Progress bar ── */}
      <div style={{
        background: "#fff", borderBottom: "1px solid #EEF0F7",
        padding: "12px 24px", display: "flex", gap: 32,
      }}>
        {["Search", "Select Seats", "Payment", "Confirmation"].map((step, i) => (
          <div key={step} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 22, height: 22, borderRadius: "50%",
              background: i === 1 ? "#0F3CC9" : i < 1 ? "#00A36C" : "#E5E7EB",
              color: i <= 1 ? "#fff" : "#9CA3AF",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700,
            }}>{i + 1}</div>
            <span style={{
              fontSize: 12, fontWeight: i === 1 ? 700 : 400,
              color: i === 1 ? "#0F3CC9" : i < 1 ? "#00A36C" : "#9CA3AF",
            }}>{step}</span>
          </div>
        ))}
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px", display: "flex", gap: 24, flexWrap: "wrap" }}>

        {/* ── Cabin map ── */}
        <div style={{ flex: "1 1 520px" }}>
          <div style={{
            background: "#fff", borderRadius: 16, border: "1px solid #EEF0F7",
            padding: 20, overflowY: "auto", maxHeight: "70vh",
          }}>
            {/* Legend */}
            <div style={{ display: "flex", gap: 16, marginBottom: 18, flexWrap: "wrap" }}>
              {[
                { color: CLR.available, border: CLR.availBorder, label: "Available" },
                { color: CLR.selected,  border: CLR.selected,    label: "Selected"  },
                { color: CLR.occupied,  border: CLR.occupBorder, label: "Occupied"  },
                { color: CLR.exit,      border: CLR.exitBorder,  label: "Exit row"  },
              ].map(({ color, border, label }) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{
                    width: 14, height: 14, borderRadius: 3,
                    background: color, border: `1.5px solid ${border}`,
                  }} />
                  <span style={{ fontSize: 11, color: CLR.muted }}>{label}</span>
                </div>
              ))}
            </div>

            {/* Column headers */}
            <div style={{ display: "flex", gap: 4, marginBottom: 6, paddingLeft: 36 }}>
              {cfg.cols.map((col, i) => (
                <React.Fragment key={col}>
                  {cfg.cols.length === 6 && i === 3 && <div style={{ width: 20 }} />}
                  <div style={{ width: 28, textAlign: "center", fontSize: 10, fontWeight: 700, color: CLR.muted }}>
                    {col}
                  </div>
                </React.Fragment>
              ))}
            </div>

            {/* Rows */}
            {Array.from({ length: cfg.rows }, (_, ri) => {
              const row = ri + 1;
              const isExit = cfg.exitRows.includes(row);
              return (
                <div key={row}>
                  {isExit && (
                    <div style={{
                      fontSize: 9, color: "#92400E", background: CLR.exit,
                      border: `1px solid ${CLR.exitBorder}`,
                      borderRadius: 4, padding: "2px 8px",
                      marginBottom: 4, display: "inline-block",
                    }}>
                      ⬛ EXIT ROW
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 4, marginBottom: 3, alignItems: "center" }}>
                    {/* Row number */}
                    <div style={{ width: 28, textAlign: "right", fontSize: 10, color: CLR.muted, marginRight: 4 }}>
                      {row}
                    </div>
                    {cfg.cols.map((col, i) => {
                      const seatId = `${row}${col}`;
                      const isOccupied = occupied.has(seatId);
                      const isSelected = selectedSeats.includes(seatId);
                      return (
                        <React.Fragment key={seatId}>
                          {cfg.cols.length === 6 && i === 3 && <div style={{ width: 20 }} />}
                          <Seat
                            label={seatId}
                            state={isSelected ? "selected" : isOccupied ? "occupied" : "available"}
                            onClick={() => toggleSeat(seatId)}
                          />
                        </React.Fragment>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            {/* Nose indicator */}
            <div style={{ textAlign: "center", marginTop: 16, color: CLR.muted, fontSize: 11 }}>
              <Plane size={18} style={{ transform: "rotate(-90deg)", opacity: 0.3 }} />
              <div style={{ fontSize: 10, marginTop: 4 }}>Front of aircraft</div>
            </div>
          </div>
        </div>

        {/* ── Right panel ── */}
        <div style={{ flex: "0 0 260px", display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Passenger counter */}
          <div style={{
            background: "#fff", borderRadius: 14, border: "1px solid #EEF0F7", padding: 18,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <Users size={16} color="#0F3CC9" />
              <span style={{ fontWeight: 700, fontSize: 14, color: CLR.text }}>Seat Selection</span>
            </div>
            <div style={{
              fontSize: 13, color: CLR.muted, marginBottom: 10,
              padding: "10px 14px", background: "#F4F6FB", borderRadius: 8,
            }}>
              Select <strong style={{ color: "#0F3CC9" }}>{passengerCount}</strong> seat{passengerCount > 1 ? "s" : ""} for this booking
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Array.from({ length: passengerCount }, (_, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  padding: "8px 12px", borderRadius: 8,
                  background: selectedSeats[i] ? "#EEF2FF" : "#F9FAFB",
                  border: `1px solid ${selectedSeats[i] ? "#C7D2FE" : "#E5E7EB"}`,
                }}>
                  <span style={{ fontSize: 12, color: CLR.muted }}>Passenger {i + 1}</span>
                  <span style={{
                    fontSize: 13, fontWeight: 700,
                    color: selectedSeats[i] ? "#0F3CC9" : CLR.muted,
                  }}>
                    {selectedSeats[i] ?? "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Price summary */}
          <div style={{
            background: "#fff", borderRadius: 14, border: "1px solid #EEF0F7", padding: 18,
          }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: CLR.text, marginBottom: 12 }}>
              Price Summary
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 8 }}>
              <span style={{ color: CLR.muted }}>Base fare × {selectedSeats.length || passengerCount}</span>
              <span style={{ color: CLR.text }}>₹{formatINR(flight.price * (selectedSeats.length || passengerCount))}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 12 }}>
              <span style={{ color: CLR.muted }}>Taxes &amp; fees</span>
              <span style={{ color: CLR.text }}>Included</span>
            </div>
            <div style={{
              display: "flex", justifyContent: "space-between",
              borderTop: "1px solid #EEF0F7", paddingTop: 12,
            }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: CLR.text }}>Total</span>
              <span style={{ fontWeight: 800, fontSize: 18, color: "#0F3CC9" }}>
                ₹{formatINR(totalPrice || flight.price * passengerCount)}
              </span>
            </div>
          </div>

          {/* Info note */}
          <div style={{
            display: "flex", gap: 8, padding: "10px 14px",
            background: "#FFFBEB", borderRadius: 10, border: "1px solid #FDE68A",
          }}>
            <Info size={14} color="#D97706" style={{ flexShrink: 0, marginTop: 1 }} />
            <span style={{ fontSize: 11, color: "#92400E", lineHeight: 1.5 }}>
              Prices are live and may change. Your seat is held for 10 minutes once you proceed to payment.
            </span>
          </div>

          {/* CTA */}
          <button
            disabled={!canContinue}
            onClick={() => setView("payment")}
            style={{
              background: canContinue ? "#FF6B00" : "#E5E7EB",
              color: canContinue ? "#fff" : "#9CA3AF",
              border: "none", borderRadius: 12,
              padding: "16px 0", fontSize: 15, fontWeight: 700,
              cursor: canContinue ? "pointer" : "not-allowed",
              width: "100%", transition: "background 0.2s",
            }}
          >
            {canContinue
              ? `Continue to Payment →`
              : `Select ${passengerCount - selectedSeats.length} more seat${passengerCount - selectedSeats.length > 1 ? "s" : ""}`
            }
          </button>
        </div>
      </div>
    </div>
  );
};
