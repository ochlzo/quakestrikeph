"""Honest per-family backtest of the SEIS base models on the 2025+ holdout.

This produces an honest out-of-sample evaluation of each base family (XGBoost,
LightGBM, Random Forest, CatBoost) -- it does NOT select a per-target winner. Model
selection is done separately and honestly on 2024 by ``repick_bins.py``; this
script only measures how each family performs on data it never saw.

Two properties make the scores honest:

1. **No holdout-selected mapping.** Every family is scored on every target;
   nothing here picks a per-target winner on the 2025+ pool (the circular
   hindsight selection the old report did). Evaluating one fixed family on 2025+
   involves no selection -- the base models trained only on <=2023.

2. **Natural prevalence.** The default sampling is ``chronological`` (and
   ``--max-events 0`` scores the whole pool), so Brier/precision are at the real
   deployment base rate, not the inflated ``balanced`` rate.

Scoring is **batched**: the production feature matrix is built once for the
pool, then every family is vectorized-scored over it -- minutes for the full
29,720-event pool, versus hours for a per-event Python loop.
"""

import argparse
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

SEIS_DIR = Path(__file__).resolve().parent
if str(SEIS_DIR) not in sys.path:
    sys.path.insert(0, str(SEIS_DIR))

from predict import (
    DEFAULT_B_VALUE,
    DEFAULT_CALIBRATORS_DIR,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_HISTORICAL_CSV,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    load_feature_columns,
    load_hybrid_model,
    normalize_raw_catalog,
    require_dependencies,
)
from calibration_score import build_feature_matrix, batch_positive_probability

LIGHTGBM_DIR = SEIS_DIR.parent / "lightgbm"
if str(LIGHTGBM_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_DIR))

from backtest_aftershock_predictions import (
    DEFAULT_INPUT_CSV,
    load_labeled_events,
    sample_events,
)

DEFAULT_FEATURE_COLUMNS = Path("src/outputs/lightgbm/models_mc_1_0/feature_columns.txt")
DEFAULT_BACKTEST_OUTPUT_DIR = Path("src/outputs/seis/backtests_mc_1_0")

FAMILIES = ["xgboost", "lightgbm", "random_forest", "catboost"]

CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]
REGRESSION_TARGETS = ["max_aftershock_mag_24h", "max_aftershock_distance_km_24h"]


def sanitize_json_value(value):
    if isinstance(value, float) and not pd.notna(value):
        return None
    if isinstance(value, dict):
        return {key: sanitize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    return value


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--xgb-models-dir", type=Path, default=Path("src/outputs/xgboost/models_mc_1_0"))
    parser.add_argument("--lgb-models-dir", type=Path, default=Path("src/outputs/lightgbm/models_mc_1_0"))
    parser.add_argument("--rf-models-dir", type=Path, default=Path("src/outputs/random-forest/models_mc_1_0"))
    parser.add_argument("--cb-models-dir", type=Path, default=Path("src/outputs/catboost/models_mc_1_0"))
    parser.add_argument("--calibrators-dir", type=Path, default=DEFAULT_CALIBRATORS_DIR)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_BACKTEST_OUTPUT_DIR)
    parser.add_argument("--test-start-year", type=int, default=2025)
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Maximum labeled events to backtest. 0 = the whole 2025+ pool (honest).",
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


def require_metric_dependencies():
    try:
        from sklearn.metrics import (
            average_precision_score,
            brier_score_loss,
            mean_absolute_error,
            mean_squared_error,
            r2_score,
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
        "r2_score": r2_score,
        "roc_auc_score": roc_auc_score,
    }


def family_dir(args, family):
    return {
        "xgboost": args.xgb_models_dir,
        "lightgbm": args.lgb_models_dir,
        "random_forest": args.rf_models_dir,
        "catboost": args.cb_models_dir,
    }[family]


def load_honest_models(args, deps):
    """Load every family's classifiers, regressors, and calibrators."""
    joblib = deps["joblib"]
    cls, reg, cal = {}, {}, {}
    for family in FAMILIES:
        models_dir = family_dir(args, family)
        cls[family], reg[family], cal[family] = {}, {}, {}
        for target in CLASSIFICATION_TARGETS:
            model = load_hybrid_model(target, family, models_dir, deps)
            if hasattr(model, "set_params"):
                try:
                    model.set_params(n_jobs=-1)
                except Exception:
                    pass
            cls[family][target] = model
            cal_path = args.calibrators_dir / f"{family}__{target}.joblib"
            if not cal_path.exists():
                raise FileNotFoundError(f"Calibrator not found: {cal_path}")
            cal[family][target] = joblib.load(cal_path)
        for target in REGRESSION_TARGETS:
            reg[family][target] = load_hybrid_model(target, family, models_dir, deps)
    return {"cls": cls, "reg": reg, "cal": cal}


def expected_calibration_error(y_true, y_prob, n_bins=10):
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(y_prob, bins[1:-1]), 0, n_bins - 1)
    ece, n = 0.0, len(y_prob)
    for b in range(n_bins):
        mask = idx == b
        if mask.any():
            ece += (mask.sum() / n) * abs(y_prob[mask].mean() - y_true[mask].mean())
    return float(ece)


