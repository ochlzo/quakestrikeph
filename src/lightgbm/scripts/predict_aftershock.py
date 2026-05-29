import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from build_lightgbm_training_dataset import (
    LOCAL_RADII_KM,
    NEAREST_RECENT_WINDOW_DAYS,
    PHIVOLCS_TIME_FORMAT,
    RECENT_WINDOWS_DAYS,
    haversine_km,
    parse_origin_time,
)
from train_lightgbm_aftershock_models import (
    CLASSIFICATION_TARGETS,
    DEFAULT_OUTPUT_DIR,
    REGRESSION_TARGET,
)


DEFAULT_HISTORICAL_CSV = Path("dataset/phivolcs_earthquake_2018_2026.csv")
DEFAULT_FEATURE_COLUMNS = Path("outputs/lightgbm_models_mc_1_0/feature_columns.txt")
DEFAULT_MIN_MAGNITUDE = 1.0
DEFAULT_B_VALUE = 1.0
DEFAULT_FRACTAL_DIMENSION = 1.6
DEFAULT_LOG10_ETA0 = -5.468679834899335
SECONDS_PER_YEAR = 365.25 * 24.0 * 60.0 * 60.0


RAW_COLUMN_MAP = {
    "Date-Time": "origin_time",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Depth": "depth_km",
    "Magnitude": "magnitude",
}


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


