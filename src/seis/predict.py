import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Feature engineering comes straight from the shared module so training and
# serving compute identical features (single source of truth).
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

# Serving helpers (event parsing, shared inference, output schema) live in the
# LightGBM predict module, the repo's serving base. The ensemble holds exactly
# one chosen model per target, so the same run_predictions/build_output the
# single-family scripts use produce an identical-schema output here.
LIGHTGBM_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "lightgbm"
if str(LIGHTGBM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_SCRIPT_DIR))

from predict_aftershock import (  # noqa: E402
    build_output,
    load_new_event,
    run_predictions,
)

# Default per-family model directories.
DEFAULT_XGB_DIR = Path("src/outputs/xgboost/models_mc_1_0")
DEFAULT_LGB_DIR = Path("src/outputs/lightgbm/models_mc_1_0")
DEFAULT_RF_DIR = Path("src/outputs/random-forest/models_mc_1_0")
DEFAULT_CB_DIR = Path("src/outputs/catboost/models_mc_1_0")
DEFAULT_FEATURE_COLUMNS = DEFAULT_LGB_DIR / "feature_columns.txt"

# New Path B target schema (matches every train_*/predict_* script).
CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_within_10km_24h",
    "aftershock_within_25km_24h",
    "aftershock_within_50km_24h",
    "aftershock_within_100km_24h",
    "aftershock_within_200km_24h",
]
REGRESSION_TARGETS = [
    "max_aftershock_mag_24h",
    "nearest_aftershock_distance_km_24h",
    "median_aftershock_distance_km_24h",
    "p90_aftershock_distance_km_24h",
]
# Distance regressors are served in log1p(km) space; run_predictions applies
# expm1 to recover kilometres.
LOG_DISTANCE_TARGETS = {
    "nearest_aftershock_distance_km_24h",
    "median_aftershock_distance_km_24h",
    "p90_aftershock_distance_km_24h",
}

FAMILY_DIRS = {
    "xgboost": DEFAULT_XGB_DIR,
    "lightgbm": DEFAULT_LGB_DIR,
    "random_forest": DEFAULT_RF_DIR,
    "catboost": DEFAULT_CB_DIR,
}

# Per-target winner taken verbatim from src/outputs/seis/backtest_pick_report.json
# (2025 backtest, production inference path, Path B / natural prevalence — no
# post-hoc calibration). Classification picks minimize Brier; regression picks
# maximize R^2. Regenerate that report (src/seis/build_pick_report_from_backtests.py)
# and update this dict after any re-train. Random Forest wins no target.
HYBRID_MODEL_MAPPING = {
    # Classification
    "aftershock_24h": "lightgbm",
    "aftershock_within_10km_24h": "lightgbm",
    "aftershock_within_25km_24h": "catboost",
    "aftershock_within_50km_24h": "catboost",
    "aftershock_within_100km_24h": "catboost",
    "aftershock_within_200km_24h": "catboost",
    # Regression
    "max_aftershock_mag_24h": "catboost",
    "nearest_aftershock_distance_km_24h": "lightgbm",
    "median_aftershock_distance_km_24h": "xgboost",
    "p90_aftershock_distance_km_24h": "xgboost",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run SEIS hybrid multi-model aftershock inference for one raw earthquake event."
    )
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--xgb-models-dir", type=Path, default=DEFAULT_XGB_DIR)
    parser.add_argument("--lgb-models-dir", type=Path, default=DEFAULT_LGB_DIR)
    parser.add_argument("--rf-models-dir", type=Path, default=DEFAULT_RF_DIR)
    parser.add_argument("--cb-models-dir", type=Path, default=DEFAULT_CB_DIR)
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
        import lightgbm as lgb  # noqa: F401  (needed to unpickle saved models)
        import catboost as cb
        import sklearn  # noqa: F401  (needed to unpickle the RF pipeline)
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "SEIS predictor requires joblib, xgboost, lightgbm, catboost, and scikit-learn. "
            "Please ensure all model dependencies are installed."
        ) from error
    return {"joblib": joblib, "xgb": xgb, "cb": cb}


def resolve_models_dir(family, args):
    return {
        "xgboost": args.xgb_models_dir,
        "lightgbm": args.lgb_models_dir,
        "random_forest": args.rf_models_dir,
        "catboost": args.cb_models_dir,
    }[family]


def load_hybrid_model(target, family, models_dir, deps):
    """Load one target's chosen-family model (joblib, with native fallback)."""
    joblib = deps["joblib"]
    is_regression = target in REGRESSION_TARGETS
    joblib_path = models_dir / f"{target}.joblib"

    if family in ("lightgbm", "random_forest"):
        if not joblib_path.exists():
            raise FileNotFoundError(f"{family} model file not found: {joblib_path}")
        return joblib.load(joblib_path)

    if family == "xgboost":
        if joblib_path.exists():
            return joblib.load(joblib_path)
        json_path = models_dir / f"{target}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"XGBoost model file not found: {joblib_path} or {json_path}")
        model = deps["xgb"].XGBRegressor() if is_regression else deps["xgb"].XGBClassifier()
        model.load_model(json_path)
        return model

    if family == "catboost":
        if joblib_path.exists():
            return joblib.load(joblib_path)
        cbm_path = models_dir / f"{target}.cbm"
        if not cbm_path.exists():
            raise FileNotFoundError(f"CatBoost model file not found: {joblib_path} or {cbm_path}")
        model = deps["cb"].CatBoostRegressor() if is_regression else deps["cb"].CatBoostClassifier()
        model.load_model(cbm_path)
        return model

    raise ValueError(f"Unknown model family: {family}")


def pin_single_thread(model):
    """Best-effort single-threaded scoring across families (n_jobs / thread_count /
    sklearn Pipeline inner estimator)."""
    for params in ({"n_jobs": 1}, {"model__n_jobs": 1}, {"thread_count": 1}):
        try:
            model.set_params(**params)
            return
        except Exception:
            continue


def load_all_hybrid_models(args, deps):
    models = {}
    for target, family in HYBRID_MODEL_MAPPING.items():
        models_dir = resolve_models_dir(family, args)
        model = load_hybrid_model(target, family, models_dir, deps)
        pin_single_thread(model)
        models[target] = model
    return models


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

    models = load_all_hybrid_models(args, deps)
    classification, regression = run_predictions(
        feature_row,
        models,
        CLASSIFICATION_TARGETS,
        REGRESSION_TARGETS,
        LOG_DISTANCE_TARGETS,
    )
    output = build_output(event, feature_row, classification, regression, len(history))
    # Annotate which family served each target (the ensemble's defining feature).
    output["model_selection"] = dict(HYBRID_MODEL_MAPPING)
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
