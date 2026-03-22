// ─── Domain: Airports ────────────────────────────────────────────────────────
export type AirportCode = "DEL" | "BOM" | "CCU" | "MAA";

export interface Airport {
  city: string;
  name: string;
  terminal: string;
}

// ─── Domain: Flights ─────────────────────────────────────────────────────────
export type FlightStatus = "ON TIME" | "DELAYED" | "BOARDING" | "CANCELLED";
export type PriceDirection = "up" | "down" | null;

export interface Flight {
  id: string;
  from: AirportCode;
  to: AirportCode;
  dep: string;
  arr: string;
  price: number;
  seats: number;
  aircraft: string;
  status: FlightStatus;
  load: number;
  _dir?: PriceDirection;
  _tick?: number;
}

// ─── WebSocket Events ────────────────────────────────────────────────────────
export type WsEventType = "PRICE_UPDATE" | "SEAT_SOLD";

export interface PriceUpdateEvent {
  type: "PRICE_UPDATE";
  fid: string;
  delta: number;
}

export interface SeatSoldEvent {
  type: "SEAT_SOLD";
  fid: string;
  count: number;
}

export type WsEvent = PriceUpdateEvent | SeatSoldEvent;

// ─── Store slices ─────────────────────────────────────────────────────────────
export interface LiveFlightState {
  flights: Flight[];
  connected: boolean;
  eventCount: number;
  swarmActive: boolean;
  batchSize: number;
}

export interface AuthState {
  authenticated: boolean;
  operatorId: string | null;
  login: (user: string, pass: string) => Promise<boolean>;
  logout: () => void;
}

// ─── Financial Metrics ───────────────────────────────────────────────────────
export interface CaskRaskDataPoint {
  t: string;
  CASK: number;
  RASK: number;
}

// ─── Thermodynamic Metrics ───────────────────────────────────────────────────
export type TurbulenceLevel = "NIL" | "LGT" | "MOD" | "SEV";
export type SigmetStatus   = "ACTIVE" | "CLEAR";

export interface RouteWindImpact {
  hw: number;
  tw: number;
  turb: TurbulenceLevel;
  eta: number;
}

export interface ThermodynamicMetrics {
  CAPE: number;
  HDWIND: number;
  QNH: number;
  TEMP: number;
  TROPO: number;
  TURB: TurbulenceLevel;
  ICING: string;
  SIGMET: SigmetStatus;
  WIND_DIR: string;
  ROUTES: Record<string, RouteWindImpact>;
}

// ─── App Navigation ───────────────────────────────────────────────────────────
export type AppView = "b2c" | "login" | "aocc" | "seat-selection" | "payment" | "ops-login" | "ops-flights";