def normalize_raw_catalog(df):
    renamed = df.rename(columns={source: target for source, target in RAW_COLUMN_MAP.items()})
    required = {"origin_time", "latitude", "longitude", "depth_km", "magnitude"}
    missing = sorted(required - set(renamed.columns))
    if missing:
        raise ValueError(f"CSV is missing required raw columns: {missing}")

    normalized = renamed[list(required)].copy()
    normalized["event_time"] = parse_origin_time(normalized["origin_time"])
    for column in ["latitude", "longitude", "depth_km", "magnitude"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    before = len(normalized)
    normalized = normalized.dropna(
        subset=["event_time", "latitude", "longitude", "depth_km", "magnitude"]
    )
    if normalized.empty:
        raise ValueError("No usable historical rows after parsing raw catalog.")
    if len(normalized) != before:
        skipped = before - len(normalized)
        print(f"Warning: skipped {skipped} malformed historical rows.", file=sys.stderr)

    return normalized.sort_values("event_time", kind="mergesort").reset_index(drop=True)


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


def load_feature_columns(feature_columns_path):
    if not feature_columns_path.exists():
        raise FileNotFoundError(f"Feature columns file does not exist: {feature_columns_path}")
    return [
        line.strip()
        for line in feature_columns_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def filter_history_for_prediction(history, event_time, minimum_magnitude):
    history = history[
        (history["event_time"] < event_time)
        & (history["magnitude"] >= minimum_magnitude)
    ].copy()
    return history.sort_values("event_time", kind="mergesort").reset_index(drop=True)


def compute_parent_features(history, event, b_value, fractal_dimension, log10_eta0):
    defaults = {
        "eta": np.nan,
        "log10_eta": np.nan,
        "is_strong_link": 0,
        "has_parent": 0,
        "parent_time_gap_days": np.nan,
        "parent_distance_km": np.nan,
        "parent_magnitude": np.nan,
        "parent_depth_km": np.nan,
    }
    if history.empty:
        return defaults

    seconds = (event["event_time"] - history["event_time"]).dt.total_seconds().to_numpy()
    valid_time = seconds > 0
    if not valid_time.any():
        return defaults

    candidates = history.loc[valid_time].copy()
    seconds = seconds[valid_time]
    distances = haversine_km(
        event["latitude"],
        event["longitude"],
        candidates["latitude"].to_numpy(dtype=float),
        candidates["longitude"].to_numpy(dtype=float),
    )
    valid_distance = distances > 0.0
    if not valid_distance.any():
        return defaults

    candidates = candidates.loc[valid_distance].reset_index(drop=True)
    seconds = seconds[valid_distance]
    distances = distances[valid_distance]
    years = seconds / SECONDS_PER_YEAR
    log_eta = (
        np.log10(years)
        + fractal_dimension * np.log10(distances)
        - b_value * candidates["magnitude"].to_numpy(dtype=float)
    )
    best_position = int(np.nanargmin(log_eta))
    best_log_eta = float(log_eta[best_position])
    parent = candidates.iloc[best_position]

    return {
        "eta": float(10.0 ** best_log_eta),
        "log10_eta": best_log_eta,
        "is_strong_link": int(best_log_eta < log10_eta0),
        "has_parent": 1,
        "parent_time_gap_days": float(seconds[best_position] / 86400.0),
        "parent_distance_km": float(distances[best_position]),
        "parent_magnitude": float(parent["magnitude"]),
        "parent_depth_km": float(parent["depth_km"]),
    }


def compute_global_history_features(history, event_time):
    features = {}
    for days in RECENT_WINDOWS_DAYS:
        start_time = event_time - pd.Timedelta(days=days)
        features[f"events_past_{days}d"] = int(
            ((history["event_time"] >= start_time) & (history["event_time"] < event_time)).sum()
        )
    return features


def compute_local_history_features(history, event):
    features = {}
    for days in RECENT_WINDOWS_DAYS:
        for radius in LOCAL_RADII_KM:
            radius_token = int(radius)
            features[f"local_events_{radius_token}km_past_{days}d"] = 0
            features[f"local_max_mag_{radius_token}km_past_{days}d"] = np.nan
            features[f"local_log10_energy_{radius_token}km_past_{days}d"] = np.nan

    features[
        f"nearest_recent_event_distance_km_past_{NEAREST_RECENT_WINDOW_DAYS}d"
    ] = np.nan
    features[
        f"nearest_recent_event_magnitude_past_{NEAREST_RECENT_WINDOW_DAYS}d"
    ] = np.nan
    features[
        f"nearest_recent_event_age_days_past_{NEAREST_RECENT_WINDOW_DAYS}d"
    ] = np.nan

    if history.empty:
        return features

    max_window_days = max(RECENT_WINDOWS_DAYS)
    max_radius_km = max(LOCAL_RADII_KM)
    start_time = event["event_time"] - pd.Timedelta(days=max_window_days)
    candidates = history[
        (history["event_time"] >= start_time)
        & (history["event_time"] < event["event_time"])
    ].copy()
    if candidates.empty:
        return features

    lat_delta = max_radius_km / 111.32
    lon_scale = max(math.cos(math.radians(event["latitude"])), 0.1)
    lon_delta = max_radius_km / (111.32 * lon_scale)
    candidates = candidates[
        (np.abs(candidates["latitude"] - event["latitude"]) <= lat_delta)
        & (np.abs(candidates["longitude"] - event["longitude"]) <= lon_delta)
    ].copy()
    if candidates.empty:
        return features

    distances = haversine_km(
        event["latitude"],
        event["longitude"],
        candidates["latitude"].to_numpy(dtype=float),
        candidates["longitude"].to_numpy(dtype=float),
    )
    candidates["distance_km"] = distances
    candidates = candidates[candidates["distance_km"] <= max_radius_km].copy()
    if candidates.empty:
        return features

    nearest_window_start = event["event_time"] - pd.Timedelta(days=NEAREST_RECENT_WINDOW_DAYS)
    nearest_candidates = candidates[candidates["event_time"] >= nearest_window_start]
    if not nearest_candidates.empty:
        nearest = nearest_candidates.loc[nearest_candidates["distance_km"].idxmin()]
        features[
            f"nearest_recent_event_distance_km_past_{NEAREST_RECENT_WINDOW_DAYS}d"
        ] = float(nearest["distance_km"])
        features[
            f"nearest_recent_event_magnitude_past_{NEAREST_RECENT_WINDOW_DAYS}d"
        ] = float(nearest["magnitude"])
        features[
            f"nearest_recent_event_age_days_past_{NEAREST_RECENT_WINDOW_DAYS}d"
        ] = float((event["event_time"] - nearest["event_time"]).total_seconds() / 86400.0)

    for days in RECENT_WINDOWS_DAYS:
        window_start = event["event_time"] - pd.Timedelta(days=days)
        window = candidates[candidates["event_time"] >= window_start]
        if window.empty:
            continue
        for radius in LOCAL_RADII_KM:
            radius_token = int(radius)
            local = window[window["distance_km"] <= radius]
            if local.empty:
                continue
            magnitudes = local["magnitude"].to_numpy(dtype=float)
            features[f"local_events_{radius_token}km_past_{days}d"] = int(len(local))
            features[f"local_max_mag_{radius_token}km_past_{days}d"] = float(np.nanmax(magnitudes))
            features[f"local_log10_energy_{radius_token}km_past_{days}d"] = float(
                np.log10(np.nansum(10.0 ** (1.5 * magnitudes)))
            )

    return features


def build_prediction_features(history, event, args, feature_columns):
    event_time = event["event_time"]
    features = {
        "magnitude": float(event["magnitude"]),
        "depth_km": float(event["depth_km"]),
        "latitude": float(event["latitude"]),
        "longitude": float(event["longitude"]),
        "event_year": int(event_time.year),
        "event_month": int(event_time.month),
        "event_dayofyear": int(event_time.dayofyear),
        "event_hour": int(event_time.hour),
        "event_weekday": int(event_time.weekday()),
    }
    features.update(
        compute_parent_features(
            history,
            event,
            args.b_value,
            args.fractal_dimension,
            args.log10_eta0,
        )
    )
    features.update(compute_global_history_features(history, event_time))
    features.update(compute_local_history_features(history, event))

    missing = sorted(set(feature_columns) - set(features))
    if missing:
        raise ValueError(f"Prediction builder did not create required features: {missing}")
    return pd.DataFrame([{column: features[column] for column in feature_columns}])


def load_models(models_dir, joblib):
    models = {}
    for target in [*CLASSIFICATION_TARGETS, REGRESSION_TARGET]:
        model_path = models_dir / f"{target}.joblib"
        if not model_path.exists():
            raise FileNotFoundError(f"Model file does not exist: {model_path}")
        models[target] = joblib.load(model_path)
    return models


def run_predictions(feature_row, models):
    classification = {}
    for target in CLASSIFICATION_TARGETS:
        probability = models[target].predict_proba(feature_row, validate_features=True)[0, 1]
        classification[target] = float(probability)

    max_magnitude = float(models[REGRESSION_TARGET].predict(feature_row)[0])
    return classification, max_magnitude


def build_output(event, feature_row, classification, max_magnitude, history_rows):
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

    distance_bins = {
        "0_10km": classification["aftershock_dist_0_10km_24h"],
        "10_25km": classification["aftershock_dist_10_25km_24h"],
        "25_50km": classification["aftershock_dist_25_50km_24h"],
        "50_100km": classification["aftershock_dist_50_100km_24h"],
        "100_200km": classification["aftershock_dist_100_200km_24h"],
        "200_pluskm": classification["aftershock_dist_200_pluskm_24h"],
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
            "distance_bin_probabilities_24h": distance_bins,
            "estimated_max_aftershock_magnitude_if_aftershock_24h": max_magnitude,
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
    classification, max_magnitude = run_predictions(feature_row, models)
    output = build_output(event, feature_row, classification, max_magnitude, len(history))
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
