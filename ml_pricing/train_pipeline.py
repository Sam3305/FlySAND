"""
ml_pricing/train_pipeline.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Complete XGBoost Training Pipeline  (Self-Contained)
──────────────────────────────────────────────────────────────────────────────

Fixes vs the original data_fusion.py + train_xgb.py:
  - Uses actual CSV column names (source_city, destination_city, days_left)
  - Dataset has no date_of_journey — uses days_left directly as days_to_departure
  - departure_time is categorical string, not numeric hour — mapped to buckets
  - stops is string ('zero','one','two_or_more') — mapped to int
  - Economics engine fusion skipped (would call weather API 43,000 times)
    → replaced with fast route-based cost floor estimation from our engine params
  - All in one file — no cross-module import issues

USAGE (run from C:\AeroSync-India\backend with venv active):
    python -m ml_pricing.train_pipeline

OUTPUT:
    ml_pricing/artifacts/xgb_indigo_pricing.ubj   ← trained XGBoost model
    ml_pricing/artifacts/feature_scaler.pkl        ← StandardScaler
    ml_pricing/artifacts/feature_names.json        ← feature manifest + cat vocabs
    ml_pricing/artifacts/training_report.json      ← metrics + data summary
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train_pipeline")

# ── Paths ─────────────────────────────────────────────────────────────────────
CSV_PATH       = Path("AeroSync_Raw_Data/Clean_Dataset.csv")
ARTIFACTS_DIR  = Path("ml_pricing/artifacts")
MODEL_PATH     = ARTIFACTS_DIR / "xgb_indigo_pricing.ubj"
SCALER_PATH    = ARTIFACTS_DIR / "feature_scaler.pkl"
FEATURES_PATH  = ARTIFACTS_DIR / "feature_names.json"
REPORT_PATH    = ARTIFACTS_DIR / "training_report.json"

# ── Constants ─────────────────────────────────────────────────────────────────
TARGET_AIRLINE         = "Indigo"
MARGIN_FLOOR_MULT      = 1.15
TRAIN_FRAC             = 0.80

# Golden Quadrilateral city pairs
GQ_PAIRS: set[frozenset] = {
    frozenset({"Delhi", "Mumbai"}),
    frozenset({"Delhi", "Kolkata"}),
    frozenset({"Delhi", "Chennai"}),
    frozenset({"Mumbai", "Kolkata"}),
    frozenset({"Mumbai", "Chennai"}),
    frozenset({"Kolkata", "Chennai"}),
}

# Departure time bucket → rough hour mapping for simulated cost floor
DEP_TIME_TO_HOUR: dict[str, int] = {
    "Early_Morning": 5,
    "Morning":       8,
    "Afternoon":     13,
    "Evening":       17,
    "Night":         20,
    "Late_Night":    23,
}

# Stops string → int
STOPS_MAP = {"zero": 0, "one": 1, "two_or_more": 2}

# Route distance lookup (km) for cost floor estimation
ROUTE_DISTANCES: dict[frozenset, float] = {
    frozenset({"Delhi",   "Mumbai"}):   1136,
    frozenset({"Delhi",   "Kolkata"}):  1305,
    frozenset({"Delhi",   "Chennai"}):  1753,
    frozenset({"Mumbai",  "Kolkata"}):  1660,
    frozenset({"Mumbai",  "Chennai"}):   843,
    frozenset({"Kolkata", "Chennai"}):  1370,
    frozenset({"Delhi",   "Bangalore"}):1740,
    frozenset({"Mumbai",  "Bangalore"}): 840,
    frozenset({"Delhi",   "Hyderabad"}):1253,
    frozenset({"Mumbai",  "Hyderabad"}): 620,
    frozenset({"Kolkata", "Bangalore"}):1560,
    frozenset({"Chennai", "Bangalore"}): 290,
    frozenset({"Kolkata", "Hyderabad"}): 960,
    frozenset({"Chennai", "Hyderabad"}): 510,
    frozenset({"Bangalore","Hyderabad"}):500,
}

# ATF price per kl by origin city — 2022 ERA (matches Kaggle dataset vintage)
# Real ATF prices were ~₹60,000–₹68,000/kl in 2022 before the fuel spike
ATF_PRICES: dict[str, float] = {
    "Delhi":     63000,
    "Mumbai":    60000,
    "Kolkata":   65000,
    "Chennai":   65000,
    "Bangalore": 62000,
    "Hyderabad": 63000,
}

# Numeric features (order is sacred — must match inference)
NUMERIC_FEATURES = [
    "days_to_departure",
    "dep_hour",
    "journey_month",
    "journey_dow",
    "is_weekend_travel",
    "is_morning_rush",
    "is_midday",
    "is_red_eye",
    "is_golden_quad",
    "stops_numeric",
    "duration_minutes",
    "simulated_base_cost_inr",
    "event_demand_multiplier",
]

CATEGORICAL_FEATURES = ["source_city", "destination_city", "class"]
TARGET_COL           = "price"
RATIO_TARGET         = True   # train on price/floor ratio, not absolute INR


# =============================================================================
# STEP 1 — LOAD & PURGE
# =============================================================================

def load_and_purge(path: Path) -> pd.DataFrame:
    log.info("Loading dataset from %s", path)
    df = pd.read_csv(path)
    log.info("Raw shape: %s rows × %s cols", *df.shape)

    before = len(df)
    df = df[df["airline"] == TARGET_AIRLINE].copy().reset_index(drop=True)
    log.info(
        "After IndiGo purge: %d rows kept, %d dropped",
        len(df), before - len(df),
    )
    return df


# =============================================================================
# STEP 2 — FEATURE ENGINEERING
# =============================================================================

def _estimate_base_cost(row: pd.Series) -> float:
    """
    Fast physics-inspired cost floor per seat — no weather API calls.
    Uses real route distances, ATF prices, and our economics engine constants.
    """
    origin = row["source_city"]
    dest   = row["destination_city"]
    dur_hr = float(row["duration_minutes"]) / 60.0

    # Route distance
    dist = ROUTE_DISTANCES.get(
        frozenset({origin, dest}),
        float(row["duration_minutes"]) * 12.0,  # fallback: ~12km/min
    )

    # ATF price at origin
    atf = ATF_PRICES.get(origin, 92000.0)

    # A20N baseline (186 seats, ~1989 kg/hr burn rate, 800 kg/kl density)
    # Scale by duration-derived fuel estimate
    base_burn_per_hr = 1989.0
    fuel_kg  = base_burn_per_hr * dur_hr * 1.1  # +10% for climb/descent
    fuel_cost = (fuel_kg / 800.0) * atf

    # Block-hour costs
    # 2022-era block-hour costs (pre-inflation)
    crew    = 14000 * dur_hr
    maint   = 32000 * dur_hr
    lease   = 60000 * dur_hr
    insur   =  2800 * dur_hr

    # Cycle costs (simplified domestic)
    nav      = (dist / 100.0) * math.sqrt(79.0 / 50.0) * 480
    landing  = 7882 + 175 * max(0, 79 - 45)   # A20N MTOW ~79t
    ground   = 65000
    catering = 14000
    cute     =  4500
    overfly  = 15000

    gross = fuel_cost + crew + maint + lease + insur + nav + landing + ground + catering + cute + overfly
    ask   = 186 * dist
    net   = gross - 0.40 * ask
    total = net * 1.08 + 180 * 186 * 0.856

    # Per-seat break-even + taxes
    break_even = total / (186 * 0.856)
    return round(break_even + 1500, 2)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Engineering features...")
    df = df.copy()

    # days_to_departure — dataset provides days_left directly
    df["days_to_departure"] = df["days_left"].clip(lower=0)

    # departure hour from categorical string
    df["dep_hour"] = df["departure_time"].map(DEP_TIME_TO_HOUR).fillna(12).astype(int)

    # Temporal buckets
    df["is_morning_rush"] = df["dep_hour"].between(5, 9).astype(int)
    df["is_midday"]       = df["dep_hour"].between(10, 16).astype(int)
    df["is_red_eye"]      = (~df["dep_hour"].between(5, 16)).astype(int)

    # Route features
    df["is_golden_quad"] = df.apply(
        lambda r: int(frozenset({r["source_city"], r["destination_city"]}) in GQ_PAIRS), axis=1
    )

    # Temporal features — use days_left as proxy for seasonality
    # Map days_left 1-49 to synthetic month/dow using modular arithmetic
    # (dataset doesn't have actual journey date)
    df["journey_month"] = ((df["days_left"] - 1) % 12 + 1).astype(int)
    df["journey_dow"]   = ((df["days_left"] - 1) % 7).astype(int)
    df["is_weekend_travel"] = df["journey_dow"].isin([4, 5, 6]).astype(int)

    # Stops
    df["stops_numeric"] = df["stops"].map(STOPS_MAP).fillna(1).astype(int)

    # Duration in minutes
    df["duration_minutes"] = (df["duration"] * 60).round().astype(int)

    # Simulated base cost (fast, no weather API)
    log.info("Computing simulated base costs (fast route-based estimation)...")
    df["simulated_base_cost_inr"] = df.apply(_estimate_base_cost, axis=1)

    # Demand multiplier — simplified: high for short lead times and GQ routes
    df["event_demand_multiplier"] = 1.0 + (0.3 * df["is_golden_quad"]) + \
        (0.4 * (df["days_to_departure"] <= 7).astype(float)) + \
        (0.2 * (df["days_to_departure"] <= 3).astype(float))

    # Price ratio — how much above the cost floor did IndiGo historically price?
    # This makes the model era-agnostic: it learns demand multipliers (1.1x, 2.5x)
    # rather than absolute INR values that were valid in 2022 but not 2026.
    df["price_ratio"] = df["price"] / df["simulated_base_cost_inr"].clip(lower=1)

    log.info(
        "Price ratio stats — min: %.2f  median: %.2f  max: %.2f  mean: %.2f",
        df["price_ratio"].min(), df["price_ratio"].median(),
        df["price_ratio"].max(), df["price_ratio"].mean(),
    )

    log.info("Feature engineering complete. Shape: %s", df.shape)
    return df


# =============================================================================
# STEP 3 — CHRONOLOGICAL SPLIT
# =============================================================================

def chronological_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Sort by days_left descending (far-out = past booking behaviour,
    close-in = future/test behaviour) and split at TRAIN_FRAC.
    This preserves temporal order: train on early bookings, test on close-in.
    """
    df_sorted = df.sort_values("days_left", ascending=False).reset_index(drop=True)
    cutoff    = int(len(df_sorted) * TRAIN_FRAC)
    train_df  = df_sorted.iloc[:cutoff].copy()
    val_df    = df_sorted.iloc[cutoff:].copy()

    log.info(
        "Chronological split — train: %d rows (days_left %d–%d) | val: %d rows (days_left %d–%d)",
        len(train_df), train_df["days_left"].min(), train_df["days_left"].max(),
        len(val_df),   val_df["days_left"].min(),   val_df["days_left"].max(),
    )
    return train_df, val_df


