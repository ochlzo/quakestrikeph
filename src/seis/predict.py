import argparse
import json
import math
import sys
from pathlib import Path
import pandas as pd
import numpy as np

# Add lightgbm path to sys.path to import prediction feature builders
LIGHTGBM_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "lightgbm"
if str(LIGHTGBM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_SCRIPT_DIR))

from predict_aftershock import (  # noqa: E402
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    build_prediction_features,
    filter_history_for_prediction,
    load_feature_columns,
    load_new_event,
    normalize_raw_catalog,
)

# Default model directory paths
DEFAULT_XGB_DIR = Path("src/outputs/xgboost/models_mc_1_0")
DEFAULT_LGB_DIR = Path("src/outputs/lightgbm/models_mc_1_0")
DEFAULT_RF_DIR = Path("src/outputs/random-forest/models_mc_1_0")
DEFAULT_FEATURE_COLUMNS = DEFAULT_LGB_DIR / "feature_columns.txt"

# Classification targets
CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]

# Model selection mapping from src/docs/model_recommendations.md
HYBRID_MODEL_MAPPING = {
    # Classification
    "aftershock_24h": ("xgboost", DEFAULT_XGB_DIR),
    "aftershock_dist_0_10km_24h": ("xgboost", DEFAULT_XGB_DIR),
    "aftershock_dist_10_25km_24h": ("lightgbm", DEFAULT_LGB_DIR),
    "aftershock_dist_25_50km_24h": ("lightgbm", DEFAULT_LGB_DIR),
    "aftershock_dist_50_100km_24h": ("xgboost", DEFAULT_XGB_DIR),
    "aftershock_dist_100_200km_24h": ("xgboost", DEFAULT_XGB_DIR),
    "aftershock_dist_200_pluskm_24h": ("lightgbm", DEFAULT_LGB_DIR),
    # Regression
    "max_aftershock_mag_24h": ("random_forest", DEFAULT_RF_DIR),
    "max_aftershock_distance_km_24h": ("lightgbm", DEFAULT_LGB_DIR),
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run SEIS Hybrid Multi-Model aftershock inference for one raw earthquake event."
    )
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--xgb-models-dir", type=Path, default=DEFAULT_XGB_DIR)
    parser.add_argument("--lgb-models-dir", type=Path, default=DEFAULT_LGB_DIR)
    parser.add_argument("--rf-models-dir", type=Path, default=DEFAULT_RF_DIR)
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


def require_dependencies():
    try:
        import joblib
        import xgboost as xgb
        import lightgbm as lgb
        import sklearn
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "SEIS predictor requires joblib, xgboost, lightgbm, and scikit-learn. "
            "Please ensure all model dependencies are installed."
        ) from error
    return {"joblib": joblib, "xgb": xgb, "lgb": lgb}


def load_hybrid_model(target, family, models_dir, deps):
    joblib = deps["joblib"]
    joblib_path = models_dir / f"{target}.joblib"
    
    if family == "xgboost":
        # Load XGBoost (can be joblib or json format)
        if joblib_path.exists():
            return joblib.load(joblib_path)
        json_path = models_dir / f"{target}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"XGBoost model file not found: {joblib_path} or {json_path}")
        model = deps["xgb"].XGBClassifier()
        model.load_model(json_path)
        return model
        
    elif family == "lightgbm":
        # Load LightGBM joblib
        if not joblib_path.exists():
            raise FileNotFoundError(f"LightGBM model file not found: {joblib_path}")
        return joblib.load(joblib_path)
        
    elif family == "random_forest":
        # Load Random Forest joblib
        if not joblib_path.exists():
            raise FileNotFoundError(f"Random Forest model file not found: {joblib_path}")
        return joblib.load(joblib_path)
        
    else:
        raise ValueError(f"Unknown model family: {family}")


def load_all_hybrid_models(args, deps):
    models = {}
    for target, (family, default_dir) in HYBRID_MODEL_MAPPING.items():
        # Determine the user-specified directory for the target family
        if family == "xgboost":
            models_dir = args.xgb_models_dir
        elif family == "lightgbm":
            models_dir = args.lgb_models_dir
        else:
            models_dir = args.rf_models_dir
            
        model = load_hybrid_model(target, family, models_dir, deps)
        
        # Set n_jobs=1 on models to prevent multi-threading overhead during single-row predictions
        if hasattr(model, "set_params"):
            try:
                model.set_params(n_jobs=1)
            except Exception:
                pass
        models[target] = model
    return models


def positive_class_probability(model, feature_row):
    # Determine the probability of the positive class (label 1)
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(feature_row)
        # Handle Pipeline (sklearn/Random Forest) vs direct classifiers
        classifier = model.named_steps["model"] if hasattr(model, "named_steps") else model
        class_positions = {label: index for index, label in enumerate(classifier.classes_)}
        if 1 not in class_positions:
            return 0.0
        return float(probabilities[0, class_positions[1]])
    else:
        raise AttributeError("Model does not support predict_proba")


def run_hybrid_predictions(feature_row, models):
    classification = {}
    # Run classification targets
    for target in CLASSIFICATION_TARGETS:
        classification[target] = positive_class_probability(models[target], feature_row)
        
    # Run regression targets
    max_magnitude = float(models["max_aftershock_mag_24h"].predict(feature_row)[0])
    max_distance = float(models["max_aftershock_distance_km_24h"].predict(feature_row)[0])
    
    return classification, max_magnitude, max_distance


def build_output(event, feature_row, classification, max_magnitude, max_distance, history_rows):
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
            "estimated_max_aftershock_distance_km_if_aftershock_24h": max_distance,
        },
    }


def main():
    args = parse_args()
    deps = require_dependencies()
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
    
    # Load all hybrid models
    models = load_all_hybrid_models(args, deps)
    
    # Execute predictions
    classification, max_magnitude, max_distance = run_hybrid_predictions(feature_row, models)
    output = build_output(event, feature_row, classification, max_magnitude, max_distance, len(history))
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
