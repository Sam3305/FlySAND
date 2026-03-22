import type { Airport, AirportCode, Flight } from "../types";

// ─── Network Scope ────────────────────────────────────────────────────────────
export const AIRPORTS: Record<AirportCode, Airport> = {
  DEL: { city: "Delhi",   name: "Indira Gandhi Intl",          terminal: "T2" },
  BOM: { city: "Mumbai",  name: "Chhatrapati Shivaji Maharaj", terminal: "T1" },
  CCU: { city: "Kolkata", name: "Netaji Subhas Chandra Bose",  terminal: "T2" },
  MAA: { city: "Chennai", name: "Chennai International",       terminal: "T3" },
};

export const AIRPORT_CODES = Object.keys(AIRPORTS) as AirportCode[];

// ─── Seed Flights ─────────────────────────────────────────────────────────────
export const SEED_FLIGHTS: Flight[] = [
  { id:"6E-201", from:"DEL", to:"BOM", dep:"06:00", arr:"08:15", price:4299,  seats:147, aircraft:"A320neo",  status:"ON TIME",  load:68 },
  { id:"6E-203", from:"DEL", to:"BOM", dep:"09:30", arr:"11:45", price:5180,  seats:42,  aircraft:"A321",     status:"ON TIME",  load:82 },
  { id:"6E-341", from:"DEL", to:"CCU", dep:"07:20", arr:"09:50", price:3850,  seats:203, aircraft:"A320neo",  status:"DELAYED",  load:45 },
  { id:"6E-512", from:"DEL", to:"MAA", dep:"08:45", arr:"11:30", price:5699,  seats:18,  aircraft:"A321XLR",  status:"ON TIME",  load:91 },
  { id:"6E-627", from:"BOM", to:"DEL", dep:"14:00", arr:"16:15", price:4550,  seats:76,  aircraft:"A320neo",  status:"ON TIME",  load:74 },
  { id:"6E-789", from:"BOM", to:"CCU", dep:"11:20", arr:"13:40", price:4120,  seats:112, aircraft:"A320",     status:"BOARDING", load:88 },
  { id:"6E-834", from:"CCU", to:"DEL", dep:"16:30", arr:"19:00", price:3920,  seats:58,  aircraft:"ATR 72",   status:"ON TIME",  load:63 },
  { id:"6E-901", from:"MAA", to:"DEL", dep:"13:15", arr:"16:00", price:5350,  seats:8,   aircraft:"A321XLR",  status:"ON TIME",  load:96 },
];

// ─── WebSocket Config ─────────────────────────────────────────────────────────
export const WS_CONFIG = {
  THROTTLE_MS:       500,   // state-batch flush interval
  NORMAL_INTERVAL:   480,   // ms between normal price ticks
  SWARM_INTERVAL_MS: 32,    // ms between events during a swarm burst
  SWARM_CYCLE_MS:    18_000,// ms between swarm activations
  SWARM_EVENT_COUNT: 120,   // total events fired per swarm burst
  PRICE_MIN:         1_499,
  PRICE_MAX:         18_000,
  NORMAL_DELTA:      110,   // max ± delta in normal mode
  SWARM_DELTA:       220,   // max ± delta in swarm mode
};

// ─── AOCC Theme Tokens ────────────────────────────────────────────────────────
export const T = {
  bg:       "#090909",
  panel:    "#0D0D0D",
  border:   "#191919",
  borderBt: "#2a2a2a",
  text:     "#B8B8B8",
  textBt:   "#EFEFEF",
  textDm:   "#444",
  green:    "#00E676",
  amber:    "#FFB300",
  red:      "#FF1744",
  cyan:     "#00E5FF",
  purple:   "#BB86FC",
  blue:     "#448AFF",
} as const;

// ─── AOCC Auth ────────────────────────────────────────────────────────────────
export const AOCC_CREDENTIALS = {
  user: "AOCC_OPS",
  pass: "6E_TERMINAL",
} as const;

export const OPS_CREDENTIALS = {
  user: "ops",
  pass: "ops@123",
} as const;
