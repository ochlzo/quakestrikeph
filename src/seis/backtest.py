"""Backtest the deployed SEIS ensemble end-to-end on the Path B target schema.

The ensemble serves ONE model per target -- the per-target winner recorded in
``HYBRID_MODEL_MAPPING`` in ``src/seis/predict.py`` (assembled from the 2025
backtest into ``src/outputs/seis/backtest_pick_report.json``). This script loads
exactly that ensemble, rebuilds each event's features through the production
inference path (the shared ``feature_engineering`` module), scores every target
with its chosen family, and reports the ensemble's metrics.

It evaluates two years and writes a single combined metrics file:

- **2026** -- the true out-of-sample holdout. The models never trained on it, it
  was not the early-stopping validation year, and the per-target selection did not
  use it. This is the honest deployment estimate (note: a partial year, so smaller
  n / noisier per-target metrics).
- **2025** -- in-sample with respect to selection. It was both the early-stopping
  validation year AND the year the per-target winners were chosen on, so these
  numbers are an optimistic ceiling, not a holdout. Kept for the apples-to-apples
  comparison against the per-family pick report.

Output (Option A -- one JSON keyed by year, per-year prediction CSVs):

    src/outputs/seis/backtests_mc_1_0/backtest_metrics.json   # {"2025": {...}, "2026": {...}}
    src/outputs/seis/backtests_mc_1_0/backtest_predictions_2025.csv
    src/outputs/seis/backtests_mc_1_0/backtest_predictions_2026.csv
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Shared feature engineering (single source of truth for the production path).
SHARED_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from feature_engineering import (  # noqa: E402
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    build_prediction_features,
    filter_history_for_prediction,
    load_feature_columns,
    normalize_raw_catalog,
)

# The deployed ensemble definition + loaders live in predict.py, so the backtest
# scores exactly what predict.py serves.
SEIS_DIR = Path(__file__).resolve().parent
if str(SEIS_DIR) not in sys.path:
    sys.path.insert(0, str(SEIS_DIR))

from predict import (  # noqa: E402
    CLASSIFICATION_TARGETS,
    DEFAULT_CB_DIR,
    DEFAULT_FEATURE_COLUMNS,
    DEFAULT_LGB_DIR,
    DEFAULT_RF_DIR,
    DEFAULT_XGB_DIR,
    HYBRID_MODEL_MAPPING,
    LOG_DISTANCE_TARGETS,
    REGRESSION_TARGETS,
    load_all_hybrid_models,
    require_dependencies,
)

# Serving inference + the verified backtest metric helpers both live in the
# lightgbm package (the repo's serving/backtest base). Reuse them so the ensemble
# backtest produces metrics identical in shape to the single-family backtests.
LIGHTGBM_DIR = SEIS_DIR.parent / "lightgbm"
if str(LIGHTGBM_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_DIR))

from predict_aftershock import run_predictions  # noqa: E402
from backtest_aftershock_predictions import (  # noqa: E402
    DEFAULT_INPUT_CSV,
    build_prediction_record,
    load_labeled_events,
    require_backtest_dependencies,
    row_to_event,
    sample_events,
    summarize_records,
)

DEFAULT_BACKTEST_OUTPUT_DIR = Path("src/outputs/seis/backtests_mc_1_0")

# Honesty labels per evaluation year (see module docstring).
YEAR_HOLDOUT_STATUS = {
    2025: "in_sample_wrt_selection (early-stopping validation year AND per-target "
    "selection year -- optimistic ceiling, not a holdout)",
    2026: "out_of_sample_holdout (never trained on, not the validation year, not "
    "used for selection -- honest deployment estimate; partial year)",
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--xgb-models-dir", type=Path, default=DEFAULT_XGB_DIR)
    parser.add_argument("--lgb-models-dir", type=Path, default=DEFAULT_LGB_DIR)
    parser.add_argument("--rf-models-dir", type=Path, default=DEFAULT_RF_DIR)
    parser.add_argument("--cb-models-dir", type=Path, default=DEFAULT_CB_DIR)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKTEST_OUTPUT_DIR)
    parser.add_argument(
        "--years",
        default="2025,2026",
        help="Comma-separated evaluation years; each is backtested in isolation "
        "(test_start_year == test_end_year == year).",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Maximum labeled events per year. 0 = the whole year's pool (honest).",
    )
    parser.add_argument(
        "--sample-mode",
        choices=["balanced", "chronological"],
        default="chronological",
        help="chronological keeps natural deployment prevalence; balanced distorts it.",
    )
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--fractal-dimension", type=float, default=DEFAULT_FRACTAL_DIMENSION)
    parser.add_argument("--log10-eta0", type=float, default=DEFAULT_LOG10_ETA0)
    return parser.parse_args()


def backtest_year(year, args, models, history, feature_columns, metric_deps):
    """Run the ensemble over one year's labeled pool; return (summary, records)."""
    labeled = load_labeled_events(
        args.labeled_csv, year, year, args.minimum_magnitude
    )
    sampled = sample_events(
        labeled, args.max_events, args.sample_mode, args.random_seed
    ).reset_index(drop=True)
    print(f"  [{year}] pool: {len(sampled)} events "
          f"(prevalence-preserving '{args.sample_mode}').", flush=True)

    records = []
    for index, row in sampled.iterrows():
        event = row_to_event(row)
        prediction_history = filter_history_for_prediction(
            history, event["event_time"], args.minimum_magnitude
        )
        feature_row = build_prediction_features(
            prediction_history, event, args, feature_columns
        )
        classification, regression = run_predictions(
            feature_row,
            models,
            CLASSIFICATION_TARGETS,
            REGRESSION_TARGETS,
            LOG_DISTANCE_TARGETS,
        )
        records.append(
            build_prediction_record(
                row, classification, regression, len(prediction_history)
            )
        )
        if (index + 1) % 1000 == 0:
            print(f"  [{year}] scored {index + 1}/{len(sampled)}...", flush=True)

    summary = {
        "config": {
            "model_family": "seis_ensemble",
            "evaluation_year": year,
            "holdout_status": YEAR_HOLDOUT_STATUS.get(year, "unknown"),
            "model_selection": dict(HYBRID_MODEL_MAPPING),
            "labeled_csv": str(args.labeled_csv),
            "historical_csv": str(args.historical_csv),
            "evaluation_rows": int(len(sampled)),
            "candidate_rows": int(len(labeled)),
            "max_events": args.max_events,
            "sample_mode": args.sample_mode,
            "minimum_magnitude": args.minimum_magnitude,
        },
        "metrics": summarize_records(records, metric_deps),
    }
    return summary, records


def main():
    args = parse_args()
    deps = require_dependencies()
    metric_deps = require_backtest_dependencies()
    feature_columns = load_feature_columns(args.feature_columns)
    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]

    print("Loading deployed ensemble (one model per target):", flush=True)
    for target, family in HYBRID_MODEL_MAPPING.items():
        print(f"  {target:<34} -> {family}", flush=True)
    models = load_all_hybrid_models(args, deps)

    print("Loading historical catalog...", flush=True)
    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    combined = {}
    for year in years:
        print(f"Backtesting {year}...", flush=True)
        try:
            summary, records = backtest_year(
                year, args, models, history, feature_columns, metric_deps
            )
        except ValueError as error:
            # e.g. a year with no labeled events matching the filters.
            print(f"  [{year}] skipped: {error}", flush=True)
            combined[str(year)] = {"error": str(error)}
            continue
        combined[str(year)] = summary
        predictions_path = args.output_dir / f"backtest_predictions_{year}.csv"
        pd.DataFrame(records).to_csv(predictions_path, index=False)
        print(f"  [{year}] wrote {predictions_path}", flush=True)

    metrics_path = args.output_dir / "backtest_metrics.json"
    metrics_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    print(f"Wrote {metrics_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
