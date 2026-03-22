"""
ml_pricing/data_fusion.py
=========================
Stage 1 of the IndiGo Dynamic Pricing Pipeline.

Responsibilities
----------------
1. Load the raw Kaggle 'flight-price-prediction' CSV.
2. CRITICAL DATA PURGE  – drop every row where Airline != 'IndiGo'.
3. Feature engineering  – days_to_departure, temporal buckets, GQ flag.
4. Economics-engine fusion – call economics_engine.generate_market_fares()
   for each row and append:
       • simulated_base_cost_inr   (physical cost floor, INR)
       • event_demand_multiplier   (real-time demand scalar)
5. Persist the fused DataFrame as a Parquet artefact for the trainer.

Usage
-----
    python -m ml_pricing.data_fusion \
        --raw-csv  data/raw/Clean_Dataset.csv \
        --output   data/processed/indigo_fused.parquet \
        [--chunksize 5000]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

# ── Our existing economics engine (assumed importable) ───────────────────────
from economics_engine import generate_market_fares   # type: ignore[import]

from ml_pricing import (
    TARGET_AIRLINE,
    GOLDEN_QUAD_PAIRS,
    TEMPORAL_BUCKETS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("data_fusion")


# ─────────────────────────────────────────────────────────────────────────────
# 1.  RAW LOAD & AIRLINE PURGE
# ─────────────────────────────────────────────────────────────────────────────

def load_and_purge(csv_path: str | Path) -> pd.DataFrame:
    """
    Load the Kaggle CSV and immediately drop all non-IndiGo rows.

    Parameters
    ----------
    csv_path : path to the raw 'Clean_Dataset.csv'

    Returns
    -------
    pd.DataFrame – only IndiGo rows, raw columns preserved.

    Raises
    ------
    ValueError  if no IndiGo rows survive after the purge.
    """
    path = Path(csv_path)
    log.info("Loading raw dataset from %s", path)
    raw = pd.read_csv(path)

    original_count = len(raw)
    log.info("Raw dataset shape: %s", raw.shape)

    # ── CRITICAL DATA PURGE ───────────────────────────────────────────────────
    mask = raw["airline"].str.strip().str.lower() == TARGET_AIRLINE.lower()
    df   = raw.loc[mask].copy()
    purged = original_count - len(df)

    log.info(
        "DATA PURGE complete — kept %d IndiGo rows, dropped %d non-IndiGo rows (%.1f%%)",
        len(df), purged, 100 * purged / original_count,
    )

    if df.empty:
        raise ValueError(
            f"Zero rows remain after purging non-'{TARGET_AIRLINE}' airlines. "
            "Check that the 'airline' column name matches the dataset schema."
        )

    df = df.reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2.  DATE PARSING
# ─────────────────────────────────────────────────────────────────────────────

def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce date_of_journey and booking_date to datetime.
    The Kaggle dataset encodes journey date as a mixed DD/MM/YYYY string;
    booking_date may be synthesised or absent (defaults to 30-day prior).
    """
    df = df.copy()

    # Journey date
    df["date_of_journey"] = pd.to_datetime(
        df["date_of_journey"], dayfirst=True, errors="coerce"
    )

    # Booking date — use if present, else impute as journey - 30 days
    if "booking_date" in df.columns:
        df["booking_date"] = pd.to_datetime(
            df["booking_date"], dayfirst=True, errors="coerce"
        )
    else:
        log.warning(
            "Column 'booking_date' not found — imputing as date_of_journey - 30 days."
        )
        df["booking_date"] = df["date_of_journey"] - pd.Timedelta(days=30)

    null_journey = df["date_of_journey"].isna().sum()
    if null_journey:
        log.warning("Dropping %d rows with unparseable journey dates.", null_journey)
        df = df.dropna(subset=["date_of_journey"]).reset_index(drop=True)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3.  FEATURE ENGINEERING
# ─────────────────────────────────────────────────────────────────────────────

def _hour_to_bucket(hour: int) -> str:
    """Map a 24-h departure hour to its temporal bucket label."""
    mr_lo, mr_hi = TEMPORAL_BUCKETS["Morning_Rush"]
    md_lo, md_hi = TEMPORAL_BUCKETS["Midday"]

    if mr_lo <= hour < mr_hi:
        return "Morning_Rush"
    if md_lo <= hour < md_hi:
        return "Midday"
    return "Red_Eye"


