// ─── Domain: Airports ──────────────────────────────────────────────────────
export type AirportCode = "DEL" | "BOM" | "CCU" | "MAA";

export interface Airport {
  city:     string;
  name:     string;
  terminal: string;
}

// ─── Domain: Flights ───────────────────────────────────────────────────────
export type FlightStatus    = "ON TIME" | "DELAYED" | "BOARDING" | "CANCELLED";
export type TurbulenceLevel = "SEV" | "MOD" | "LOW";

export interface Flight {
  id:       string;
  from:     AirportCode;
  to:       AirportCode;
  dep:      string;          // "HH:MM" IST
  arr:      string;          // "HH:MM" IST
  price:    number;          // INR per person
  seats:    number;          // available seats
  aircraft: string;          // e.g. "A320neo"
  status:   FlightStatus;
  load:     number;          // 0–100 load factor %
  // Live-tick metadata set by flightReducer after WebSocket events
  _tick?: number;
  _dir?:  "up" | "down" | "flat";
}

export interface Inventory {
  capacity:  number;
  sold:      number;
  available: number;
}

export interface CurrentPricing {
  floor_inr:    number;
  ml_fare_inr:  number;
}

export interface LiveFlight {
  flight_id:       string;
  origin:          AirportCode;
  destination:     AirportCode;
  departure_date:  string;
  departure_time?: string;
  slot:            string;
  route:           string;
  status:          string;
  inventory:       Inventory;
  current_pricing: CurrentPricing;
}

// ─── Dashboard Stats (from /api/v1/dashboard/stats) ───────────────────────
export interface DashboardStats {
  total_flights:      number;
  total_capacity:     number;
  total_sold:         number;
  system_lf_pct:      number;
  active_routes:      number;
  total_bookings:     number;
  total_revenue_inr:  number;
  total_cost_inr:     number;
  contribution_inr:   number;
  margin_pct:         number;
  reports: {
    finance: boolean;
    network: boolean;
    fuel:    boolean;
  };
}

// ─── Finance Report ────────────────────────────────────────────────────────
export interface FinanceReport {
  available:           boolean;
  generated_at?:       string;
  overall_health?:     "HEALTHY" | "CAUTION" | "CRITICAL";
  executive_summary?:  string;
  route_ranking?: {
    star:        string[];
    acceptable:  string[];
    problem:     string[];
  };
  revenue_leakage?: {
    estimated_inr: number;
    explanation:   string;
  };
  recommendations?: { priority: number; action: string; expected_impact: string }[];
  total_revenue?:   number;
  total_cost?:      number;
}

// ─── Network Report ────────────────────────────────────────────────────────
export interface NetworkReport {
  available:                  boolean;
  generated_at?:              string;
  executive_summary?:         string;
  network_efficiency_score?:  { score: number; out_of: number; justification: string };
  frequency_decisions?:       { route: string; current: number; recommended: number; action: string; reason: string }[];
  growth_opportunities?:      { route: string; finding: string; action: string }[];
}

// ─── WebSocket Events (real Redis events) ─────────────────────────────────
export interface WsSeatSold {
  event_type:        "SEAT_SOLD";
  flight_id:         string;
  booking_ref:       string;
  passenger_id:      string;
  seats_sold:        number;
  seats_remaining:   number;
  price_charged_inr: number;
  timestamp_utc:     string;
}

export interface WsPriceUpdate {
  event_type:  "PRICE_UPDATE";
  flight_id:   string;
  old_fare:    number;
  new_fare:    number;
  action:      string;
  reason:      string;
  agent:       string;
  timestamp:   string;
}

export interface WsDisruption {
  event_type:         "DISRUPTION_RESOLVED";
  cancelled_flight:   string;
  route:              string;
  affected_bookings:  number;
  rebooked:           number;
  vouchered:          number;
  summary:            string;
}

export interface WsConnected {
  event_type: "CONNECTED";
  message:    string;
}

export type WsEvent = WsSeatSold | WsPriceUpdate | WsDisruption | WsConnected | { event_type: string };

// ─── App Navigation ────────────────────────────────────────────────────────
export type AppView = "b2c" | "login" | "aocc" | "seat-selection" | "payment" | "ops-login" | "ops-flights" | "ops-agents";

// ─── Store slices ──────────────────────────────────────────────────────────
export interface AuthState {
  authenticated: boolean;
  operatorId:    string | null;
  login:  (user: string, pass: string) => Promise<boolean>;
  logout: () => void;
}

// ─── CFO Briefing (from narrator agent) ────────────────────────────────────
export interface CfoBriefing {
  available:              boolean;
  generated_at?:          string;
  headline?:              string;
  financial_snapshot?:    string;
  route_performance?:     string;
  network_intelligence?:  string;
  risk_flags?:            string;
  recommendations?:       string;
  overall_health?:        "HEALTHY" | "CAUTION" | "CRITICAL";
}
