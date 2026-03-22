import { describe, it, expect } from "vitest";
import { calcDuration, formatINR, capeColor, capeSeverity, hdwindLabel, hdwindColor, clamp, loadColor } from "../src/utils";
import { flightReducer } from "../src/store/flightReducer";
import { SEED_FLIGHTS }  from "../src/constants";
import type { Flight }   from "../src/types";

// ─── Utils ────────────────────────────────────────────────────────────────────
describe("calcDuration", () => {
  it("calculates correct duration string", () => {
    expect(calcDuration("06:00", "08:15")).toBe("2h 15m");
    expect(calcDuration("09:30", "11:45")).toBe("2h 15m");
    expect(calcDuration("13:15", "16:00")).toBe("2h 45m");
  });
});

describe("formatINR", () => {
  it("rounds and formats in Indian locale", () => {
    expect(formatINR(4299)).toBe("4,299");
    expect(formatINR(14_500.9)).toBe("14,501");
  });
});

describe("capeColor + capeSeverity", () => {
  it("returns correct values for CAPE thresholds", () => {
    expect(capeColor(400)).toBe("#00E676");
    expect(capeSeverity(400)).toBe("STABLE");
    expect(capeColor(2500)).toBe("#FFB300");
    expect(capeSeverity(2500)).toBe("MODERATE");
    expect(capeColor(4000)).toBe("#FF1744");
    expect(capeSeverity(4000)).toBe("SEVERE");
  });
});

describe("hdwindLabel + hdwindColor", () => {
  it("categorises headwind correctly", () => {
    expect(hdwindLabel(20)).toBe("LOW");
    expect(hdwindLabel(50)).toBe("MOD");
    expect(hdwindLabel(80)).toBe("HIGH");
    expect(hdwindColor(80)).toBe("#FF1744");
  });
});

describe("clamp", () => {
  it("constrains values to [min, max]", () => {
    expect(clamp(5,   10, 20)).toBe(10);
    expect(clamp(15,  10, 20)).toBe(15);
    expect(clamp(25,  10, 20)).toBe(20);
  });
});

describe("loadColor", () => {
  it("returns red when load > 85", () => expect(loadColor(90)).toBe("#E63946"));
  it("returns orange when load 66–85", () => expect(loadColor(75)).toBe("#FF6B00"));
  it("returns green when load ≤ 65", () => expect(loadColor(50)).toBe("#00A36C"));
});

// ─── Flight reducer ───────────────────────────────────────────────────────────
describe("flightReducer", () => {
  const flight = SEED_FLIGHTS[0]; // 6E-201, initial price 4299

  it("ignores BATCH with no matching flight ID", () => {
    const state = flightReducer([flight], {
      type: "BATCH",
      payload: [{ type: "PRICE_UPDATE", fid: "UNKNOWN", delta: 999 }],
    });
    expect(state[0].price).toBe(flight.price);
  });

  it("applies PRICE_UPDATE delta correctly", () => {
    const state = flightReducer([flight], {
      type: "BATCH",
      payload: [{ type: "PRICE_UPDATE", fid: flight.id, delta: 500 }],
    });
    expect(state[0].price).toBe(flight.price + 500);
    expect(state[0]._dir).toBe("up");
  });

  it("clamps price to [PRICE_MIN, PRICE_MAX]", () => {
    const cheapFlight: Flight = { ...flight, price: 1_500 };
    const state = flightReducer([cheapFlight], {
      type: "BATCH",
      payload: [{ type: "PRICE_UPDATE", fid: flight.id, delta: -5_000 }],
    });
    expect(state[0].price).toBe(1_499); // WS_CONFIG.PRICE_MIN
  });

  it("applies SEAT_SOLD event correctly", () => {
    const state = flightReducer([flight], {
      type: "BATCH",
      payload: [{ type: "SEAT_SOLD", fid: flight.id, count: 2 }],
    });
    expect(state[0].seats).toBe(flight.seats - 2);
    expect(state[0].load).toBeGreaterThan(flight.load);
  });

  it("seats never go below zero", () => {
    const lastSeat: Flight = { ...flight, seats: 1 };
    const state = flightReducer([lastSeat], {
      type: "BATCH",
      payload: [{ type: "SEAT_SOLD", fid: flight.id, count: 99 }],
    });
    expect(state[0].seats).toBe(0);
  });

  it("batches multiple events for the same flight in one dispatch", () => {
    const state = flightReducer([flight], {
      type: "BATCH",
      payload: [
        { type: "PRICE_UPDATE", fid: flight.id, delta: 100 },
        { type: "PRICE_UPDATE", fid: flight.id, delta: 100 },
        { type: "SEAT_SOLD",    fid: flight.id, count: 1  },
      ],
    });
    // Both deltas applied sequentially
    expect(state[0].price).toBe(flight.price + 200);
    expect(state[0].seats).toBe(flight.seats - 1);
  });
});
