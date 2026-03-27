"""
app/engines/ml_pricing_model.py  — XGBoost inference + heuristic fallback
"""
from __future__ import annotations
import json, logging, math
from pathlib import Path
import numpy as np

logger = logging.getLogger("orchestrator.ml")

_REPO_ROOT    = Path(__file__).resolve().parent.parent.parent.parent
_MODEL_PATH   = _REPO_ROOT / "ml_pricing" / "artifacts" / "xgb_indigo_pricing.ubj"
_SCALER_PATH  = _REPO_ROOT / "ml_pricing" / "artifacts" / "feature_scaler.pkl"
_FEAT_PATH    = _REPO_ROOT / "ml_pricing" / "artifacts" / "feature_names.json"
MARGIN_FLOOR  = 1.02

_model = _scaler = _meta = None
_loaded = _tried = False

_NUMERIC = [
    "days_to_departure","dep_hour","booking_window_bucket","likely_weekend",
    "is_morning_rush","is_midday","is_red_eye","is_golden_quad",
    "stops_numeric","duration_minutes","simulated_base_cost_inr","event_demand_multiplier",
]
_DEP_HR = {"A":6,"B":12,"C":18}

def _load():
    global _model,_scaler,_meta,_loaded,_tried
    if _tried: return _loaded
    _tried = True
    if not _MODEL_PATH.exists():
        logger.warning("XGBoost model not found — run: python -m ml_pricing.train_model  (using heuristic)")
        return False
    try:
        import xgboost as xgb, joblib
        _model = xgb.XGBRegressor(); _model.load_model(str(_MODEL_PATH))
        _scaler = joblib.load(str(_SCALER_PATH))
        with open(_FEAT_PATH) as f: _meta = json.load(f)
        _loaded = True
        m = (_meta.get("validation_metrics") or {})
        logger.info("XGBoost model loaded — MAE=₹%s  MAPE=%.1f%%  Compliance=%.1f%%",
                    m.get("MAE_INR","?"), m.get("MAPE_pct",0), m.get("Margin_Compliance_pct",0))
        return True
    except Exception as e:
        logger.error("Model load failed: %s", e); return False

def _vec(floor_price, seats_available, total_seats, severity, days_to_flight, flight_id):
    parts   = (flight_id or "").split("_")
    slot    = parts[1] if len(parts)>=2 else "B"
    dep_hr  = _DEP_HR.get(slot,12)
    numeric = [
        days_to_flight, dep_hr,
        min(int(days_to_flight/10),4),
        int(dep_hr>=17),
        int(5<=dep_hr<=9), int(10<=dep_hr<=16), int(not 5<=dep_hr<=16),
        1, 0, 130,
        floor_price, 1.0 + severity*0.5,
    ]
    row = np.array(numeric + [0,1,0], dtype=float).reshape(1,-1)
    row[0,:len(_NUMERIC)] = _scaler.transform(row[:,:len(_NUMERIC)])[0]
    return row

def predict_price(
    *,
    flight_id:       str,
    floor_price:     float,
    seats_available: int,
    total_seats:     int,
    severity:        float,
    days_to_flight:  int   = 15,
    current_price:   float = 0.0,
) -> float:
    """
    Apply a weather disruption premium to the current seeded price.

    The seeder already priced flights correctly via the calibrated
    economics engine (floor x DOW multiplier). This function adds
    a WEATHER PREMIUM on top — it does NOT reprice from scratch.

    Premium caps: severity=0.5 -> ~10%, severity=1.0 -> ~25% max.
    """
    base = current_price if current_price > floor_price else floor_price
    lf   = max(0.0, min(1.0, 1.0 - seats_available / max(total_seats, 1)))

    if _load():
        try:
            v         = _vec(floor_price, seats_available, total_seats,
                             severity, days_to_flight, flight_id)
            ml_ratio  = float(np.expm1(_model.predict(v)[0]))
            weather_p = min(max(0.0, ml_ratio - 1.0) * severity, 0.25)
            logger.debug("XGB weather — flight=%s ml_ratio=%.3f sev=%.2f premium=+%.1f%%",
                         flight_id, ml_ratio, severity, weather_p * 100)
        except Exception as e:
            logger.warning("XGB inference error %s: %s — heuristic", flight_id, e)
            weather_p = min(severity * 0.18 + lf * severity * 0.10, 0.25)
    else:
        weather_p = min(severity * 0.18 + lf * severity * 0.10, 0.25)

    final = max(base * (1.0 + weather_p), floor_price * MARGIN_FLOOR)
    return round(final, 2)