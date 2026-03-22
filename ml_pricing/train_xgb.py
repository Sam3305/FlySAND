"""
ml_pricing/train_xgb.py
=======================
Stage 2 of the IndiGo Dynamic Pricing Pipeline.

Responsibilities
----------------
1. Load the fused Parquet produced by data_fusion.py.
2. Build the full feature matrix (model features + engine outputs).
3. Perform a STRICT CHRONOLOGICAL split — no random splits ever.
   Train on the earliest N% of journey dates; validate on the tail.
4. Train an XGBoostRegressor with early stopping on the validation fold.
5. Evaluate with MAE, RMSE, MAPE, and a margin-compliance rate.
6. Persist the trained booster, StandardScaler, and feature name list.

Usage
-----
    python -m ml_pricing.train_xgb \
        --fused-parquet data/processed/indigo_fused.parquet \
        [--train-frac 0.80] \
        [--n-estimators 1000] \
        [--learning-rate 0.05]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.preprocessing import StandardScaler
import joblib
import xgboost as xgb

from ml_pricing import MODEL_PATH, SCALER_PATH, FEATURES_PATH, MARGIN_FLOOR_MULTIPLIER

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("train_xgb")


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE CATALOGUE
# ─────────────────────────────────────────────────────────────────────────────

# Numeric features fed directly to XGBoost
NUMERIC_FEATURES: list[str] = [
    # Temporal
    "days_to_departure",
    "dep_hour",
    "journey_month",
    "journey_dow",
    "is_weekend_travel",
    # Temporal bucket one-hots
    "is_morning_rush",
    "is_midday",
    "is_red_eye",
    # Route
    "is_golden_quad",
    # Operational
    "stops_numeric",
    "duration_minutes",
    # Economics engine outputs (physical priors)
    "simulated_base_cost_inr",
    "event_demand_multiplier",
]

# Categorical features — label-encoded then passed as XGBoost categoricals
CATEGORICAL_FEATURES: list[str] = [
    "source",
    "destination",
    "class",         # Economy / Business
]

TARGET_COL     = "price"        # historical fare (INR) — training target
DATE_SORT_COL  = "date_of_journey"


# ─────────────────────────────────────────────────────────────────────────────
# 1.  DATA LOADING & VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

def load_fused(parquet_path: str | Path) -> pd.DataFrame:
    path = Path(parquet_path)
    log.info("Loading fused dataset from %s", path)
    df = pd.read_parquet(path)
    log.info("Loaded shape: %s", df.shape)

    required = set(NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET_COL, DATE_SORT_COL])
    missing  = required - set(df.columns)
    if missing:
        # Normalise column name case
        df.columns = df.columns.str.lower().str.strip()
        missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing required columns in fused Parquet: {missing}")

    # Drop rows with null targets or date
    before = len(df)
    df = df.dropna(subset=[TARGET_COL, DATE_SORT_COL]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        log.warning("Dropped %d rows with null target/date.", dropped)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2.  STRICT CHRONOLOGICAL SPLIT
# ─────────────────────────────────────────────────────────────────────────────

def chronological_split(
    df: pd.DataFrame,
    train_frac: float = 0.80,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Sort rows by DATE_SORT_COL and cut at train_frac.

    CRITICAL DESIGN NOTE
    --------------------
    We sort by the actual journey date (not a random index) so that the
    validation fold only ever contains future observations relative to every
    training sample. This prevents temporal leakage — a common mistake when
    sklearn's train_test_split(shuffle=True) is used on time series data.

    Parameters
    ----------
    df          : full fused DataFrame
    train_frac  : fraction of EARLIEST dates to use for training [0.5, 0.95]

    Returns
    -------
    (train_df, val_df) — both DataFrames retain all original columns.
    """
    if not 0.5 <= train_frac <= 0.95:
        raise ValueError(f"train_frac must be in [0.5, 0.95], got {train_frac}.")

    df_sorted = df.sort_values(DATE_SORT_COL).reset_index(drop=True)
    cutoff_idx = int(len(df_sorted) * train_frac)

    train_df = df_sorted.iloc[:cutoff_idx].copy()
    val_df   = df_sorted.iloc[cutoff_idx:].copy()

    cutoff_date = df_sorted[DATE_SORT_COL].iloc[cutoff_idx]
    log.info(
        "Chronological split — train: %d rows (up to %s) | val: %d rows (from %s)",
        len(train_df), train_df[DATE_SORT_COL].max().date(),
        len(val_df),   cutoff_date.date(),
    )

    # Assert zero leakage
    assert train_df[DATE_SORT_COL].max() <= val_df[DATE_SORT_COL].min(), (
        "TEMPORAL LEAKAGE DETECTED: training set contains dates after validation set start!"
    )

    return train_df, val_df


