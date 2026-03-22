"""
ml_pricing — IndiGo Dynamic Pricing Pipeline
=============================================
Modules
-------
data_fusion  : Kaggle dataset cleaner + economics-engine fuser
train_xgb    : Chronological XGBoost trainer
inference    : Hard-margin-enforced prediction wrapper
"""

# ── Shared constants ──────────────────────────────────────────────────────────

TARGET_AIRLINE = "IndiGo"

# Golden Quadrilateral trunk routes (city-pair sets, order-insensitive)
GOLDEN_QUAD_PAIRS: set[frozenset] = {
    frozenset({"Delhi", "Mumbai"}),
    frozenset({"Delhi", "Kolkata"}),
    frozenset({"Delhi", "Chennai"}),
    frozenset({"Mumbai", "Kolkata"}),
    frozenset({"Mumbai", "Chennai"}),
    frozenset({"Kolkata", "Chennai"}),
}

# Hour-of-day bucket boundaries  (24-h clock, inclusive-left / exclusive-right)
TEMPORAL_BUCKETS: dict[str, tuple[int, int]] = {
    "Morning_Rush": (5, 10),   # 05:00 – 09:59
    "Midday":       (10, 17),  # 10:00 – 16:59
    "Red_Eye":      (17, 5),   # 17:00 – 04:59  (wraps midnight)
}

MODEL_PATH      = "ml_pricing/artifacts/xgb_indigo_pricing.ubj"
SCALER_PATH     = "ml_pricing/artifacts/feature_scaler.pkl"
FEATURES_PATH   = "ml_pricing/artifacts/feature_names.json"

MARGIN_FLOOR_MULTIPLIER = 1.15   # Final_Price >= base_cost × 1.15
