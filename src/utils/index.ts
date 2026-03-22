import type { FlightStatus, TurbulenceLevel } from "../types";
import { T } from "../constants";

// ─── Flight duration from "HH:MM" departure / arrival ────────────────────────
export function calcDuration(dep: string, arr: string): string {
  const [dh, dm] = dep.split(":").map(Number);
  const [ah, am] = arr.split(":").map(Number);
  const mins = ah * 60 + am - (dh * 60 + dm);
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

// ─── Colour helpers ──────────────────────────────────────────────────────────
export function statusColor(s: FlightStatus): string {
  return (
    { "ON TIME": "#2E7D32", DELAYED: "#E65100", BOARDING: "#1565C0", CANCELLED: "#C62828" }[s] ?? "#555"
  );
}

export function statusBg(s: FlightStatus): string {
  return (
    { "ON TIME": "#E8F5E9", DELAYED: "#FFF3E0", BOARDING: "#E3F2FD", CANCELLED: "#FFEBEE" }[s] ?? "#F5F5F5"
  );
}

export function loadColor(load: number): string {
  if (load > 85) return "#E63946";
  if (load > 65) return "#FF6B00";
  return "#00A36C";
}

export function turbColor(level: TurbulenceLevel): string {
  return level === "SEV" ? T.red : level === "MOD" ? T.amber : T.green;
}

// ─── Number formatters ────────────────────────────────────────────────────────
export function formatINR(value: number): string {
  return Math.round(value).toLocaleString("en-IN");
}

export function formatHHMMSS(date: Date): string {
  return date.toLocaleTimeString("en-IN", { hour12: false });
}

// ─── CAPE severity label ──────────────────────────────────────────────────────
export function capeSeverity(cape: number): string {
  if (cape > 3500) return "SEVERE";
  if (cape > 2200) return "MODERATE";
  return "STABLE";
}

export function capeColor(cape: number): string {
  if (cape > 3500) return T.red;
  if (cape > 2200) return T.amber;
  return T.green;
}

// ─── Headwind severity ────────────────────────────────────────────────────────
export function hdwindLabel(kph: number): string {
  if (kph > 70) return "HIGH";
  if (kph > 35) return "MOD";
  return "LOW";
}

export function hdwindColor(kph: number): string {
  if (kph > 70) return T.red;
  if (kph > 35) return T.amber;
  return T.green;
}

// ─── Clamp helper ─────────────────────────────────────────────────────────────
export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
