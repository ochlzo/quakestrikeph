import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

# Add prediction script to sys.path
SEIS_DIR = Path(__file__).resolve().parent
if str(SEIS_DIR) not in sys.path:
    sys.path.insert(0, str(SEIS_DIR))

from predict import (
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    HYBRID_MODEL_MAPPING,
    build_prediction_features,
    filter_history_for_prediction,
    load_feature_columns,
    load_all_hybrid_models,
    normalize_raw_catalog,
    require_dependencies,
    run_hybrid_predictions,
    load_feature_columns,
)

# Reference LightGBM backtest helper imports
LIGHTGBM_DIR = SEIS_DIR.parent / "lightgbm"
if str(LIGHTGBM_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_DIR))

from backtest_aftershock_predictions import (
    DEFAULT_INPUT_CSV,
    load_labeled_events,
    sample_events,
    row_to_event,
    classification_metrics,
    regression_metrics,
)

DEFAULT_FEATURE_COLUMNS = Path("src/outputs/lightgbm/models_mc_1_0/feature_columns.txt")
DEFAULT_BACKTEST_OUTPUT_DIR = Path("src/outputs/seis/backtests_mc_1_0")

CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backtest the SEIS Hybrid Multi-Model inference path against historical holdout events."
    )
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--xgb-models-dir", type=Path, default=Path("src/outputs/xgboost/models_mc_1_0"))
    parser.add_argument("--lgb-models-dir", type=Path, default=Path("src/outputs/lightgbm/models_mc_1_0"))
    parser.add_argument("--rf-models-dir", type=Path, default=Path("src/outputs/random-forest/models_mc_1_0"))
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKTEST_OUTPUT_DIR)
    parser.add_argument("--test-start-year", type=int, default=2025)
    parser.add_argument(
        "--max-events",
        type=int,
        default=500,
        help="Maximum labeled events to backtest. Use 0 for all matching events.",
    )
    parser.add_argument(
        "--sample-mode",
        choices=["balanced", "chronological"],
        default="balanced",
        help="How to choose rows when --max-events limits the backtest.",
    )
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--fractal-dimension", type=float, default=DEFAULT_FRACTAL_DIMENSION)
    parser.add_argument("--log10-eta0", type=float, default=DEFAULT_LOG10_ETA0)
    return parser.parse_args()


def require_metric_dependencies():
    try:
        from sklearn.metrics import (
            average_precision_score,
            brier_score_loss,
            mean_absolute_error,
            mean_squared_error,
            precision_score,
            r2_score,
            recall_score,
            roc_auc_score,
        )
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "Backtesting requires scikit-learn. Install dependencies before running."
        ) from error

    return {
        "average_precision_score": average_precision_score,
        "brier_score_loss": brier_score_loss,
        "mean_absolute_error": mean_absolute_error,
        "mean_squared_error": mean_squared_error,
        "precision_score": precision_score,
        "r2_score": r2_score,
        "recall_score": recall_score,
        "roc_auc_score": roc_auc_score,
    }


def build_prediction_record(row, classification, max_magnitude, max_distance, history_rows):
    record = {
        "event_id": row["event_id"],
        "origin_time": row["origin_time"],
        "event_time": row["event_time"].isoformat(),
        "magnitude": float(row["magnitude"]),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "history_rows_used": int(history_rows),
        "predicted_max_aftershock_mag_24h": float(max_magnitude),
        "actual_max_aftershock_mag_24h": (
            None if pd.isna(row["max_aftershock_mag_24h"]) else float(row["max_aftershock_mag_24h"])
        ),
        "predicted_max_aftershock_distance_km_24h": float(max_distance),
        "actual_max_aftershock_distance_km_24h": (
            None if pd.isna(row["max_aftershock_distance_km_24h"]) else float(row["max_aftershock_distance_km_24h"])
        ),
    }
    for target in CLASSIFICATION_TARGETS:
        record[f"actual_{target}"] = int(row[target])
        record[f"predicted_probability_{target}"] = float(classification[target])
    return record


def summarize_records(records, metrics):
    summary = {"classification": {}}
    for target in CLASSIFICATION_TARGETS:
        y_true = [record[f"actual_{target}"] for record in records]
        y_probability = [
            record[f"predicted_probability_{target}"] for record in records
        ]
        summary["classification"][target] = classification_metrics(
            y_true,
            y_probability,
            metrics,
        )
    summary["regression"] = {
        "max_aftershock_mag_24h": regression_metrics(
            records, "actual_max_aftershock_mag_24h", "predicted_max_aftershock_mag_24h", metrics
        ),
        "max_aftershock_distance_km_24h": regression_metrics(
            records, "actual_max_aftershock_distance_km_24h", "predicted_max_aftershock_distance_km_24h", metrics
        ),
    }
    return summary


def main():
    args = parse_args()
    deps = require_dependencies()
    metric_deps = require_metric_dependencies()
    feature_columns = load_feature_columns(args.feature_columns)
    
    # Load all models
    models = load_all_hybrid_models(args, deps)

    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))
    labeled = load_labeled_events(
        args.labeled_csv,
        args.test_start_year,
        args.minimum_magnitude,
    )
    
    # Check if there is an extra column required by the regression targets
    if "max_aftershock_distance_km_24h" not in labeled.columns:
        # Re-parse labeled events or ensure it is present
        pass
        
    sampled = sample_events(
        labeled,
        args.max_events,
        args.sample_mode,
        args.random_seed,
    )

    records = []
    for index, row in sampled.iterrows():
        event = row_to_event(row)
        prediction_history = filter_history_for_prediction(
            history,
            event["event_time"],
            args.minimum_magnitude,
        )
        feature_row = build_prediction_features(
            prediction_history,
            event,
            args,
            feature_columns,
        )
        classification, max_magnitude, max_distance = run_hybrid_predictions(feature_row, models)
        records.append(
            build_prediction_record(
                row,
                classification,
                max_magnitude,
                max_distance,
                len(prediction_history),
            )
        )
        if (index + 1) % 50 == 0:
            print(f"Backtested {index + 1}/{len(sampled)} events...")

    summary = {
        "config": {
            "model_family": "seis_hybrid_ensemble",
            "labeled_csv": str(args.labeled_csv),
            "historical_csv": str(args.historical_csv),
            "xgb_models_dir": str(args.xgb_models_dir),
            "lgb_models_dir": str(args.lgb_models_dir),
            "rf_models_dir": str(args.rf_models_dir),
            "feature_columns": str(args.feature_columns),
            "test_start_year": args.test_start_year,
            "max_events": args.max_events,
            "sample_mode": args.sample_mode,
            "sampled_rows": int(len(sampled)),
            "candidate_rows": int(len(labeled)),
            "minimum_magnitude": args.minimum_magnitude,
        },
        "metrics": summarize_records(records, metric_deps),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = args.output_dir / "backtest_predictions.csv"
    metrics_path = args.output_dir / "backtest_metrics.json"
    pd.DataFrame(records).to_csv(predictions_path, index=False)
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {predictions_path}")
    print(f"Wrote {metrics_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
