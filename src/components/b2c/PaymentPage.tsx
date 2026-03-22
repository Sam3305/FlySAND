import React, { useState } from "react";
import { ArrowLeft, CheckCircle, CreditCard, Smartphone, Building2, Lock } from "lucide-react";
import type { Flight } from "../../types";
import { AIRPORTS } from "../../constants";
import { formatINR } from "../../utils";
import { useBookingStore } from "../../store/bookingStore";
import { useNavStore }    from "../../store/navStore";

const CLR = {
  text:   "#1A1A2E",
  muted:  "#6B7280",
  border: "#EEF0F7",
  bg:     "#F4F6FB",
};

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "11px 14px",
  border: "1.5px solid #E5E7EB", borderRadius: 10,
  fontSize: 14, color: CLR.text, background: "#fff",
  outline: "none", boxSizing: "border-box",
  fontFamily: "Barlow, sans-serif",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11, fontWeight: 600, color: CLR.muted,
  letterSpacing: "0.06em", marginBottom: 5, display: "block",
};

type PayMethod = "upi" | "card" | "netbanking";

interface Props { flight: Flight }

export const PaymentPage: React.FC<Props> = ({ flight }) => {
  const { selectedSeats, passengerCount, clearBooking } = useBookingStore();
  const setView = useNavStore((s) => s.setView);

  // Passenger forms
  const [passengers, setPassengers] = useState(
    Array.from({ length: passengerCount }, () => ({
      name: "", age: "", gender: "Male",
    }))
  );

  // Contact
  const [email, setEmail]   = useState("");
  const [phone, setPhone]   = useState("");

  // Payment
  const [method, setMethod]       = useState<PayMethod>("upi");
  const [upiId, setUpiId]         = useState("");
  const [cardNum, setCardNum]     = useState("");
  const [cardExpiry, setCardExpiry] = useState("");
  const [cardCvv, setCardCvv]     = useState("");
  const [cardName, setCardName]   = useState("");
  const [bank, setBank]           = useState("SBI");

  // State
  const [loading,   setLoading]   = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [bookingRef, setBookingRef] = useState("");
  const [error, setError]         = useState("");

  const totalPrice = flight.price * passengerCount;

  const updatePassenger = (i: number, field: string, val: string) =>
    setPassengers((prev) => prev.map((p, idx) => idx === i ? { ...p, [field]: val } : p));

  const handlePay = async () => {
    // Basic validation
    if (!email || !phone) { setError("Please fill in contact details."); return; }
    if (passengers.some((p) => !p.name || !p.age)) { setError("Please fill in all passenger details."); return; }
    if (method === "upi"        && !upiId)                    { setError("Enter a valid UPI ID.");       return; }
    if (method === "card"       && (!cardNum || !cardExpiry || !cardCvv)) { setError("Enter complete card details."); return; }

    setError("");
    setLoading(true);

    try {
      // ── Resolve the real MongoDB flight_id ──────────────────────────────
      // B2CPortal now maps MongoDB docs directly so flight.id IS already
      // the full MongoDB _id (e.g. "6E-101_A_2026-03-22").
      // We still do a lookup to confirm availability and get a fresh status.
      // Parse the date from the flight_id: "6E-NNN_[ABC]_YYYY-MM-DD"
      const idParts = flight.id.split("_");
      const dateStr = idParts.length >= 3 ? idParts[idParts.length - 1] : "";

      const lookupRes = await fetch(
        `http://localhost:8000/api/v1/flights?origin=${flight.from}&destination=${flight.to}&departure_date=${dateStr}`
      );
      if (!lookupRes.ok) throw new Error("Could not fetch flight availability.");

      const availableFlights: Array<{ flight_id: string; departure_time: string; status: string }> =
        await lookupRes.json();

      // Match by departure_time (06:00 / 12:30 / 18:00) and scheduled status
      const match = availableFlights.find(
        (f) => f.departure_time === flight.dep && f.status === "scheduled"
      );
      if (!match) throw new Error("No available flight found for this route and time. It may be fully booked or departed.");

      const realFlightId = match.flight_id;

      // ── Call booking API with the real flight_id ──────────────────────────
      const res = await fetch("http://localhost:8000/api/v1/book", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          flight_id:       realFlightId,
          passenger_id:    email,
          seats_requested: passengerCount,
          idempotency_key: `${realFlightId}-${email}-${Date.now()}`,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        const detail = data?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : detail?.message ?? detail?.reason ?? detail?.error ?? JSON.stringify(detail);
        throw new Error(msg ?? "Booking failed.");
      }

      const data = await res.json();
      setBookingRef(data.booking_ref);
      setConfirmed(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  // ── Confirmation screen ───────────────────────────────────────────────────
  if (confirmed) {
    return (
      <div style={{
        minHeight: "100vh", background: CLR.bg,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>
        <div style={{
          background: "#fff", borderRadius: 20, padding: "48px 40px",
          maxWidth: 480, width: "100%", textAlign: "center",
          boxShadow: "0 20px 60px rgba(0,0,0,0.08)",
        }}>
          <CheckCircle size={56} color="#00A36C" style={{ marginBottom: 16 }} />
          <h2 style={{ fontSize: 24, fontWeight: 800, color: CLR.text, marginBottom: 8 }}>
            Booking Confirmed!
          </h2>
          <p style={{ color: CLR.muted, fontSize: 14, marginBottom: 24 }}>
            Your seats have been reserved. A confirmation has been sent to {email}.
          </p>

          <div style={{
            background: CLR.bg, borderRadius: 12, padding: "16px 20px", marginBottom: 24,
          }}>
            <div style={{ fontSize: 11, color: CLR.muted, marginBottom: 4 }}>BOOKING REFERENCE</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: "#0F3CC9", letterSpacing: "0.05em" }}>
              {bookingRef}
            </div>
          </div>

          <div style={{ textAlign: "left", marginBottom: 24 }}>
            {[
              ["Flight",     flight.id],
              ["Route",      `${AIRPORTS[flight.from]?.city} → ${AIRPORTS[flight.to]?.city}`],
              ["Departure",  flight.dep],
              ["Seats",      selectedSeats.join(", ")],
              ["Total paid", `₹${formatINR(totalPrice)}`],
            ].map(([k, v]) => (
              <div key={k} style={{
                display: "flex", justifyContent: "space-between",
                padding: "8px 0", borderBottom: `1px solid ${CLR.border}`,
                fontSize: 13,
              }}>
                <span style={{ color: CLR.muted }}>{k}</span>
                <span style={{ fontWeight: 600, color: CLR.text }}>{v}</span>
              </div>
            ))}
          </div>

          <button
            onClick={() => { clearBooking(); setView("b2c"); }}
            style={{
              background: "#0F3CC9", color: "#fff", border: "none",
              borderRadius: 12, padding: "14px 32px",
              fontSize: 14, fontWeight: 700, cursor: "pointer", width: "100%",
            }}
          >
            Back to Flights
          </button>
        </div>
      </div>
    );
  }

  // ── Payment form ─────────────────────────────────────────────────────────
  return (
    <div style={{ minHeight: "100vh", background: CLR.bg }}>

      {/* Header */}
      <div style={{
        background: "linear-gradient(145deg,#0F3CC9,#1246e0)",
        padding: "18px 24px", display: "flex", alignItems: "center", gap: 16,
      }}>
        <button
          onClick={() => setView("seat-selection")}
          style={{
            background: "rgba(255,255,255,0.15)", border: "none", borderRadius: 8,
            padding: "8px 12px", color: "#fff", cursor: "pointer",
            display: "flex", alignItems: "center", gap: 6, fontSize: 13,
          }}
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div style={{ flex: 1 }}>
          <div style={{ color: "rgba(255,255,255,0.7)", fontSize: 11, marginBottom: 2 }}>PAYMENT — {flight.id}</div>
          <div style={{ color: "#fff", fontSize: 16, fontWeight: 700 }}>
            {AIRPORTS[flight.from]?.city} → {AIRPORTS[flight.to]?.city}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, color: "rgba(255,255,255,0.8)", fontSize: 12 }}>
          <Lock size={12} /> Secure payment
        </div>
      </div>

      {/* Progress */}
      <div style={{
        background: "#fff", borderBottom: `1px solid ${CLR.border}`,
        padding: "12px 24px", display: "flex", gap: 32,
      }}>
        {["Search", "Select Seats", "Payment", "Confirmation"].map((step, i) => (
          <div key={step} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{
              width: 22, height: 22, borderRadius: "50%",
              background: i === 2 ? "#0F3CC9" : i < 2 ? "#00A36C" : "#E5E7EB",
              color: i <= 2 ? "#fff" : "#9CA3AF",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 11, fontWeight: 700,
            }}>{i + 1}</div>
            <span style={{
              fontSize: 12, fontWeight: i === 2 ? 700 : 400,
              color: i === 2 ? "#0F3CC9" : i < 2 ? "#00A36C" : "#9CA3AF",
            }}>{step}</span>
          </div>
        ))}
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 20px", display: "flex", gap: 24, flexWrap: "wrap" }}>

        {/* ── Left: forms ── */}
        <div style={{ flex: "1 1 500px", display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Passenger details */}
          <div style={{ background: "#fff", borderRadius: 16, border: `1px solid ${CLR.border}`, padding: 22 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: CLR.text, marginBottom: 18 }}>
              Passenger Details
            </h3>
            {passengers.map((p, i) => (
              <div key={i} style={{ marginBottom: i < passengers.length - 1 ? 20 : 0 }}>
                <div style={{
                  fontSize: 12, fontWeight: 700, color: "#0F3CC9",
                  marginBottom: 12, paddingBottom: 6,
                  borderBottom: `1px solid ${CLR.border}`,
                }}>
                  Passenger {i + 1} — Seat {selectedSeats[i] ?? "—"}
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                  <div style={{ flex: "2 1 180px" }}>
                    <label style={labelStyle}>FULL NAME (AS ON ID)</label>
                    <input
                      style={inputStyle} placeholder="e.g. Rahul Kumar"
                      value={p.name} onChange={(e) => updatePassenger(i, "name", e.target.value)}
                    />
                  </div>
                  <div style={{ flex: "1 1 80px" }}>
                    <label style={labelStyle}>AGE</label>
                    <input
                      style={inputStyle} placeholder="25" type="number" min={1} max={99}
                      value={p.age} onChange={(e) => updatePassenger(i, "age", e.target.value)}
                    />
                  </div>
                  <div style={{ flex: "1 1 100px" }}>
                    <label style={labelStyle}>GENDER</label>
                    <select
                      style={inputStyle}
                      value={p.gender} onChange={(e) => updatePassenger(i, "gender", e.target.value)}
                    >
                      <option>Male</option>
                      <option>Female</option>
                      <option>Other</option>
                    </select>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Contact details */}
          <div style={{ background: "#fff", borderRadius: 16, border: `1px solid ${CLR.border}`, padding: 22 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: CLR.text, marginBottom: 18 }}>
              Contact Details
            </h3>
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              <div style={{ flex: "1 1 200px" }}>
                <label style={labelStyle}>EMAIL ADDRESS</label>
                <input
                  style={inputStyle} placeholder="you@example.com" type="email"
                  value={email} onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div style={{ flex: "1 1 160px" }}>
                <label style={labelStyle}>MOBILE NUMBER</label>
                <input
                  style={inputStyle} placeholder="+91 98765 43210" type="tel"
                  value={phone} onChange={(e) => setPhone(e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* Payment method */}
          <div style={{ background: "#fff", borderRadius: 16, border: `1px solid ${CLR.border}`, padding: 22 }}>
            <h3 style={{ fontSize: 15, fontWeight: 700, color: CLR.text, marginBottom: 18 }}>
              Payment Method
            </h3>

            {/* Method tabs */}
            <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
              {([
                { id: "upi",        label: "UPI",         Icon: Smartphone  },
                { id: "card",       label: "Debit/Credit", Icon: CreditCard },
                { id: "netbanking", label: "Net Banking",  Icon: Building2  },
              ] as const).map(({ id, label, Icon }) => (
                <button
                  key={id}
                  onClick={() => setMethod(id)}
                  style={{
                    flex: 1, padding: "10px 0", borderRadius: 10,
                    border: `2px solid ${method === id ? "#0F3CC9" : "#E5E7EB"}`,
                    background: method === id ? "#EEF2FF" : "#fff",
                    color: method === id ? "#0F3CC9" : CLR.muted,
                    fontWeight: method === id ? 700 : 500,
                    fontSize: 12, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                  }}
                >
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>

            {/* UPI */}
            {method === "upi" && (
              <div>
                <label style={labelStyle}>UPI ID</label>
                <input
                  style={inputStyle} placeholder="yourname@upi"
                  value={upiId} onChange={(e) => setUpiId(e.target.value)}
                />
                <p style={{ fontSize: 11, color: CLR.muted, marginTop: 6 }}>
                  e.g. 9876543210@paytm · name@gpay · name@phonepe
                </p>
              </div>
            )}

            {/* Card */}
            {method === "card" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div>
                  <label style={labelStyle}>CARD NUMBER</label>
                  <input
                    style={inputStyle} placeholder="1234 5678 9012 3456"
                    maxLength={19}
                    value={cardNum}
                    onChange={(e) => setCardNum(e.target.value.replace(/\D/g,"").replace(/(.{4})/g,"$1 ").trim())}
                  />
                </div>
                <div>
                  <label style={labelStyle}>NAME ON CARD</label>
                  <input
                    style={inputStyle} placeholder="RAHUL KUMAR"
                    value={cardName} onChange={(e) => setCardName(e.target.value.toUpperCase())}
                  />
                </div>
                <div style={{ display: "flex", gap: 12 }}>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>EXPIRY</label>
                    <input
                      style={inputStyle} placeholder="MM / YY" maxLength={7}
                      value={cardExpiry}
                      onChange={(e) => {
                        const v = e.target.value.replace(/\D/g,"");
                        setCardExpiry(v.length >= 2 ? `${v.slice(0,2)} / ${v.slice(2,4)}` : v);
                      }}
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <label style={labelStyle}>CVV</label>
                    <input
                      style={inputStyle} placeholder="•••" maxLength={4} type="password"
                      value={cardCvv} onChange={(e) => setCardCvv(e.target.value.replace(/\D/g,""))}
                    />
                  </div>
                </div>
              </div>
            )}

            {/* Net Banking */}
            {method === "netbanking" && (
              <div>
                <label style={labelStyle}>SELECT BANK</label>
                <select style={inputStyle} value={bank} onChange={(e) => setBank(e.target.value)}>
                  {["SBI","HDFC Bank","ICICI Bank","Axis Bank","Kotak Bank","Yes Bank","PNB","Bank of Baroda"].map(
                    (b) => <option key={b}>{b}</option>
                  )}
                </select>
                <p style={{ fontSize: 11, color: CLR.muted, marginTop: 6 }}>
                  You'll be redirected to your bank's secure login page.
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Right: order summary ── */}
        <div style={{ flex: "0 0 260px", display: "flex", flexDirection: "column", gap: 16 }}>

          <div style={{ background: "#fff", borderRadius: 14, border: `1px solid ${CLR.border}`, padding: 20 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: CLR.text, marginBottom: 14 }}>
              Order Summary
            </div>

            {/* Flight info */}
            <div style={{
              background: CLR.bg, borderRadius: 10, padding: "12px 14px", marginBottom: 14,
            }}>
              <div style={{ fontSize: 11, color: CLR.muted, marginBottom: 4 }}>{flight.id} · {flight.aircraft}</div>
              <div style={{ fontWeight: 700, fontSize: 15, color: CLR.text }}>
                {AIRPORTS[flight.from]?.city} → {AIRPORTS[flight.to]?.city}
              </div>
              <div style={{ fontSize: 12, color: CLR.muted, marginTop: 2 }}>
                {flight.dep} · {selectedSeats.join(", ")}
              </div>
            </div>

            {/* Line items */}
            {[
              [`Base fare × ${passengerCount}`,    `₹${formatINR(flight.price * passengerCount)}`],
              ["Convenience fee",                   "₹0"],
              ["GST (5%)",                          "Included"],
            ].map(([k, v]) => (
              <div key={k} style={{
                display: "flex", justifyContent: "space-between",
                fontSize: 12, color: CLR.muted, marginBottom: 8,
              }}>
                <span>{k}</span><span>{v}</span>
              </div>
            ))}

            <div style={{
              display: "flex", justifyContent: "space-between",
              borderTop: `1px solid ${CLR.border}`, paddingTop: 12, marginTop: 4,
            }}>
              <span style={{ fontWeight: 700, fontSize: 14, color: CLR.text }}>Total</span>
              <span style={{ fontWeight: 800, fontSize: 20, color: "#0F3CC9" }}>
                ₹{formatINR(totalPrice)}
              </span>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={{
              background: "#FEF2F2", border: "1px solid #FECACA",
              borderRadius: 10, padding: "10px 14px",
              fontSize: 12, color: "#DC2626",
            }}>
              {error}
            </div>
          )}

          {/* Pay button */}
          <button
            onClick={handlePay}
            disabled={loading}
            style={{
              background: loading ? "#E5E7EB" : "#FF6B00",
              color: loading ? "#9CA3AF" : "#fff",
              border: "none", borderRadius: 12, padding: "16px 0",
              fontSize: 15, fontWeight: 700,
              cursor: loading ? "not-allowed" : "pointer",
              width: "100%", transition: "background 0.2s",
            }}
          >
            {loading ? "Processing…" : `Pay ₹${formatINR(totalPrice)}`}
          </button>

          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            gap: 6, fontSize: 11, color: CLR.muted,
          }}>
            <Lock size={11} /> 256-bit SSL encrypted · PCI DSS compliant
          </div>
        </div>
      </div>
    </div>
  );
};