# =============================================================================
# STEP 4 — ENCODE & SCALE
# =============================================================================

def build_feature_matrix(
    df:          pd.DataFrame,
    scaler:      StandardScaler | None = None,
    fit_scaler:  bool = False,
    cat_vocabs:  dict | None = None,
    fit_vocabs:  bool = False,
) -> tuple[np.ndarray, np.ndarray, StandardScaler, dict]:

    df = df.copy()

    # Label-encode categoricals
    vocabs: dict[str, list] = {} if cat_vocabs is None else cat_vocabs
    for col in CATEGORICAL_FEATURES:
        if fit_vocabs:
            vocab       = sorted(df[col].astype(str).unique().tolist())
            vocabs[col] = vocab
        else:
            vocab = vocabs.get(col, [])
        df[col] = df[col].astype(str).map(
            lambda v, voc=vocab: voc.index(v) if v in voc else -1
        ).astype(float)

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X_raw = df[feature_cols].fillna(0).values.astype(float)

    # Use price_ratio as target (price / simulated_base_cost_inr)
    # Model learns demand multipliers, not absolute era-specific prices
    y_raw = df["price_ratio"].values.astype(float)
    y     = np.log1p(y_raw)  # log1p transform for numerical stability

    n_num = len(NUMERIC_FEATURES)
    if fit_scaler:
        scaler = StandardScaler()
        X_raw[:, :n_num] = scaler.fit_transform(X_raw[:, :n_num])
    else:
        X_raw[:, :n_num] = scaler.transform(X_raw[:, :n_num])

    return X_raw, y, scaler, vocabs


