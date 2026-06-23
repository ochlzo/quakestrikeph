import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SHARED_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

# Feature engineering lives in the shared module so training and serving compute
# identical features. These names are re-exported here because several downstream
# scripts (backtests, calibration, the seis package) import them from
# predict_aftershock.
from feature_engineering import (  # noqa: E402,F401
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    LOCAL_RADII_KM,
    NEAREST_RECENT_WINDOW_DAYS,
    PHIVOLCS_TIME_FORMAT,
    RAW_COLUMN_MAP,
    RECENT_WINDOWS_DAYS,
    SECONDS_PER_YEAR,
    build_prediction_features,
    compute_global_history_features,
    compute_local_history_features,
    compute_parent_features,
    filter_history_for_prediction,
    haversine_km,
    load_feature_columns,
    normalize_raw_catalog,
    parse_origin_time,
)
from train_lightgbm_aftershock_models import (  # noqa: E402
    CLASSIFICATION_TARGETS,
    DEFAULT_OUTPUT_DIR,
    LOG_DISTANCE_TARGETS,
    REGRESSION_TARGETS,
)


DEFAULT_FEATURE_COLUMNS = Path("src/outputs/lightgbm/models_mc_1_0/feature_columns.txt")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run LightGBM aftershock inference for one raw earthquake event."
    )
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--event-csv", type=Path, help="CSV containing one raw event row.")
    parser.add_argument("--date-time", help="Event Date-Time, e.g. '26 April 2026 - 03:20 PM'.")
    parser.add_argument("--latitude", type=float)
    parser.add_argument("--longitude", type=float)
    parser.add_argument("--depth", type=float)
    parser.add_argument("--magnitude", type=float)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--fractal-dimension", type=float, default=DEFAULT_FRACTAL_DIMENSION)
    parser.add_argument("--log10-eta0", type=float, default=DEFAULT_LOG10_ETA0)
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def require_prediction_dependencies():
    try:
        import joblib
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "Prediction requires joblib and LightGBM model dependencies. "
            "Install them with `python -m pip install -r requirements-lightgbm.txt`."
        ) from error

    return joblib


def load_new_event(args):
    if args.event_csv:
        event_df = pd.read_csv(args.event_csv, low_memory=False)
        if len(event_df) != 1:
            raise ValueError("--event-csv must contain exactly one row.")
        return normalize_raw_catalog(event_df).iloc[0].to_dict()

    missing_args = [
        name
        for name, value in [
            ("--date-time", args.date_time),
            ("--latitude", args.latitude),
            ("--longitude", args.longitude),
            ("--depth", args.depth),
            ("--magnitude", args.magnitude),
        ]
        if value is None
    ]
    if missing_args:
        raise ValueError(
            "Provide either --event-csv or all raw event arguments: "
            + ", ".join(missing_args)
        )

    event_df = pd.DataFrame(
        [
            {
                "Date-Time": args.date_time,
                "Latitude": args.latitude,
                "Longitude": args.longitude,
                "Depth": args.depth,
                "Magnitude": args.magnitude,
            }
        ]
    )
    return normalize_raw_catalog(event_df).iloc[0].to_dict()


def load_models(models_dir, joblib):
    models = {}
    for target in [*CLASSIFICATION_TARGETS, *REGRESSION_TARGETS]:
        model_path = models_dir / f"{target}.joblib"
        if not model_path.exists():
            raise FileNotFoundError(f"Model file does not exist: {model_path}")
        models[target] = joblib.load(model_path)
    return models


def positive_class_probability(model, feature_row):
    """Probability of the positive class (label 1), robust to class ordering.

    Works for every family: plain estimators (LightGBM/XGBoost/CatBoost) and the
    Random Forest sklearn Pipeline both expose ``classes_`` and ``predict_proba``.
    """
    probabilities = model.predict_proba(feature_row)
    class_positions = {label: index for index, label in enumerate(model.classes_)}
    if 1 not in class_positions:
        return 0.0
    return float(probabilities[0, class_positions[1]])