def _is_golden_quad(source: str, destination: str) -> int:
    """Return 1 if the city-pair is on the Golden Quadrilateral trunk, else 0."""
    pair = frozenset({source.strip(), destination.strip()})
    return int(pair in GOLDEN_QUAD_PAIRS)


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive all model features from the cleaned IndiGo DataFrame.

    New columns added
    -----------------
    days_to_departure   : int  — calendar days between booking and journey
    dep_hour            : int  — departure hour (0-23) parsed from dep_time
    temporal_bucket     : str  — 'Morning_Rush' | 'Midday' | 'Red_Eye'
    is_morning_rush     : int  — one-hot for temporal_bucket
    is_midday           : int  — one-hot for temporal_bucket
    is_red_eye          : int  — one-hot for temporal_bucket
    is_golden_quad      : int  — 1 if GQ trunk route
    journey_month       : int  — month of travel (seasonality signal)
    journey_dow         : int  — day-of-week (0=Mon … 6=Sun)
    is_weekend_travel   : int  — 1 if Fri/Sat/Sun
    stops_numeric       : int  — 0 / 1 / 2+ parsed from total_stops
    duration_minutes    : int  — total_duration parsed to minutes
    """
    df = df.copy()

    # ── days_to_departure ────────────────────────────────────────────────────
    df["days_to_departure"] = (
        df["date_of_journey"] - df["booking_date"]
    ).dt.days.clip(lower=0)

    # ── Departure hour ───────────────────────────────────────────────────────
    dep_time = pd.to_datetime(df["dep_time"], format="%H:%M", errors="coerce")
    df["dep_hour"] = dep_time.dt.hour.fillna(12).astype(int)

    # ── Temporal buckets (label + one-hot) ───────────────────────────────────
    df["temporal_bucket"] = df["dep_hour"].apply(_hour_to_bucket)
    df["is_morning_rush"] = (df["temporal_bucket"] == "Morning_Rush").astype(int)
    df["is_midday"]       = (df["temporal_bucket"] == "Midday").astype(int)
    df["is_red_eye"]      = (df["temporal_bucket"] == "Red_Eye").astype(int)

    # ── Golden Quadrilateral flag ────────────────────────────────────────────
    df["is_golden_quad"] = df.apply(
        lambda r: _is_golden_quad(r["source"], r["destination"]), axis=1
    )

    # ── Temporal seasonality ─────────────────────────────────────────────────
    df["journey_month"]    = df["date_of_journey"].dt.month
    df["journey_dow"]      = df["date_of_journey"].dt.dayofweek
    df["is_weekend_travel"] = df["journey_dow"].isin([4, 5, 6]).astype(int)

    # ── Stops → numeric ──────────────────────────────────────────────────────
    stop_map = {
        "non-stop": 0, "non stop": 0,
        "1 stop": 1,
        "2 stops": 2, "3 stops": 3, "4 stops": 4,
    }
    df["stops_numeric"] = (
        df["total_stops"]
        .str.strip()
        .str.lower()
        .map(stop_map)
        .fillna(1)          # safe default: assume 1 stop if unrecognised
        .astype(int)
    )

    # ── Duration → minutes ───────────────────────────────────────────────────
    def _duration_to_minutes(s: str) -> int:
        """Parse '2h 30m', '1h', '45m' → minutes."""
        try:
            h = int(pd.Series([s]).str.extract(r"(\d+)h")[0].iloc[0] or 0)
            m = int(pd.Series([s]).str.extract(r"(\d+)m")[0].iloc[0] or 0)
            return h * 60 + m
        except Exception:
            return 90   # safe default

    df["duration_minutes"] = df["duration"].apply(_duration_to_minutes)

    log.info("Feature engineering complete. Shape: %s", df.shape)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 4.  ECONOMICS ENGINE FUSION
# ─────────────────────────────────────────────────────────────────────────────

def fuse_economics_engine(
    df: pd.DataFrame,
    chunksize: int = 1000,
) -> pd.DataFrame:
    """
    Iterate through every row of the cleaned dataset and call
    economics_engine.generate_market_fares() to obtain:

        simulated_base_cost_inr   – physical cost floor (fuel + ops)
        event_demand_multiplier   – market/event demand scalar

    The engine call is row-level to faithfully simulate real-time inference.
    Chunked iteration + progress bar prevents OOM on large datasets.

    Parameters
    ----------
    df        : feature-engineered IndiGo DataFrame
    chunksize : rows processed per engine batch (tune for your hardware)

    Returns
    -------
    pd.DataFrame with two new columns appended.
    """
    log.info(
        "Starting economics-engine fusion on %d rows (chunksize=%d)…",
        len(df), chunksize,
    )

    base_costs:   list[float] = []
    demand_mults: list[float] = []

    for i in tqdm(range(0, len(df), chunksize), desc="Fusing economics engine"):
        chunk = df.iloc[i : i + chunksize]

        for _, row in chunk.iterrows():
            # Build the market-context payload the engine expects.
            # Adjust field names to match your engine's actual API contract.
            market_context = {
                "origin":             row.get("source", "Unknown"),
                "destination":        row.get("destination", "Unknown"),
                "journey_date":       str(row.get("date_of_journey", "")),
                "days_to_departure":  int(row.get("days_to_departure", 30)),
                "stops":              int(row.get("stops_numeric", 1)),
                "duration_minutes":   int(row.get("duration_minutes", 90)),
                "is_golden_quad":     int(row.get("is_golden_quad", 0)),
                "temporal_bucket":    row.get("temporal_bucket", "Midday"),
                "flight_class":       row.get("class", "Economy"),
            }

            # ── Call the existing economics engine ───────────────────────────
            engine_output: dict = generate_market_fares(market_context)

            base_costs.append(float(engine_output["simulated_base_cost_inr"]))
            demand_mults.append(float(engine_output["event_demand_multiplier"]))

    df = df.copy()
    df["simulated_base_cost_inr"]  = base_costs
    df["event_demand_multiplier"]  = demand_mults

    log.info(
        "Fusion complete. base_cost range: ₹%.0f – ₹%.0f | demand_mult range: %.2f – %.2f",
        df["simulated_base_cost_inr"].min(), df["simulated_base_cost_inr"].max(),
        df["event_demand_multiplier"].min(), df["event_demand_multiplier"].max(),
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5.  PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def run_fusion_pipeline(
    raw_csv:   str | Path,
    output:    str | Path,
    chunksize: int = 1000,
) -> pd.DataFrame:
    """
    End-to-end fusion pipeline.

    Steps
    -----
    load_and_purge → parse_dates → engineer_features → fuse_economics_engine
    → persist Parquet

    Returns the final fused DataFrame (useful for downstream unit tests).
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    df = load_and_purge(raw_csv)
    df = parse_dates(df)
    df = engineer_features(df)
    df = fuse_economics_engine(df, chunksize=chunksize)

    df.to_parquet(output, index=False, engine="pyarrow")
    log.info("Fused dataset saved → %s  (rows=%d, cols=%d)", output, *df.shape)

    # ── Sanity assertions ────────────────────────────────────────────────────
    assert (df["airline"].str.strip().str.lower() == TARGET_AIRLINE.lower()).all(), (
        "CRITICAL: Non-IndiGo rows found in fused output!"
    )
    assert "simulated_base_cost_inr" in df.columns, "Missing base cost column."
    assert "event_demand_multiplier" in df.columns, "Missing demand multiplier column."
    assert (df["simulated_base_cost_inr"] > 0).all(),  "Non-positive base costs detected."
    assert (df["event_demand_multiplier"] > 0).all(),  "Non-positive demand multipliers detected."

    log.info("All sanity checks passed ✓")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="IndiGo data-fusion pipeline: Kaggle CSV → fused Parquet"
    )
    p.add_argument("--raw-csv",   required=True, help="Path to raw Kaggle CSV")
    p.add_argument("--output",    required=True, help="Output Parquet path")
    p.add_argument("--chunksize", type=int, default=1000,
                   help="Rows per economics-engine batch (default: 1000)")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    run_fusion_pipeline(
        raw_csv=args.raw_csv,
        output=args.output,
        chunksize=args.chunksize,
    )
    sys.exit(0)