# =============================================================================
# STEP 5 — TRAIN
# =============================================================================

def train(
    X_train: np.ndarray, y_train: np.ndarray,
    X_val:   np.ndarray, y_val:   np.ndarray,
) -> xgb.XGBRegressor:

    model = xgb.XGBRegressor(
        n_estimators          = 800,
        learning_rate         = 0.05,
        max_depth             = 7,
        subsample             = 0.80,
        colsample_bytree      = 0.75,
        reg_alpha             = 0.1,
        reg_lambda            = 1.0,
        objective             = "reg:squarederror",
        eval_metric           = ["rmse", "mae"],
        early_stopping_rounds = 50,
        random_state          = 42,
        n_jobs                = -1,
        tree_method           = "hist",
        verbosity             = 1,
    )

    log.info("Training XGBoost...")
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100,
    )
    log.info("Best iteration: %d", model.best_iteration)
    return model


# =============================================================================
# STEP 6 — EVALUATE
# =============================================================================

def evaluate(
    model:  xgb.XGBRegressor,
    X_val:  np.ndarray,
    y_val:  np.ndarray,
    val_df: pd.DataFrame,
) -> dict:

    y_pred_log   = model.predict(X_val)
    y_true_ratio = np.expm1(y_val)
    y_pred_ratio = np.expm1(y_pred_log)

    # Convert ratios back to INR for interpretable metrics
    floors       = val_df["simulated_base_cost_inr"].values
    y_true_inr   = y_true_ratio * floors
    y_pred_inr   = y_pred_ratio * floors

    mae  = mean_absolute_error(y_true_inr, y_pred_inr)
    rmse = np.sqrt(mean_squared_error(y_true_inr, y_pred_inr))
    mape = float(np.mean(np.abs((y_true_inr - y_pred_inr) / np.maximum(y_true_inr, 1))) * 100)

    # Margin compliance — predicted ratio >= 1.15 (no INR floor dependency)
    compliant        = float(np.mean(y_pred_ratio >= MARGIN_FLOOR_MULT) * 100)
    ratio_mae        = float(mean_absolute_error(y_true_ratio, y_pred_ratio))
    ratio_mean       = float(y_pred_ratio.mean())

    # After enforcer
    y_enforced_inr   = np.maximum(y_pred_ratio, MARGIN_FLOOR_MULT) * floors
    mae_enforced     = mean_absolute_error(y_true_inr, y_enforced_inr)

    metrics = {
        "MAE_INR":                round(mae, 2),
        "RMSE_INR":               round(rmse, 2),
        "MAPE_pct":               round(mape, 4),
        "Ratio_MAE":              round(ratio_mae, 4),
        "Avg_predicted_ratio":    round(ratio_mean, 4),
        "Margin_Compliance_pct":  round(compliant, 2),
        "MAE_after_enforcer_INR": round(mae_enforced, 2),
        "Best_Iteration":         int(model.best_iteration),
        "Train_rows":             int(len(y_val)),
    }

    log.info("─" * 56)
    log.info("  Validation Metrics")
    log.info("─" * 56)
    for k, v in metrics.items():
        log.info("  %-30s : %s", k, v)
    log.info("─" * 56)

    return metrics


