"""
ml_pricing/demand_model.py
──────────────────────────────────────────────────────────────────────────────
AeroSync-India  |  Market Demand Model
──────────────────────────────────────────────────────────────────────────────

PURPOSE
───────
This is NOT a pricing model. It does NOT predict what to charge.

It learns HUMAN BOOKING BEHAVIOUR from 300,153 real Indian airline bookings
across 6 airlines (Vistara, Air India, IndiGo, GoFirst, AirAsia, SpiceJet).

WHAT IT LEARNS
──────────────
Given: route + days_to_departure + time_of_day + stops + class
Predicts: willingness_to_pay_ratio = price / operating_floor

This ratio tells swarm agents: "At this context, real Indian travellers
historically paid X× the operating floor." An agent with that ratio as their
ceiling behaves like a statistically real Indian air traveller.

WHY ALL AIRLINES (not just IndiGo)
────────────────────────────────────
We are no longer simulating IndiGo. We are simulating the Indian air travel
market. Human demand elasticity is a property of the traveller, not the
airline. A budget student on DEL-BOM is equally price-sensitive whether
they're on IndiGo, SpiceJet, or GoFirst.

HOW SWARM AGENTS USE THIS
──────────────────────────
Old (hardcoded):
    if current_fare < 4500: book()  ← arbitrary, same for every route

New (data-driven):
    ratio = model.predict(route, days_left, time, stops, class)
    if current_fare <= floor * ratio: book()  ← real market behaviour

USAGE
─────
    cd C:\AeroSync-India
    python -m ml_pricing.demand_model

OUTPUT
──────
    ml_pricing/artifacts/demand_model.ubj       ← XGBoost model
    ml_pricing/artifacts/demand_scaler.pkl      ← StandardScaler
    ml_pricing/artifacts/demand_meta.json       ← feature manifest
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
log = logging.getLogger("demand_model")

# ── Paths ─────────────────────────────────────────────────────────────────────
CSV_PATH      = Path("AeroSync_Raw_Data/Clean_Dataset.csv")
ARTIFACTS_DIR = Path("ml_pricing/artifacts")
MODEL_PATH    = ARTIFACTS_DIR / "demand_model.ubj"
SCALER_PATH   = ARTIFACTS_DIR / "demand_scaler.pkl"
META_PATH     = ARTIFACTS_DIR / "demand_meta.json"

# ── Cost floor estimator (same params as economics engine) ────────────────────
ROUTE_DISTANCES = {
    frozenset({"Delhi",   "Mumbai"}):    1136,
    frozenset({"Delhi",   "Kolkata"}):   1305,
    frozenset({"Delhi",   "Chennai"}):   1753,
    frozenset({"Delhi",   "Bangalore"}): 1740,
    frozenset({"Delhi",   "Hyderabad"}): 1253,
    frozenset({"Mumbai",  "Kolkata"}):   1660,
    frozenset({"Mumbai",  "Chennai"}):    843,
    frozenset({"Mumbai",  "Bangalore"}):  840,
    frozenset({"Mumbai",  "Hyderabad"}):  620,
    frozenset({"Kolkata", "Chennai"}):   1370,
    frozenset({"Kolkata", "Bangalore"}): 1560,
    frozenset({"Kolkata", "Hyderabad"}):  960,
    frozenset({"Chennai", "Bangalore"}):  290,
    frozenset({"Chennai", "Hyderabad"}):  510,
    frozenset({"Bangalore","Hyderabad"}): 500,
}
ATF_BY_CITY = {
    "Delhi":     92323, "Mumbai":  86352,
    "Kolkata":   95378, "Chennai": 95770,
    "Bangalore": 91000, "Hyderabad": 92000,
}
GQ_PAIRS = {
    frozenset({"Delhi","Mumbai"}), frozenset({"Delhi","Kolkata"}),
    frozenset({"Delhi","Chennai"}), frozenset({"Mumbai","Kolkata"}),
    frozenset({"Mumbai","Chennai"}), frozenset({"Kolkata","Chennai"}),
}

# Inflation factor: 2022 Kaggle prices → 2026 cost level
# Inflation factor: 2022 → 2026. Bumped to 1.50x for nonstop-only model.
# ATF +46%, opex +35%, blended 1.50x. Ratio model largely inflation-immune.
INFLATION = 1.50

NUMERIC_FEATURES = [
    "days_left",
    "duration_hrs",
    # stops_numeric removed — nonstop-only dataset, always 0, no signal
    "is_economy",
    "is_golden_quad",
    "dep_hour",
    "is_morning",
    "is_evening",
    "is_night",
    "journey_dow",
    "is_weekend",
    "simulated_floor",
]
CATEGORICAL_FEATURES = ["source_city", "destination_city"]
TARGET_COL = "willingness_ratio"


# =============================================================================
# STEP 1 — LOAD (all airlines)
# =============================================================================

def load(path: Path) -> pd.DataFrame:
    log.info("Loading dataset from %s", path)
    df = pd.read_csv(path)
    log.info("Raw shape: %s", df.shape)
    log.info("Airlines: %s", df["airline"].value_counts().to_dict())

    # ── NONSTOP ONLY ──────────────────────────────────────────────────────────
    # We operate nonstop-only. Multi-stop flights have fundamentally different
    # demand behaviour (connecting itineraries, long layovers, bargain hunters)
    # that would pollute the nonstop demand signal.
    # 1-stop: ~250k rows (leisure bargain hunters, price-sensitive)
    # 2-stop: ~13k rows  (extreme budget travellers)
    # nonstop: ~36k rows (our target market — same-day direct travellers)
    before = len(df)
    df = df[df["stops"] == "zero"].copy().reset_index(drop=True)
    log.info(
        "Nonstop filter: kept %d rows, dropped %d multi-stop rows",
        len(df), before - len(df),
    )
    log.info("Nonstop by airline: %s", df["airline"].value_counts().to_dict())
    return df


# =============================================================================
# STEP 2 — FEATURE ENGINEERING
# =============================================================================

DEP_TO_HOUR = {
    "Early_Morning": 5, "Morning": 8, "Afternoon": 13,
    "Evening": 17, "Night": 20, "Late_Night": 23,
}

def _simulated_floor(row: pd.Series) -> float:
    """Fast per-route cost floor — same formula as economics engine."""
    origin = row["source_city"]
    dest   = row["destination_city"]
    dist   = ROUTE_DISTANCES.get(frozenset({origin, dest}), 1000.0)
    bh     = dist / 780.0 + 0.55
    atf    = ATF_BY_CITY.get(origin, 92000.0) * 0.97
    fuel   = (1650 * bh * 1.1 / 800) * atf
    gross  = fuel + (16000+25000+45000+2500) * bh
    gross += (dist/100) * math.sqrt(79/50) * 480 + 7882 + 175*(79-45)
    gross += 65000 + 14000 + 4500 + 15000
    pax    = 186
    net    = gross - 0.40 * pax * dist
    total  = net * 1.08 + 180 * pax * 0.856
    return total / (pax * 0.856) + 800


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    log.info("Engineering features on %d rows...", len(df))
    df = df.copy()

    # Inflate 2022 prices to 2026 cost level
    df["price"] = (df["price"] * INFLATION).round(0)

    # Simulated floor
    log.info("Computing cost floors...")
    df["simulated_floor"] = df.apply(_simulated_floor, axis=1)

    # Target: willingness ratio
    # How many times the operating floor did this traveller actually pay?
    df["willingness_ratio"] = (df["price"] / df["simulated_floor"].clip(lower=1)).clip(
        lower=0.5, upper=8.0   # sanity bounds: nobody pays <50% or >8× floor
    )

    # Duration
    df["duration_hrs"] = df["duration"].astype(float)

    # stops_numeric not computed — nonstop-only dataset

    # Class
    df["is_economy"] = (df["class"] == "Economy").astype(int)

    # Route
    df["is_golden_quad"] = df.apply(
        lambda r: int(frozenset({r["source_city"], r["destination_city"]}) in GQ_PAIRS),
        axis=1,
    )

    # Time
    df["dep_hour"] = df["departure_time"].map(DEP_TO_HOUR).fillna(12).astype(int)
    df["is_morning"] = df["dep_hour"].between(6, 9).astype(int)
    df["is_evening"] = df["dep_hour"].between(17, 20).astype(int)
    df["is_night"]   = (df["dep_hour"] >= 21).astype(int)

    # Day of week proxy
    df["journey_dow"] = df["days_left"] % 7
    df["is_weekend"]  = df["journey_dow"].isin([4, 5, 6]).astype(int)

    log.info(
        "Willingness ratio — min: %.2f  median: %.2f  mean: %.2f  max: %.2f",
        df["willingness_ratio"].min(), df["willingness_ratio"].median(),
        df["willingness_ratio"].mean(), df["willingness_ratio"].max(),
    )
    log.info(
        "By DTD bucket:\n%s",
        df.groupby(pd.cut(df["days_left"], [0,3,7,14,21,35,49]))["willingness_ratio"]
          .median().round(3).to_string()
    )
    return df


# =============================================================================
# STEP 3 — CHRONOLOGICAL SPLIT
# =============================================================================

def split(df: pd.DataFrame, train_frac: float = 0.80):
    df_s    = df.sort_values("days_left", ascending=False).reset_index(drop=True)
    cut     = int(len(df_s) * train_frac)
    return df_s.iloc[:cut].copy(), df_s.iloc[cut:].copy()


# =============================================================================
# STEP 4 — BUILD FEATURE MATRIX
# =============================================================================

def build_matrix(
    df:         pd.DataFrame,
    scaler:     StandardScaler | None = None,
    fit_scaler: bool = False,
    vocabs:     dict | None = None,
    fit_vocabs: bool = False,
):
    df = df.copy()
    vocabs = vocabs or {}

    for col in CATEGORICAL_FEATURES:
        if fit_vocabs:
            vocabs[col] = sorted(df[col].astype(str).unique().tolist())
        df[col] = df[col].astype(str).map(
            lambda v, voc=vocabs.get(col, []): voc.index(v) if v in voc else -1
        ).astype(float)

    X = df[NUMERIC_FEATURES + CATEGORICAL_FEATURES].fillna(0).values.astype(float)
    y = np.log1p(df[TARGET_COL].values.astype(float))   # log1p for stability

    n_num = len(NUMERIC_FEATURES)
    if fit_scaler:
        scaler = StandardScaler()
        X[:, :n_num] = scaler.fit_transform(X[:, :n_num])
    else:
        X[:, :n_num] = scaler.transform(X[:, :n_num])

    return X, y, scaler, vocabs


# =============================================================================
# STEP 5 — TRAIN
# =============================================================================

def train(X_tr, y_tr, X_val, y_val) -> xgb.XGBRegressor:
    model = xgb.XGBRegressor(
        n_estimators          = 600,
        learning_rate         = 0.05,
        max_depth             = 6,
        subsample             = 0.80,
        colsample_bytree      = 0.75,
        reg_alpha             = 0.1,
        reg_lambda            = 1.0,
        objective             = "reg:squarederror",
        eval_metric           = ["rmse", "mae"],
        early_stopping_rounds = 40,
        random_state          = 42,
        n_jobs                = -1,
        tree_method           = "hist",
    )
    log.info("Training demand model on %d rows...", len(y_tr))
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=100)
    log.info("Best iteration: %d", model.best_iteration)
    return model


# =============================================================================
# STEP 6 — EVALUATE
# =============================================================================

def evaluate(model, X_val, y_val, val_df) -> dict:
    y_pred_log   = model.predict(X_val)
    y_true_ratio = np.expm1(y_val)
    y_pred_ratio = np.expm1(y_pred_log)

    floors   = val_df["simulated_floor"].values
    y_true_p = y_true_ratio * floors
    y_pred_p = y_pred_ratio * floors

    mae  = mean_absolute_error(y_true_p, y_pred_p)
    rmse = np.sqrt(mean_squared_error(y_true_p, y_pred_p))
    mape = float(np.mean(np.abs((y_true_p - y_pred_p) / np.maximum(y_true_p, 1))) * 100)
    ratio_mae = float(mean_absolute_error(y_true_ratio, y_pred_ratio))

    # Per-DTD-bucket accuracy
    val_df = val_df.copy()
    val_df["pred_ratio"] = y_pred_ratio
    val_df["true_ratio"] = y_true_ratio
    bucket_acc = val_df.groupby(
        pd.cut(val_df["days_left"], [0,3,7,14,21,35,49])
    )[["true_ratio","pred_ratio"]].median().round(3)

    metrics = {
        "MAE_INR":          round(mae, 2),
        "RMSE_INR":         round(rmse, 2),
        "MAPE_pct":         round(mape, 4),
        "Ratio_MAE":        round(ratio_mae, 4),
        "Best_Iteration":   int(model.best_iteration),
        "Val_rows":         int(len(y_val)),
    }

    log.info("─" * 56)
    log.info("  Validation Metrics")
    log.info("─" * 56)
    for k, v in metrics.items():
        log.info("  %-28s : %s", k, v)
    log.info("─" * 56)
    log.info("  Per-DTD-bucket median ratio:")
    log.info("\n%s", bucket_acc.to_string())
    log.info("─" * 56)

    return metrics


# =============================================================================
# STEP 7 — SAVE
# =============================================================================

def save(model, scaler, vocabs, metrics, train_df, val_df):
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    model.save_model(str(MODEL_PATH))
    log.info("Model  → %s", MODEL_PATH)

    joblib.dump(scaler, SCALER_PATH)
    log.info("Scaler → %s", SCALER_PATH)

    meta = {
        "numeric_features":    NUMERIC_FEATURES,
        "categorical_features":CATEGORICAL_FEATURES,
        "all_features":        NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        "target":              "log1p(willingness_ratio)",
        "inflation_factor":    INFLATION,
        "cat_vocabs":          vocabs,
        "validation_metrics":  metrics,
        "train_rows":          len(train_df),
        "val_rows":            len(val_df),
        "airlines_trained_on": ["Vistara","Air_India","Indigo","GO_FIRST","AirAsia","SpiceJet"],
        "description": (
            "Predicts willingness_to_pay_ratio = price / operating_floor. "
            "Trained on all Indian airlines — captures market demand behaviour, "
            "not airline-specific pricing. Used by swarm agents to decide "
            "whether current_fare <= floor * predicted_ratio."
        ),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    log.info("Meta   → %s", META_PATH)


# =============================================================================
# PIPELINE
# =============================================================================

def run():
    log.info("=" * 56)
    log.info("  AeroSync — Market Demand Model Training")
    log.info("  All airlines | Willingness-to-pay ratios")
    log.info("=" * 56)

    df           = load(CSV_PATH)
    df           = engineer(df)
    train_df, val_df = split(df)

    X_tr, y_tr, scaler, vocabs = build_matrix(train_df, fit_scaler=True, fit_vocabs=True)
    X_val, y_val, _, _         = build_matrix(val_df, scaler=scaler, vocabs=vocabs)

    log.info("Feature matrix — train: %s | val: %s", X_tr.shape, X_val.shape)

    model   = train(X_tr, y_tr, X_val, y_val)
    metrics = evaluate(model, X_val, y_val, val_df)
    save(model, scaler, vocabs, metrics, train_df, val_df)

    log.info("=" * 56)
    log.info("  Training complete.")
    log.info("  MAE  : ₹%.0f", metrics["MAE_INR"])
    log.info("  MAPE : %.2f%%", metrics["MAPE_pct"])
    log.info("  Ratio MAE: %.4f", metrics["Ratio_MAE"])
    log.info("=" * 56)
    log.info("")
    log.info("  What this model now enables:")
    log.info("  → Swarm agents book based on real market willingness-to-pay")
    log.info("  → Budget agents reflect real D+30 price-sensitive travellers")
    log.info("  → Business agents reflect real D+1-3 inelastic travellers")
    log.info("  → Route sensitivity: DEL-BOM agents behave differently from CCU-MAA")


if __name__ == "__main__":
    run()
    sys.exit(0)
