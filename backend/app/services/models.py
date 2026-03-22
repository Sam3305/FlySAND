"""
database/models.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Pydantic v2 Schema — MongoDB `live_flights` Collection
──────────────────────────────────────────────────────────────────────────────

DESIGN PRINCIPLES
─────────────────
1.  Every sub-document mirrors the exact dict shape returned by the engine
    layer (physics_engine.py, economics_engine.py). No fields renamed.
    Seeder can pass engine-output dicts directly via Model(**engine_dict).

2.  CARDINAL RULE is enforced at the Pydantic layer before MongoDB write:
        current_pricing.ml_fare_inr  >=  current_pricing.floor_inr  (ALWAYS)

3.  Inventory consistency is validated:
        sold + available == capacity  (ALWAYS)

4.  flight_id convention: "6E-<NUM>_<SLOT>_<ISO-DATE>"
    e.g. "6E-101_A_2026-10-16"

LAYER MAP
─────────
  LiveFlight
  ├── FlightInventory      (capacity / sold / available)
  ├── CurrentPricing       generate_market_fares().pricing_breakdown.floor_inr)
  │                        (ml_fare_inr <- generate_market_fares().pricing_breakdown.final_dynamic_price_inr)
  └── PhysicsSnapshot
      ├── FlightPhases     (mirrors physics_engine.flight_phases sub-dict)
      └── ThermoMetrics    (mirrors physics_engine.thermodynamic_metrics sub-dict)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator


# =============================================================================
# ENUMS
# =============================================================================

class FlightStatus(str, Enum):
    """Lifecycle states for a single flight document."""
    SCHEDULED = "scheduled"   # Future departure — inventory open for booking
    BOARDING  = "boarding"    # T-45 min gate open — inventory locked
    AIRBORNE  = "airborne"    # Wheels-off — revenue realised
    LANDED    = "landed"      # Wheels-on — final revenue locked, cycle complete
    CANCELLED = "cancelled"   # Ops / weather cancel


class AircraftICAO(str, Enum):
    """IndiGo fleet ICAO codes tracked by openap_service.py."""
    A20N = "A20N"   # Airbus A320neo  — 186 high-density seats (IndiGo config)
    A21N = "A21N"   # Airbus A321neo  — 222 high-density seats
    A320 = "A320"   # Airbus A320ceo  — 180 seats (legacy fleet)
    AT72 = "AT72"   # ATR 72-600      — 78 seats (regional)


class DepartureSlot(str, Enum):
    """Three daily departure waves per route (IndiGo LCC bank structure)."""
    MORNING   = "A"   # 06:00 IST
    AFTERNOON = "B"   # 12:30 IST
    EVENING   = "C"   # 18:00 IST


# =============================================================================
# SUB-DOCUMENT: FlightPhases
# Maps 1-to-1 to physics_engine.calculate_physical_flight()['flight_phases']
# =============================================================================

class FlightPhases(BaseModel):
    """
    LCC standard phase-split fuel burn (kg) from AeroPhysicsEngine.
    Thermodynamic multipliers and payload penalties are already baked in.
    """
    climb_fuel_kg:           Annotated[float, Field(gt=0,
        description="Climb phase — engines at ~185% base burn rate")]
    cruise_fuel_kg:          Annotated[float, Field(gt=0,
        description="Cruise phase — thermo-adjusted + payload penalty applied")]
    descent_fuel_kg:         Annotated[float, Field(gt=0,
        description="Descent phase — ~35% base burn (idle/gravity driven)")]
    ground_and_hold_fuel_kg: Annotated[float, Field(ge=0,
        description="Taxi + takeoff + ATC holding burn at 40% thrust")]

    @property
    def total_computed_kg(self) -> float:
        """Convenience: sum across all four phases. Should match physics total."""
        return (
            self.climb_fuel_kg
            + self.cruise_fuel_kg
            + self.descent_fuel_kg
            + self.ground_and_hold_fuel_kg
        )


# =============================================================================
# SUB-DOCUMENT: ThermoMetrics
# Maps 1-to-1 to physics_engine.calculate_physical_flight()['thermodynamic_metrics']
# =============================================================================

class ThermoMetrics(BaseModel):
    """
    Thermodynamic and aerodynamic conditions from
    ThermodynamicCalculator.calculate_environmental_impact() via Open-Meteo data.
    """
    calculated_rho_kg_m3:   float = Field(
        description="True air density calculated via Tetens vapour-pressure equation (kg/m^3)")
    density_ratio:          float = Field(
        description="rho_actual / rho_ISA — values <1.0 trigger thrust-lapse fuel penalty")
    v_ground_kph:           float = Field(gt=0,
        description="True airspeed offset by jet-stream headwind/tailwind vector (km/h)")
    actual_flight_time_hrs: float = Field(gt=0,
        description="Pure en-route flight time; excludes taxi and ATC holding")
    total_burn_multiplier:  float = Field(ge=1.0,
        description="Combined scalar: density_lapse_multiplier x chaos_multiplier")
    atc_holding_time_mins:  int   = Field(ge=0,
        description="Aggregate ATC delay accrued from icing / CAPE / precipitation events")


# =============================================================================
# SUB-DOCUMENT: PhysicsSnapshot
# Wraps the top-level output of AeroPhysicsEngine.calculate_physical_flight()
# =============================================================================

class PhysicsSnapshot(BaseModel):
    """
    Immutable physics record captured at seed time.
    Never mutated by downstream pricing or booking events.
    Provides the thermodynamic audit trail for every fare decision.
    """
    aircraft_icao:         str   = Field(
        description="OpenAP ICAO fleet code (A20N / A21N / A320 / AT72)")
    distance_km:           float = Field(gt=0,
        description="Great-circle route distance computed via Haversine formula")
    block_time_hrs:        float = Field(gt=0,
        description="Gate-to-gate block time including taxi, en-route and ATC holding")
    total_fuel_burn_kg:    float = Field(gt=0,
        description="Aggregate fuel across all four phases with all penalties applied")
    flight_phases:         FlightPhases
    thermodynamic_metrics: ThermoMetrics

    @field_validator("aircraft_icao")
    @classmethod
    def validate_fleet_icao(cls, v: str) -> str:
        valid = {item.value for item in AircraftICAO}
        if v not in valid:
            raise ValueError(
                f"aircraft_icao '{v}' is not in the IndiGo fleet registry {valid}. "
                f"Check openap_service.fleet_map."
            )
        return v


# =============================================================================
# SUB-DOCUMENT: FlightInventory
# =============================================================================

class FlightInventory(BaseModel):
    """
    Real-time seat inventory triple.
    `sold` is updated by the booking engine; the other two are locked at seed.
    Pydantic enforces the inventory identity at every write.
    """
    capacity:  Annotated[int, Field(gt=0,
        description="Total available seats — IndiGo high-density from openap_service.indigo_pax")]
    sold:      Annotated[int, Field(ge=0,
        description="Seats sold — incremented by booking events, 0 at seed time")]
    available: Annotated[int, Field(ge=0,
        description="Remaining bookable seats: capacity - sold")]

    @model_validator(mode="after")
    def check_inventory_consistency(self) -> "FlightInventory":
        """
        Invariant: sold + available == capacity, sold <= capacity.
        Violated during an oversell or a stale cache write — caught here.
        """
        if self.sold + self.available != self.capacity:
            raise ValueError(
                f"Inventory triple is inconsistent: "
                f"sold({self.sold}) + available({self.available}) "
                f"!= capacity({self.capacity}). "
                f"All three values must be provided and must balance."
            )
        if self.sold > self.capacity:
            raise ValueError(
                f"Oversell detected: sold({self.sold}) > capacity({self.capacity})."
            )
        return self


# =============================================================================
# SUB-DOCUMENT: CurrentPricing
# =============================================================================

class CurrentPricing(BaseModel):
    """
    Dual-price model enforcing the AeroSync-India Cardinal Rule.

    floor_inr
        Source : generate_market_fares().pricing_breakdown.floor_inr
                 Equals break_even_base_fare_inr + fixed_taxes_and_fees,
                 computed and returned by the engine directly.

    ml_fare_inr
        Source : generate_market_fares().pricing_breakdown.final_dynamic_price_inr
                 Engine applies 13.5% margin + EventOracle demand multiplier
                 to the variable (non-tax) fare portion, then clamps to floor_inr.

    CARDINAL RULE (model_validator):
        ml_fare_inr >= floor_inr
        Any document that violates this raises ValidationError before MongoDB write.
    """
    floor_inr:   Annotated[float, Field(gt=0,
        description="Per-seat break-even cost. ABSOLUTE MINIMUM. Never sell below this.")]
    ml_fare_inr: Annotated[float, Field(gt=0,
        description="Dynamic demand-adjusted fare. Always >= floor_inr by cardinal rule.")]

    @model_validator(mode="after")
    def enforce_cardinal_price_floor(self) -> "CurrentPricing":
        """
        CARDINAL RULE ENFORCEMENT POINT.
        This is the last line of defence before a below-cost fare reaches MongoDB.
        If this raises, the seeder's clamp logic has a bug and must be fixed.
        """
        if self.ml_fare_inr < self.floor_inr:
            raise ValueError(
                f"CARDINAL RULE VIOLATED — "
                f"ml_fare_inr (Rs {self.ml_fare_inr:,.2f}) is below "
                f"floor_inr (Rs {self.floor_inr:,.2f}). "
                f"The airline cannot sell a seat below its physics-derived cost. "
                f"Seeder must clamp: ml_fare = max(computed_fare, floor_inr)."
            )
        return self

    @property
    def margin_pct(self) -> float:
        """Percentage margin above the break-even floor."""
        return round((self.ml_fare_inr / self.floor_inr - 1.0) * 100, 2)

    @property
    def markup_inr(self) -> float:
        """Absolute rupee markup above the floor."""
        return round(self.ml_fare_inr - self.floor_inr, 2)


# =============================================================================
# PRIMARY DOCUMENT: LiveFlight
# MongoDB collection: `live_flights`
# =============================================================================

# Compile once: flight_id regex  "6E-NNN_[ABC]_YYYY-MM-DD"
_FLIGHT_ID_RE = re.compile(r"^6E-\d{3}_[ABC]_\d{4}-\d{2}-\d{2}$")

# Golden Quadrilateral constraint
_GQ_AIRPORTS = frozenset({"DEL", "BOM", "CCU", "MAA"})


class LiveFlight(BaseModel):
    """
    Canonical MongoDB document for the `live_flights` collection.

    Uniqueness
    ──────────
    flight_id is the MongoDB _id — globally unique per route-slot-date.
    Pattern: "6E-<ROUTE_NUMBER>_<SLOT>_<YYYY-MM-DD>"
    Example: "6E-101_A_2026-10-16"

    Seed Volume
    ───────────
    12 routes x 3 slots x 30 days = 1,080 documents per daily run

    MongoDB Index Strategy (managed by mongo_manager.py)
    ─────────────────────────────────────────────────────
    1. UNIQUE    on  _id / flight_id           (document dedup)
    2. COMPOUND  on  (route, departure_date)   (booking engine queries)
    3. SINGLE    on  status                    (scheduled-flight filter)
    4. TTL       on  seeded_at  (90 days)      (auto-expire old cycles)
    """

    # -- Identifiers ----------------------------------------------------------
    flight_id:      str = Field(
        description='Globally unique. Format: "6E-NNN_[ABC]_YYYY-MM-DD"')
    route:          str = Field(
        description='IATA route string e.g. "DEL-BOM"')
    origin:         str = Field(min_length=3, max_length=3,
        description="IATA origin airport code — must be in the Golden Quadrilateral")
    destination:    str = Field(min_length=3, max_length=3,
        description="IATA destination code — must be in the Golden Quadrilateral")
    departure_date: str = Field(
        description="ISO-8601 date of departure YYYY-MM-DD")
    departure_time: str = Field(
        description="Scheduled departure time in IST HH:MM")
    slot:           DepartureSlot = Field(
        description="A=morning(06:00) / B=afternoon(12:30) / C=evening(18:00)")

    # -- Operational State ----------------------------------------------------
    status: FlightStatus = Field(
        default=FlightStatus.SCHEDULED,
        description="Lifecycle state — always SCHEDULED at seed time")

    # -- Core Payload Sections ------------------------------------------------
    inventory:        FlightInventory
    current_pricing:  CurrentPricing
    physics_snapshot: PhysicsSnapshot

    # -- Audit Timestamps -----------------------------------------------------
    seeded_at:    datetime = Field(
        description="UTC timestamp when daily_seeder.py created this document")
    last_updated: datetime = Field(
        description="UTC timestamp of last pricing or booking mutation")

    # =========================================================================
    # FIELD-LEVEL VALIDATORS
    # =========================================================================

    @field_validator("flight_id")
    @classmethod
    def validate_flight_id_format(cls, v: str) -> str:
        if not _FLIGHT_ID_RE.match(v):
            raise ValueError(
                f"flight_id '{v}' does not match required pattern "
                f"'6E-NNN_[ABC]_YYYY-MM-DD'. "
                f"Valid example: '6E-101_A_2026-10-16'."
            )
        return v

    @field_validator("origin", "destination")
    @classmethod
    def validate_golden_quadrilateral(cls, v: str) -> str:
        """Hard constraint: AeroSync-India operates only within the Golden Quadrilateral."""
        code = v.upper()
        if code not in _GQ_AIRPORTS:
            raise ValueError(
                f"Airport '{code}' is outside the Golden Quadrilateral. "
                f"AeroSync-India operates strictly within: {sorted(_GQ_AIRPORTS)}."
            )
        return code

    @field_validator("route")
    @classmethod
    def validate_route_format(cls, v: str) -> str:
        parts = v.upper().split("-")
        if len(parts) != 2 or not all(len(p) == 3 for p in parts):
            raise ValueError(
                f"Route '{v}' must follow 'XXX-YYY' IATA format e.g. 'DEL-BOM'."
            )
        return v.upper()

    @field_validator("departure_date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"departure_date '{v}' must be ISO-8601 format YYYY-MM-DD."
            )
        return v

    @field_validator("departure_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%H:%M")
        except ValueError:
            raise ValueError(
                f"departure_time '{v}' must be HH:MM (24-hour IST) e.g. '06:00'."
            )
        return v

    # =========================================================================
    # MODEL-LEVEL VALIDATORS
    # =========================================================================

    @model_validator(mode="after")
    def validate_route_airport_consistency(self) -> "LiveFlight":
        """route string must be identical to origin-destination pair."""
        expected = f"{self.origin}-{self.destination}"
        if self.route != expected:
            raise ValueError(
                f"Route mismatch: route='{self.route}' but "
                f"origin='{self.origin}' / destination='{self.destination}' "
                f"implies '{expected}'."
            )
        if self.origin == self.destination:
            raise ValueError(
                f"origin and destination cannot be the same airport: '{self.origin}'."
            )
        return self

    # =========================================================================
    # MONGODB SERIALISATION HELPERS
    # =========================================================================

    def to_mongo_dict(self) -> dict:
        """
        Returns a MongoDB-ready dict.
        - flight_id becomes the _id field (natural unique key, no ObjectId needed).
        - Enum values are serialised to their string primitives.
        - Datetime objects are kept as Python datetime (Motor/PyMongo handle BSON).
        """
        data = self.model_dump()
        # Promote flight_id to MongoDB _id
        data["_id"] = data.pop("flight_id")
        # Serialise enums to primitives for clean Atlas UI display
        data["status"] = self.status.value
        data["slot"]   = self.slot.value
        return data

    @classmethod
    def from_mongo_dict(cls, doc: dict) -> "LiveFlight":
        """Re-hydrate a LiveFlight Pydantic model from a raw Motor/PyMongo document."""
        doc = dict(doc)
        doc["flight_id"] = doc.pop("_id")
        return cls(**doc)
