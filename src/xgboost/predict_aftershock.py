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
# LightGBM predict module, which is the repo's serving base. Reusing them keeps
# every family's prediction JSON identical.
LIGHTGBM_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "lightgbm"
if str(LIGHTGBM_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_SCRIPT_DIR))

from predict_aftershock import (  # noqa: E402
    build_output,
    load_new_event,
    run_predictions,
)
from train_xgboost_aftershock_models import (  # noqa: E402
    CLASSIFICATION_TARGETS,
    DEFAULT_OUTPUT_DIR,
    LOG_DISTANCE_TARGETS,
    REGRESSION_TARGETS,
)


DEFAULT_FEATURE_COLUMNS = DEFAULT_OUTPUT_DIR / "feature_columns.txt"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run XGBoost aftershock inference for one raw earthquake event."
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
        import xgboost as xgb
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "Prediction requires joblib and XGBoost model dependencies. "
            "Install them with `python -m pip install -r requirements-xgboost.txt`."
        ) from error

    return {"joblib": joblib, "xgb": xgb}


def load_model(target, models_dir, deps):
    joblib_path = models_dir / f"{target}.joblib"
    if joblib_path.exists():
        return deps["joblib"].load(joblib_path)

    json_path = models_dir / f"{target}.json"
    if not json_path.exists():
        raise FileNotFoundError(
            f"Model file does not exist: {joblib_path} or {json_path}"
        )

    if target in REGRESSION_TARGETS:
        model = deps["xgb"].XGBRegressor()
    else:
        model = deps["xgb"].XGBClassifier()
    model.load_model(json_path)
    return model


def load_models(models_dir, deps):
    models = {}
    for target in [*CLASSIFICATION_TARGETS, *REGRESSION_TARGETS]:
        model = load_model(target, models_dir, deps)
        if hasattr(model, "set_params"):
            model.set_params(n_jobs=1)
        models[target] = model
    return models


def main():
    args = parse_args()
    deps = require_prediction_dependencies()
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
    models = load_models(args.models_dir, deps)
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