def cls_metrics(y_true, y_prob, m):
    y_true = np.asarray(y_true, dtype=int)
    y_prob = np.asarray(y_prob, dtype=float)
    out = {
        "count": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "brier": float(m["brier_score_loss"](y_true, y_prob)),
        "ece": expected_calibration_error(y_true, y_prob),
    }
    if len(np.unique(y_true)) == 2:
        out["roc_auc"] = float(m["roc_auc_score"](y_true, y_prob))
        out["average_precision"] = float(m["average_precision_score"](y_true, y_prob))
    else:
        out["roc_auc"] = out["average_precision"] = None
    return out


def reg_metrics(y_true, y_pred, m):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mask = ~np.isnan(y_true)
    if not mask.any():
        return {"count": 0}
    yt, yp = y_true[mask], y_pred[mask]
    return {
        "count": int(mask.sum()),
        "mae": float(m["mean_absolute_error"](yt, yp)),
        "rmse": float(np.sqrt(m["mean_squared_error"](yt, yp))),
        "r2": float(m["r2_score"](yt, yp)),
        "actual_mean": float(yt.mean()),
        "predicted_mean": float(yp.mean()),
    }


def main():
    args = parse_args()
    deps = require_dependencies()
    metric_deps = require_metric_dependencies()
    feature_columns = load_feature_columns(args.feature_columns)

    print(f"Loading models (all {len(FAMILIES)} families)...", flush=True)
    honest = load_honest_models(args, deps)

    print("Loading catalog + labeled pool...", flush=True)
    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))
    labeled = load_labeled_events(args.labeled_csv, args.test_start_year, args.minimum_magnitude)
    sampled = sample_events(labeled, args.max_events, args.sample_mode, args.random_seed).reset_index(drop=True)
    print(f"Pool: {len(sampled)} events (prevalence-preserving '{args.sample_mode}').", flush=True)

    # Build the production feature matrix ONCE for the whole pool.
    print("Building production features (once)...", flush=True)
    X, meta_df, cls_labels = build_feature_matrix(sampled, history, args, feature_columns)

    # Batch-score every family and calibrate. No ensemble, no selection here.
    print("Batch-scoring families...", flush=True)
    out = meta_df.copy()
    per_family_cls = {f: {} for f in FAMILIES}
    for target in CLASSIFICATION_TARGETS:
        out[f"actual_{target}"] = cls_labels[target].to_numpy(dtype=int)
        for family in FAMILIES:
            raw = batch_positive_probability(honest["cls"][family][target], X)
            calibrated = honest["cal"][family][target].predict(raw)
            per_family_cls[family][target] = np.asarray(calibrated, dtype=float)
            out[f"prob_{family}_{target}"] = per_family_cls[family][target]

    per_family_reg = {f: {} for f in FAMILIES}
    for target in REGRESSION_TARGETS:
        out[f"actual_{target}"] = sampled[target].to_numpy(dtype=float)
        for family in FAMILIES:
            p = np.asarray(honest["reg"][family][target].predict(X), dtype=float)
            if target == "max_aftershock_distance_km_24h":
                p = np.clip(p, 0.0, None)
            per_family_reg[family][target] = p
            out[f"pred_{family}_{target}"] = p

    # Metrics (per family only).
    print("Computing metrics...", flush=True)
    summary = {
        "config": {
            "model_family": "seis_per_family_honest_backtest",
            "selection": "none here -- families are re-picked honestly on 2024 by repick_bins.py",
            "labeled_csv": str(args.labeled_csv),
            "historical_csv": str(args.historical_csv),
            "calibrators_dir": str(args.calibrators_dir),
            "test_start_year": args.test_start_year,
            "max_events": args.max_events,
            "sample_mode": args.sample_mode,
            "sampled_rows": int(len(sampled)),
            "candidate_rows": int(len(labeled)),
            "minimum_magnitude": args.minimum_magnitude,
        },
        "metrics": {
            "classification_per_family": {f: {} for f in FAMILIES},
            "regression_per_family": {f: {} for f in FAMILIES},
        },
    }
    me = summary["metrics"]
    for target in CLASSIFICATION_TARGETS:
        y = out[f"actual_{target}"].to_numpy()
        for family in FAMILIES:
            me["classification_per_family"][family][target] = cls_metrics(
                y, per_family_cls[family][target], metric_deps
            )
    for target in REGRESSION_TARGETS:
        y = out[f"actual_{target}"].to_numpy(dtype=float)
        for family in FAMILIES:
            me["regression_per_family"][family][target] = reg_metrics(
                y, per_family_reg[family][target], metric_deps
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = args.output_dir / "backtest_predictions.csv"
    metrics_path = args.output_dir / "backtest_metrics.json"
    out.to_csv(predictions_path, index=False)
    metrics_path.write_text(
        json.dumps(sanitize_json_value(summary), indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Wrote {predictions_path}")
    print(f"Wrote {metrics_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