# ─────────────────────────────────────────────────────────────────────────────
# 3.  FEATURE MATRIX BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_feature_matrix(
    df: pd.DataFrame,
    scaler: StandardScaler | None = None,
    fit_scaler: bool = False,
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    """
    Build (X, y) arrays from the fused DataFrame.

    Categorical columns are integer label-encoded.
    Numeric columns are StandardScaled (fit only on train; transform on val).

    Returns
    -------
    X        : np.ndarray of shape (n_samples, n_features)
    y        : np.ndarray of shape (n_samples,) — log1p-transformed price
    scaler   : fitted StandardScaler (returned even if pre-fitted was passed in)
    """
    df = df.copy()

    # ── Label-encode categoricals ────────────────────────────────────────────
    for col in CATEGORICAL_FEATURES:
        df[col] = pd.Categorical(df[col]).codes.astype(float)

    feature_cols = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    X_raw = df[feature_cols].fillna(0).values.astype(float)
    y_raw = df[TARGET_COL].values.astype(float)

    # ── Log1p-transform target (reduces skew, improves RMSE optimisation) ───
    y = np.log1p(y_raw)

    # ── Scale numeric block only ─────────────────────────────────────────────
    n_numeric = len(NUMERIC_FEATURES)
    if fit_scaler:
        scaler = StandardScaler()
        X_raw[:, :n_numeric] = scaler.fit_transform(X_raw[:, :n_numeric])
    else:
        if scaler is None:
            raise ValueError("A fitted scaler must be provided when fit_scaler=False.")
        X_raw[:, :n_numeric] = scaler.transform(X_raw[:, :n_numeric])

    return X_raw, y, scaler


# ─────────────────────────────────────────────────────────────────────────────
# 4.  MODEL TRAINING
# ─────────────────────────────────────────────────────────────────────────────

def train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val:   np.ndarray,
    y_val:   np.ndarray,
    n_estimators:  int   = 1000,
    learning_rate: float = 0.05,
    max_depth:     int   = 7,
    subsample:     float = 0.80,
    colsample:     float = 0.75,
    reg_alpha:     float = 0.1,
    reg_lambda:    float = 1.0,
    early_stop:    int   = 50,
) -> xgb.XGBRegressor:
    """
    Train an XGBoost regressor with early stopping on the validation fold.

    Hyperparameter rationale
    ------------------------
    • max_depth=7       — captures non-linear route × time interactions
    • subsample=0.80    — row-level bagging reduces variance on sparse routes
    • colsample=0.75    — prevents over-reliance on simulated_base_cost_inr
    • reg_alpha=0.1     — L1 sparsity; prunes irrelevant temporal features
    • early_stop=50     — aborts if no val improvement for 50 rounds
    """
    model = xgb.XGBRegressor(
        n_estimators      = n_estimators,
        learning_rate     = learning_rate,
        max_depth         = max_depth,
        subsample         = subsample,
        colsample_bytree  = colsample,
        reg_alpha         = reg_alpha,
        reg_lambda        = reg_lambda,
        objective         = "reg:squarederror",
        eval_metric       = ["rmse", "mae"],
        early_stopping_rounds = early_stop,
        random_state      = 42,
        n_jobs            = -1,
        tree_method       = "hist",   # CPU-efficient histogram algorithm
    )

    log.info(
        "Training XGBoost | n_estimators=%d | lr=%.3f | max_depth=%d",
        n_estimators, learning_rate, max_depth,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=100,
    )

    best = model.best_iteration
    log.info("Early stopping — best iteration: %d", best)
    return model


