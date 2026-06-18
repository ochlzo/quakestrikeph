import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from predict_aftershock import (
    DEFAULT_FEATURE_COLUMNS,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_MIN_MAGNITUDE,
    build_prediction_features,
    filter_history_for_prediction,
    load_feature_columns,
    load_models,
    normalize_raw_catalog,
    require_prediction_dependencies,
    run_predictions,
)
from train_lightgbm_aftershock_models import (
    CLASSIFICATION_TARGETS,
    DEFAULT_INPUT_CSV,
    DEFAULT_OUTPUT_DIR as DEFAULT_MODELS_DIR,
    REGRESSION_TARGETS,
)


DEFAULT_BACKTEST_OUTPUT_DIR = Path("src/outputs/lightgbm/backtests_mc_1_0")
DISTANCE_TARGET_LABELS = {
    "aftershock_dist_0_10km_24h": "0_10km",
    "aftershock_dist_10_25km_24h": "10_25km",
    "aftershock_dist_25_50km_24h": "25_50km",
    "aftershock_dist_50_100km_24h": "50_100km",
    "aftershock_dist_100_200km_24h": "100_200km",
    "aftershock_dist_200_pluskm_24h": "200_pluskm",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Backtest the production-style LightGBM inference path against "
            "historical labeled events."
        )
    )
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
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
        default="chronological",
        help="How to choose rows when --max-events limits the backtest. "
        "chronological keeps the natural deployment prevalence; balanced "
        "oversamples positives and distorts Brier/precision.",
    )
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=1.0)
    parser.add_argument("--fractal-dimension", type=float, default=1.6)
    parser.add_argument("--log10-eta0", type=float, default=-5.468679834899335)
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
            "Backtest metrics require scikit-learn. Install dependencies with "
            "`python -m pip install -r requirements-lightgbm.txt`."
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


def load_labeled_events(path, test_start_year, minimum_magnitude):
    if not path.exists():
        raise FileNotFoundError(f"Labeled CSV does not exist: {path}")
    df = pd.read_csv(path, low_memory=False)
    required = {
        "event_id",
        "origin_time",
        "event_time",
        "latitude",
        "longitude",
        "depth_km",
        "magnitude",
        "event_year",
        *REGRESSION_TARGETS,
        *CLASSIFICATION_TARGETS,
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Labeled CSV is missing required columns: {missing}")

    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    df = df.dropna(subset=["event_time", "latitude", "longitude", "depth_km", "magnitude"])
    df = df[
        (df["event_year"] >= test_start_year)
        & (df["magnitude"] >= minimum_magnitude)
    ].copy()
    if df.empty:
        raise ValueError("No labeled test events matched the requested filters.")
    return df.sort_values(["event_time", "event_id"], kind="mergesort").reset_index(drop=True)


def sample_events(df, max_events, sample_mode, random_seed):
    if max_events == 0 or len(df) <= max_events:
        return df.copy()
    if max_events < 0:
        raise ValueError("--max-events must be >= 0.")

    if sample_mode == "chronological":
        positions = np.linspace(0, len(df) - 1, max_events, dtype=int)
        return df.iloc[positions].copy().reset_index(drop=True)

    positives = df[df["aftershock_24h"].eq(1)]
    negatives = df[df["aftershock_24h"].eq(0)]
    positive_count = min(len(positives), max_events // 2)
    negative_count = min(len(negatives), max_events - positive_count)
    if positive_count + negative_count < max_events:
        remaining = max_events - positive_count - negative_count
        positive_count = min(len(positives), positive_count + remaining)

    sampled = pd.concat(
        [
            positives.sample(n=positive_count, random_state=random_seed)
            if positive_count
            else positives.iloc[:0],
            negatives.sample(n=negative_count, random_state=random_seed + 1)
            if negative_count
            else negatives.iloc[:0],
        ],
        ignore_index=True,
    )
    return sampled.sort_values(["event_time", "event_id"], kind="mergesort").reset_index(drop=True)


def row_to_event(row):
    return {
        "origin_time": row["origin_time"],
        "event_time": row["event_time"],
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "depth_km": float(row["depth_km"]),
        "magnitude": float(row["magnitude"]),
    }


def probability_for_target(target, classification):
    if target == "aftershock_24h":
        return classification[target]
    return classification[target]


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
        record[f"predicted_probability_{target}"] = float(
            probability_for_target(target, classification)
        )
    return record


def classification_metrics(y_true, y_probability, metrics):
    y_true = np.asarray(y_true, dtype=int)
    y_probability = np.asarray(y_probability, dtype=float)
    y_pred = (y_probability >= 0.5).astype(int)
    result = {
        "count": int(len(y_true)),
        "positive_rate": float(np.mean(y_true)),
        "predicted_positive_rate_at_0_5": float(np.mean(y_pred)),
        "brier": float(metrics["brier_score_loss"](y_true, y_probability)),
        "precision_at_0_5": float(metrics["precision_score"](y_true, y_pred, zero_division=0)),
        "recall_at_0_5": float(metrics["recall_score"](y_true, y_pred, zero_division=0)),
    }
    if len(np.unique(y_true)) == 2:
        result["roc_auc"] = float(metrics["roc_auc_score"](y_true, y_probability))
        result["average_precision"] = float(
            metrics["average_precision_score"](y_true, y_probability)
        )
    else:
        result["roc_auc"] = None
        result["average_precision"] = None
    return result


def regression_metrics(records, actual_key, predicted_key, metrics):
    pairs = [
        (
            record[actual_key],
            record[predicted_key],
        )
        for record in records
        if record[actual_key] is not None
    ]
    if not pairs:
        return {"count": 0}

    y_true = np.asarray([pair[0] for pair in pairs], dtype=float)
    y_pred = np.asarray([pair[1] for pair in pairs], dtype=float)
    mse = metrics["mean_squared_error"](y_true, y_pred)
    return {
        "count": int(len(y_true)),
        "mae": float(metrics["mean_absolute_error"](y_true, y_pred)),
        "rmse": float(np.sqrt(mse)),
        "r2": float(metrics["r2_score"](y_true, y_pred)),
        "actual_mean": float(np.mean(y_true)),
        "predicted_mean": float(np.mean(y_pred)),
    }


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
    joblib = require_prediction_dependencies()
    metric_deps = require_metric_dependencies()
    feature_columns = load_feature_columns(args.feature_columns)
    models = load_models(args.models_dir, joblib)

    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))
    labeled = load_labeled_events(
        args.labeled_csv,
        args.test_start_year,
        args.minimum_magnitude,
    )
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
        classification, max_magnitude, max_distance = run_predictions(feature_row, models)
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
            "labeled_csv": str(args.labeled_csv),
            "historical_csv": str(args.historical_csv),
            "models_dir": str(args.models_dir),
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
