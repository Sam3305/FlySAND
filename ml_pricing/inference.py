"""
ml_pricing/inference.py
=======================
Stage 3 of the IndiGo Dynamic Pricing Pipeline — Production Inference.

Responsibilities
----------------
1. Load the trained XGBoost model, StandardScaler, and feature manifest.
2. Accept a booking-context dict (mirrors data_fusion row schema).
3. Produce the raw XGBoost prediction AND the economics-engine floor.
4. Apply the HARD MARGIN ENFORCER:

        Final_Price = max(XGBoost_Prediction, simulated_base_cost_inr × 1.15)

5. Return a structured PricingDecision dataclass with full audit trail.

Design principles
-----------------
• Thread-safe: the IndigoPricingEngine is a stateless, reentrant class.
• Model artefacts are loaded once at __init__ (not per request).
• Every pricing decision is fully auditable — caller can inspect which
  branch (model or floor) was active.
• Strict typing throughout for production safety.

Usage (Python API)
------------------
    from ml_pricing.inference import IndigoPricingEngine, BookingContext

    engine = IndigoPricingEngine()          # loads model once at startup
    ctx = BookingContext(
        origin           = "Delhi",
        destination      = "Mumbai",
        journey_date     = "2025-06-15",
        booking_date     = "2025-05-01",
        dep_hour         = 8,
        stops            = 0,
        duration_minutes = 120,
        flight_class     = "Economy",
    )
    decision = engine.price(ctx)
    print(decision)

Usage (CLI / batch scoring)
---------------------------
    python -m ml_pricing.inference \
        --input  data/requests/booking_contexts.jsonl \
        --output data/results/pricing_decisions.jsonl
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import joblib
import xgboost as xgb

# ── Our existing economics engine (assumed importable) ───────────────────────
from economics_engine import generate_market_fares   # type: ignore[import]

from ml_pricing import (
    MODEL_PATH,
    SCALER_PATH,
    FEATURES_PATH,
    MARGIN_FLOOR_MULTIPLIER,
    GOLDEN_QUAD_PAIRS,
    TEMPORAL_BUCKETS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("inference")


# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN TYPES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BookingContext:
    """
    All inputs required to price a single IndiGo booking request.

    Attributes
    ----------
    origin / destination : IATA city names (must match training vocabulary)
    journey_date         : YYYY-MM-DD string or date object
    booking_date         : YYYY-MM-DD string or date object
                           (defaults to today if omitted)
    dep_hour             : departure hour 0-23 (24-h clock)
    stops                : number of stops (0, 1, 2 …)
    duration_minutes     : scheduled flight + connection time in minutes
    flight_class         : 'Economy' | 'Business'
    """
    origin:           str
    destination:      str
    journey_date:     str | date
    dep_hour:         int
    stops:            int
    duration_minutes: int
    flight_class:     str              = "Economy"
    booking_date:     str | date | None = None

    def __post_init__(self) -> None:
        # Normalise dates to date objects
        self.journey_date = _to_date(self.journey_date)
        self.booking_date = (
            _to_date(self.booking_date)
            if self.booking_date is not None
            else date.today()
        )
        # Validate hour
        if not 0 <= self.dep_hour <= 23:
            raise ValueError(f"dep_hour must be 0-23, got {self.dep_hour}.")
        # Validate class
        if self.flight_class not in {"Economy", "Business"}:
            raise ValueError(
                f"flight_class must be 'Economy' or 'Business', got '{self.flight_class}'."
            )


@dataclass
class PricingDecision:
    """
    Full auditable output of the pricing engine for one booking context.

    Attributes
    ----------
    final_price_inr          : the price to display/charge (after margin enforcer)
    xgb_raw_prediction_inr   : raw XGBoost output (before floor clamping)
    simulated_base_cost_inr  : physics-based cost floor from economics engine
    margin_floor_inr         : base_cost × MARGIN_FLOOR_MULTIPLIER
    event_demand_multiplier  : demand scalar from economics engine
    margin_enforcer_active   : True if floor clamping overrode the model
    margin_uplift_inr        : additional INR added by the floor enforcer (0 if inactive)
    """
    final_price_inr:         float
    xgb_raw_prediction_inr:  float
    simulated_base_cost_inr: float
    margin_floor_inr:        float
    event_demand_multiplier: float
    margin_enforcer_active:  bool
    margin_uplift_inr:       float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        status = "FLOOR ACTIVE ⚠" if self.margin_enforcer_active else "MODEL     ✓"
        return (
            f"PricingDecision [{status}]\n"
            f"  Final Price        : ₹{self.final_price_inr:,.0f}\n"
            f"  XGB Raw Prediction : ₹{self.xgb_raw_prediction_inr:,.0f}\n"
            f"  Base Cost Floor    : ₹{self.simulated_base_cost_inr:,.0f}\n"
            f"  Margin Floor (×{MARGIN_FLOOR_MULTIPLIER}): ₹{self.margin_floor_inr:,.0f}\n"
            f"  Demand Multiplier  : {self.event_demand_multiplier:.3f}\n"
            f"  Floor Uplift       : ₹{self.margin_uplift_inr:,.0f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _to_date(d: str | date | datetime) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date string: '{d}'")


def _hour_to_bucket(hour: int) -> str:
    mr_lo, mr_hi = TEMPORAL_BUCKETS["Morning_Rush"]
    md_lo, md_hi = TEMPORAL_BUCKETS["Midday"]
    if mr_lo <= hour < mr_hi:
        return "Morning_Rush"
    if md_lo <= hour < md_hi:
        return "Midday"
    return "Red_Eye"


def _is_golden_quad(origin: str, destination: str) -> int:
    return int(frozenset({origin.strip(), destination.strip()}) in GOLDEN_QUAD_PAIRS)


# ─────────────────────────────────────────────────────────────────────────────
# PRICING ENGINE (stateless, reentrant)
# ─────────────────────────────────────────────────────────────────────────────

class IndigoPricingEngine:
    """
    Production pricing engine for IndiGo flights.

    Thread Safety
    -------------
    The engine holds no mutable per-request state.  The XGBoost model and
    scaler are read-only after __init__, making this class safe to share
    across concurrent request handlers (e.g. FastAPI worker threads).

    Attributes (private, do not mutate)
    ------------------------------------
    _model   : xgb.XGBRegressor — loaded from .ubj artefact
    _scaler  : StandardScaler   — loaded from .pkl artefact
    _feature_meta : dict        — numeric/categorical feature name lists
    """

    def __init__(
        self,
        model_path:    str | Path = MODEL_PATH,
        scaler_path:   str | Path = SCALER_PATH,
        features_path: str | Path = FEATURES_PATH,
    ) -> None:
        log.info("Initialising IndigoPricingEngine …")

        # ── Load XGBoost booster ─────────────────────────────────────────────
        self._model = xgb.XGBRegressor()
        self._model.load_model(str(model_path))
        log.info("Model loaded from %s", model_path)

        # ── Load scaler ──────────────────────────────────────────────────────
        self._scaler: StandardScaler = joblib.load(scaler_path)
        log.info("Scaler loaded from %s", scaler_path)

        # ── Load feature manifest ────────────────────────────────────────────
        with open(features_path) as f:
            self._feature_meta: dict = json.load(f)
        self._numeric_features:     list[str] = self._feature_meta["numeric_features"]
        self._categorical_features: list[str] = self._feature_meta["categorical_features"]
        self._all_features:         list[str] = self._feature_meta["all_features"]

        # Precompute category vocabularies from training manifest (if present)
        self._cat_vocabs: dict[str, list[str]] = self._feature_meta.get("cat_vocabs", {})

        log.info(
            "IndigoPricingEngine ready. Feature count: %d (%d numeric, %d categorical)",
            len(self._all_features),
            len(self._numeric_features),
            len(self._categorical_features),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def price(self, ctx: BookingContext) -> PricingDecision:
        """
        Price a single booking context.

        Pipeline
        --------
        1. Derive features from BookingContext.
        2. Call economics_engine.generate_market_fares() for the cost floor.
        3. Build feature vector and run XGBoost inference.
        4. Apply hard margin enforcer.
        5. Return PricingDecision with full audit trail.

        Parameters
        ----------
        ctx : BookingContext — validated booking inputs

        Returns
        -------
        PricingDecision — includes final price, raw prediction, and floor details.
        """
        # ── Step 1: derive features ──────────────────────────────────────────
        features = self._derive_features(ctx)

        # ── Step 2: call economics engine ────────────────────────────────────
        market_context = {
            "origin":            ctx.origin,
            "destination":       ctx.destination,
            "journey_date":      ctx.journey_date.isoformat(),
            "days_to_departure": features["days_to_departure"],
            "stops":             ctx.stops,
            "duration_minutes":  ctx.duration_minutes,
            "is_golden_quad":    features["is_golden_quad"],
            "temporal_bucket":   features["temporal_bucket"],
            "flight_class":      ctx.flight_class,
        }
        engine_out: dict = generate_market_fares(market_context)

        base_cost_inr:      float = float(engine_out["simulated_base_cost_inr"])
        demand_multiplier:  float = float(engine_out["event_demand_multiplier"])

        # ── Step 3: build feature vector and predict ─────────────────────────
        feature_row = self._build_feature_vector(features, base_cost_inr, demand_multiplier)
        xgb_log_pred: float = float(self._model.predict(feature_row)[0])
        xgb_price_inr: float = float(np.expm1(xgb_log_pred))

        # ── Step 4: HARD MARGIN ENFORCER ─────────────────────────────────────
        #
        #   Final_Price = max(XGBoost_Prediction, simulated_base_cost_inr × 1.15)
        #
        margin_floor_inr: float = base_cost_inr * MARGIN_FLOOR_MULTIPLIER
        enforcer_active:  bool  = xgb_price_inr < margin_floor_inr
        final_price_inr:  float = max(xgb_price_inr, margin_floor_inr)
        uplift_inr:       float = final_price_inr - xgb_price_inr   # ≥ 0

        decision = PricingDecision(
            final_price_inr         = round(final_price_inr, 2),
            xgb_raw_prediction_inr  = round(xgb_price_inr, 2),
            simulated_base_cost_inr = round(base_cost_inr, 2),
            margin_floor_inr        = round(margin_floor_inr, 2),
            event_demand_multiplier = round(demand_multiplier, 4),
            margin_enforcer_active  = enforcer_active,
            margin_uplift_inr       = round(uplift_inr, 2),
        )

        log.debug("Pricing decision: %s", decision)
        return decision

    def batch_price(
        self, contexts: list[BookingContext]
    ) -> list[PricingDecision]:
        """Price a list of booking contexts. Returns decisions in same order."""
        return [self.price(ctx) for ctx in contexts]

    # ── Private helpers ───────────────────────────────────────────────────────

    def _derive_features(self, ctx: BookingContext) -> dict[str, Any]:
        """Compute all derived fields from a BookingContext."""
        days_to_dep  = max(0, (ctx.journey_date - ctx.booking_date).days)
        bucket       = _hour_to_bucket(ctx.dep_hour)
        is_gq        = _is_golden_quad(ctx.origin, ctx.destination)
        journey_dt   = datetime(ctx.journey_date.year, ctx.journey_date.month, ctx.journey_date.day)
        dow          = journey_dt.weekday()

        return {
            "days_to_departure": days_to_dep,
            "dep_hour":          ctx.dep_hour,
            "journey_month":     ctx.journey_date.month,
            "journey_dow":       dow,
            "is_weekend_travel": int(dow in {4, 5, 6}),
            "is_morning_rush":   int(bucket == "Morning_Rush"),
            "is_midday":         int(bucket == "Midday"),
            "is_red_eye":        int(bucket == "Red_Eye"),
            "is_golden_quad":    is_gq,
            "stops_numeric":     ctx.stops,
            "duration_minutes":  ctx.duration_minutes,
            "temporal_bucket":   bucket,
            # Categoricals (label-encoded to int)
            "source":            self._encode_cat("source", ctx.origin),
            "destination":       self._encode_cat("destination", ctx.destination),
            "class":             self._encode_cat("class", ctx.flight_class),
        }

    def _encode_cat(self, col: str, value: str) -> int:
        """
        Encode a categorical value to the integer code used during training.
        Falls back to -1 (unseen category) if vocabulary is unavailable.
        """
        vocab = self._cat_vocabs.get(col)
        if vocab is None:
            # Vocabulary not stored — use a deterministic hash-based fallback
            # that is consistent across calls for the same value.
            return hash(value) % 1000
        try:
            return vocab.index(value)
        except ValueError:
            log.warning("Unseen category '%s' for column '%s'. Encoding as -1.", value, col)
            return -1

    def _build_feature_vector(
        self,
        features:         dict[str, Any],
        base_cost_inr:    float,
        demand_multiplier:float,
    ) -> np.ndarray:
        """
        Assemble, scale, and return the feature vector as a (1, n_features) array.
        """
        # Numeric features (order must match training NUMERIC_FEATURES list)
        numeric_vals = [
            features["days_to_departure"],
            features["dep_hour"],
            features["journey_month"],
            features["journey_dow"],
            features["is_weekend_travel"],
            features["is_morning_rush"],
            features["is_midday"],
            features["is_red_eye"],
            features["is_golden_quad"],
            features["stops_numeric"],
            features["duration_minutes"],
            base_cost_inr,
            demand_multiplier,
        ]

        # Categorical features (already integer-encoded)
        cat_vals = [
            features["source"],
            features["destination"],
            features["class"],
        ]

        row = np.array(numeric_vals + cat_vals, dtype=float).reshape(1, -1)

        # Scale numeric block (same slice as in training)
        n_num = len(self._numeric_features)
        row[0, :n_num] = self._scaler.transform(row[:, :n_num])[0]

        return row


# ─────────────────────────────────────────────────────────────────────────────
# CLI — BATCH JSONL SCORING
# ─────────────────────────────────────────────────────────────────────────────

def _run_batch_cli(input_path: str, output_path: str) -> None:
    """
    Read BookingContext dicts from a JSONL file, score each, and write
    PricingDecision dicts to an output JSONL file.

    Input format (one JSON object per line)
    ----------------------------------------
    {"origin": "Delhi", "destination": "Mumbai", "journey_date": "2025-06-15",
     "booking_date": "2025-05-01", "dep_hour": 8, "stops": 0,
     "duration_minutes": 120, "flight_class": "Economy"}
    """
    engine = IndigoPricingEngine()

    in_path  = Path(input_path)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    errors:  int = 0

    with open(in_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    log.info("Scoring %d booking contexts from %s", len(lines), in_path)

    for i, line in enumerate(lines):
        try:
            raw = json.loads(line)
            ctx = BookingContext(**raw)
            decision = engine.price(ctx)
            results.append({"input": raw, "decision": decision.to_dict()})
        except Exception as exc:
            log.error("Row %d failed: %s — %s", i, line[:80], exc)
            results.append({"input": raw if "raw" in dir() else {}, "error": str(exc)})
            errors += 1

    with open(out_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    log.info(
        "Batch scoring complete. Success: %d | Errors: %d → %s",
        len(results) - errors, errors, out_path,
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(
        description="Batch-score BookingContext JSONL with IndigoPricingEngine"
    )
    p.add_argument("--input",  required=True, help="Input JSONL path")
    p.add_argument("--output", required=True, help="Output JSONL path")
    args = p.parse_args()

    _run_batch_cli(args.input, args.output)
    sys.exit(0)