# ─────────────────────────────────────────────────────────────────────────────
# 5.  EVALUATION
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(
    model:   xgb.XGBRegressor,
    X_val:   np.ndarray,
    y_val:   np.ndarray,
    val_df:  pd.DataFrame,
) -> dict[str, float]:
    """
    Compute MAE, RMSE, MAPE, and the margin-compliance rate on the val fold.

    Margin Compliance Rate
    ----------------------
    Fraction of predictions where:
        expm1(y_hat) >= simulated_base_cost_inr * MARGIN_FLOOR_MULTIPLIER
    This directly measures how often the raw XGBoost prediction already
    satisfies the hard margin constraint (before the enforcer clamps it).
    """
    y_pred_log = model.predict(X_val)

    # Inverse log1p transform back to INR
    y_true_inr = np.expm1(y_val)
    y_pred_inr = np.expm1(y_pred_log)

    mae  = mean_absolute_error(y_true_inr, y_pred_inr)
    rmse = np.sqrt(mean_squared_error(y_true_inr, y_pred_inr))
    mape = np.mean(np.abs((y_true_inr - y_pred_inr) / np.maximum(y_true_inr, 1))) * 100

    # Margin compliance check
    floor = val_df["simulated_base_cost_inr"].values * MARGIN_FLOOR_MULTIPLIER
    compliant = np.mean(y_pred_inr >= floor) * 100

    metrics = {
        "MAE_INR":              round(mae, 2),
        "RMSE_INR":             round(rmse, 2),
        "MAPE_pct":             round(mape, 4),
        "Margin_Compliance_pct": round(compliant, 2),
        "Best_Iteration":       int(model.best_iteration),
    }

    log.info("── Validation Metrics ──────────────────────────────────")
    for k, v in metrics.items():
        log.info("  %-28s : %s", k, v)
    log.info("────────────────────────────────────────────────────────")

    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# 6.  PERSISTENCE
# ─────────────────────────────────────────────────────────────────────────────

def save_artefacts(
    model:        xgb.XGBRegressor,
    scaler:       StandardScaler,
    metrics:      dict,
    model_path:   str | Path = MODEL_PATH,
    scaler_path:  str | Path = SCALER_PATH,
    features_path:str | Path = FEATURES_PATH,
) -> None:
    for p in [model_path, scaler_path, features_path]:
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    # XGBoost native binary format (fastest load, version-stable)
    model.save_model(str(model_path))
    log.info("Model saved → %s", model_path)

    joblib.dump(scaler, scaler_path)
    log.info("Scaler saved → %s", scaler_path)

    feature_meta = {
        "numeric_features":     NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "all_features":         NUMERIC_FEATURES + CATEGORICAL_FEATURES,
        "target_transform":     "log1p",
        "validation_metrics":   metrics,
    }
    with open(features_path, "w") as f:
        json.dump(feature_meta, f, indent=2)
    log.info("Feature manifest saved → %s", features_path)


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_training_pipeline(
    fused_parquet:  str | Path,
    train_frac:     float = 0.80,
    n_estimators:   int   = 1000,
    learning_rate:  float = 0.05,
) -> tuple[xgb.XGBRegressor, StandardScaler, dict]:
    """
    End-to-end training pipeline.

    Steps
    -----
    load → chronological_split → build_feature_matrix
    → train_xgboost (with early stopping) → evaluate → save_artefacts

    Returns
    -------
    (model, scaler, validation_metrics) — useful for notebooks / tests.
    """
    df = load_fused(fused_parquet)

    train_df, val_df = chronological_split(df, train_frac=train_frac)

    X_train, y_train, scaler = build_feature_matrix(
        train_df, fit_scaler=True
    )
    X_val, y_val, _ = build_feature_matrix(
        val_df, scaler=scaler, fit_scaler=False
    )

    model = train_xgboost(
        X_train, y_train,
        X_val,   y_val,
        n_estimators=n_estimators,
        learning_rate=learning_rate,
    )

    metrics = evaluate(model, X_val, y_val, val_df)

    save_artefacts(model, scaler, metrics)

    return model, scaler, metrics


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Train IndiGo XGBoost pricing model (chronological split)"
    )
    p.add_argument("--fused-parquet", required=True)
    p.add_argument("--train-frac",    type=float, default=0.80,
                   help="Fraction of earliest journey dates for training")
    p.add_argument("--n-estimators",  type=int,   default=1000)
    p.add_argument("--learning-rate", type=float, default=0.05)
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run_training_pipeline(
        fused_parquet = args.fused_parquet,
        train_frac    = args.train_frac,
        n_estimators  = args.n_estimators,
        learning_rate = args.learning_rate,
    )
    sys.exit(0)