# =============================================================================
# STEP 7 — SAVE ARTIFACTS
# =============================================================================

def save_artifacts(
    model:    xgb.XGBRegressor,
    scaler:   StandardScaler,
    metrics:  dict,
    vocabs:   dict,
    train_df: pd.DataFrame,
    val_df:   pd.DataFrame,
) -> None:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    model.save_model(str(MODEL_PATH))
    log.info("Model saved   → %s", MODEL_PATH)

    joblib.dump(scaler, SCALER_PATH)
    log.info("Scaler saved  → %s", SCALER_PATH)

    feature_meta = {
        "numeric_features":     NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "all_features":         NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        "target_transform":     "log1p",
        "margin_floor_mult":    MARGIN_FLOOR_MULT,
        "cat_vocabs":           vocabs,
        "validation_metrics":   metrics,
    }
    with open(FEATURES_PATH, "w") as f:
        json.dump(feature_meta, f, indent=2)
    log.info("Features saved → %s", FEATURES_PATH)

    # Training report
    report = {
        "model": "XGBoostRegressor",
        "target": "log1p(price_inr)",
        "train_rows":  len(train_df),
        "val_rows":    len(val_df),
        "gq_train_pct": round(train_df["is_golden_quad"].mean() * 100, 1),
        "price_range_train": {
            "min": int(train_df["price"].min()),
            "max": int(train_df["price"].max()),
            "mean": int(train_df["price"].mean()),
            "median": int(train_df["price"].median()),
        },
        "metrics": metrics,
        "artifacts": {
            "model":    str(MODEL_PATH),
            "scaler":   str(SCALER_PATH),
            "features": str(FEATURES_PATH),
        },
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    log.info("Report saved  → %s", REPORT_PATH)


# =============================================================================
# PIPELINE ORCHESTRATOR
# =============================================================================

def run() -> None:
    log.info("=" * 56)
    log.info("  AeroSync-India — XGBoost Training Pipeline")
    log.info("=" * 56)

    # 1. Load
    df = load_and_purge(CSV_PATH)

    # 2. Feature engineering
    df = engineer_features(df)

    # 3. Chronological split
    train_df, val_df = chronological_split(df)

    # 4. Build feature matrices
    X_train, y_train, scaler, vocabs = build_feature_matrix(
        train_df, fit_scaler=True, fit_vocabs=True
    )
    X_val, y_val, _, _ = build_feature_matrix(
        val_df, scaler=scaler, cat_vocabs=vocabs
    )

    log.info(
        "Feature matrix — train: %s | val: %s | features: %d",
        X_train.shape, X_val.shape, X_train.shape[1],
    )

    # 5. Train
    model = train(X_train, y_train, X_val, y_val)

    # 6. Evaluate
    metrics = evaluate(model, X_val, y_val, val_df)

    # 7. Save
    save_artifacts(model, scaler, metrics, vocabs, train_df, val_df)

    log.info("=" * 56)
    log.info("  Training complete.")
    log.info("  MAE  : ₹%.0f", metrics["MAE_INR"])
    log.info("  MAPE : %.2f%%", metrics["MAPE_pct"])
    log.info("  Margin compliance: %.1f%%", metrics["Margin_Compliance_pct"])
    log.info("=" * 56)


if __name__ == "__main__":
    run()
    sys.exit(0)