def run_predictions(feature_row, models, classification_targets, regression_targets, log_distance_targets):
    """Shared serving inference for all four families (new Path B schema).

    Distance regressors are trained in log1p(km) space, so their raw prediction
    is back-transformed with expm1 (clipped at 0) to recover kilometres.
    """
    mc_model = models["aftershock_spatial_zone_24h"]
    p = mc_model.predict_proba(feature_row)[0] # [p0, p1, p2, p3, p4]
    
    # Clip each probability to [0.0, 1.0] just in case of float issues
    p = np.clip(p, 0.0, 1.0)
    
    classification = {
        "aftershock_24h": float(p[1:].sum()),
        "aftershock_within_10km_24h": float(p[1]),
        "aftershock_within_25km_24h": float(p[1] + p[2]),
        "aftershock_within_50km_24h": float(p[1] + p[2] + p[3]),
        "aftershock_beyond_50km_24h": float(p[4]),
    }
    for target in classification:
        classification[target] = float(np.clip(classification[target], 0.0, 1.0))

    regression = {}
    for target in regression_targets:
        prediction = float(models[target].predict(feature_row)[0])
        if target in log_distance_targets:
            prediction = float(np.clip(np.expm1(prediction), 0.0, None))
        regression[target] = prediction
    return classification, regression


def build_output(event, feature_row, classification, regression, history_rows):
    feature_values = {}
    for column, value in feature_row.iloc[0].items():
        if pd.isna(value):
            feature_values[column] = None
        elif isinstance(value, (np.integer,)):
            feature_values[column] = int(value)
        elif isinstance(value, (np.floating,)):
            feature_values[column] = float(value)
        else:
            feature_values[column] = value

    # Disjoint zone probabilities: extract from cumulative values
    p1 = classification["aftershock_within_10km_24h"]
    p2 = classification["aftershock_within_25km_24h"] - p1
    p3 = classification["aftershock_within_50km_24h"] - (p1 + p2)
    p4 = classification["aftershock_24h"] - (p1 + p2 + p3)

    containment = {
        "within_10km": float(np.clip(p1, 0.0, 1.0)),
        "between_10_25km": float(np.clip(p2, 0.0, 1.0)),
        "between_25_50km": float(np.clip(p3, 0.0, 1.0)),
        "beyond_50km": float(np.clip(p4, 0.0, 1.0)),
    }
    return {
        "event": {
            "origin_time": str(event["origin_time"]),
            "event_time": event["event_time"].isoformat(),
            "latitude": float(event["latitude"]),
            "longitude": float(event["longitude"]),
            "depth_km": float(event["depth_km"]),
            "magnitude": float(event["magnitude"]),
        },
        "history_rows_used": int(history_rows),
        "features": feature_values,
        "predictions": {
            "aftershock_24h_probability": classification["aftershock_24h"],
            "aftershock_distance_probabilities_24h": containment,
            "estimated_max_aftershock_magnitude_if_aftershock_24h": regression[
                "max_aftershock_mag_24h"
            ],
            "estimated_aftershock_distances_km_if_aftershock_24h": {
                "nearest": regression["nearest_aftershock_distance_km_24h"],
                "median": regression["median_aftershock_distance_km_24h"],
                "p90": regression["p90_aftershock_distance_km_24h"],
            },
        },
    }


def main():
    args = parse_args()
    joblib = require_prediction_dependencies()
    if not args.historical_csv.exists():
        raise FileNotFoundError(f"Historical CSV does not exist: {args.historical_csv}")

    event = load_new_event(args)
    if event["magnitude"] < args.minimum_magnitude:
        raise ValueError(
            f"Event magnitude {event['magnitude']} is below the model minimum "
            f"magnitude threshold {args.minimum_magnitude}."
        )

    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))
    history = filter_history_for_prediction(
        history,
        event["event_time"],
        args.minimum_magnitude,
    )
    feature_columns = load_feature_columns(args.feature_columns)
    feature_row = build_prediction_features(history, event, args, feature_columns)
    models = load_models(args.models_dir, joblib)
    classification, regression = run_predictions(
        feature_row,
        models,
        CLASSIFICATION_TARGETS,
        REGRESSION_TARGETS,
        LOG_DISTANCE_TARGETS,
    )
    output = build_output(event, feature_row, classification, regression, len(history))
    output_json = json.dumps(output, indent=2, allow_nan=False)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(output_json + "\n", encoding="utf-8")
        print(f"Wrote {args.output_json}")
    else:
        print(output_json)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
