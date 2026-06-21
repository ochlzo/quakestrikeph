import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Feature engineering (the columns this model consumes) is owned by the shared
# module so training and serving never drift. The training CSV's features were
# built by it via build_training_dataset.py; here we reuse its feature-list
# loader as the single definition of "what columns are features".
SHARED_SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SHARED_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_SCRIPT_DIR))

from feature_engineering import load_feature_columns as load_feature_list  # noqa: E402


DEFAULT_INPUT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_OUTPUT_DIR = Path("src/outputs/random-forest/models_mc_1_0")
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
# Distance regressors are trained in log1p(km) space because the distance cloud
# is heavily right-skewed (p95 ~ 500 km). The saved model therefore predicts
# log1p(km); callers (and the metrics below) apply expm1 to recover kilometres.
LOG_DISTANCE_TARGETS = {
    "nearest_aftershock_distance_km_24h",
    "median_aftershock_distance_km_24h",
    "p90_aftershock_distance_km_24h",
}
# Backward-compatible alias: the single-target predict / backtest helpers import
# this and only use the magnitude regressor (distance routing lives in src/seis).
REGRESSION_TARGET = REGRESSION_TARGETS[0]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Train Random Forest aftershock likelihood and magnitude models "
            "from the existing leakage-safe mc_1_0 training dataset."
        )
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    # Split B: train on 2018-2024, validate on the last full year (2025), test on
    # the freshest (partial) year (2026). Forward-validation on the newest data.
    parser.add_argument("--train-end-year", type=int, default=2024)
    parser.add_argument("--validation-year", type=int, default=2025)
    parser.add_argument("--test-start-year", type=int, default=2026)
    # RF-native defaults: a large bagged forest with sqrt feature subsampling.
    # min_samples_leaf differs by task (4 generalises the regressors better).
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--min-samples-leaf", type=int, default=2)
    parser.add_argument("--regressor-min-samples-leaf", type=int, default=4)
    parser.add_argument("--max-features", default="sqrt")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--max-train-rows", type=int, default=0)
    parser.add_argument("--max-validation-rows", type=int, default=0)
    parser.add_argument("--max-test-rows", type=int, default=0)
    return parser.parse_args()


def require_training_dependencies():
    try:
        import joblib
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.calibration import calibration_curve
        from sklearn.metrics import (
            average_precision_score,
            brier_score_loss,
            log_loss,
            mean_absolute_error,
            mean_squared_error,
            precision_score,
            r2_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.pipeline import Pipeline
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "Training requires scikit-learn, pandas, numpy, and joblib. "
            "Install them with `python -m pip install -r requirements-random-forest.txt`."
        ) from error

    return {
        "joblib": joblib,
        "Pipeline": Pipeline,
        "SimpleImputer": SimpleImputer,
        "RandomForestClassifier": RandomForestClassifier,
        "RandomForestRegressor": RandomForestRegressor,
        "calibration_curve": calibration_curve,
        "average_precision_score": average_precision_score,
        "brier_score_loss": brier_score_loss,
        "log_loss": log_loss,
        "mean_absolute_error": mean_absolute_error,
        "mean_squared_error": mean_squared_error,
        "precision_score": precision_score,
        "r2_score": r2_score,
        "recall_score": recall_score,
        "roc_auc_score": roc_auc_score,
    }


def load_feature_columns(input_csv):
    feature_path = input_csv.with_suffix(".features.txt")
    if not feature_path.exists():
        raise FileNotFoundError(
            f"Feature list does not exist: {feature_path}. "
            "Run src/scripts/build_training_dataset.py first."
        )
    # Parse via the shared feature module so there is one definition of the
    # feature-column manifest across training and serving.
    return load_feature_list(feature_path)


def split_by_year(df, args):
    train = df[df["event_year"] <= args.train_end_year].copy()
    validation = df[df["event_year"] == args.validation_year].copy()
    test = df[df["event_year"] >= args.test_start_year].copy()
    if train.empty or validation.empty or test.empty:
        raise ValueError(
            "Chronological split produced an empty train, validation, or test set. "
            "Adjust --train-end-year, --validation-year, or --test-start-year."
        )
    return train, validation, test


def limit_rows(df, max_rows, random_state):
    if max_rows == 0 or len(df) <= max_rows:
        return df
    if max_rows < 0:
        raise ValueError("Row limits must be >= 0.")
    return (
        df.sample(n=max_rows, random_state=random_state)
        .sort_values(["event_time", "event_id"], kind="mergesort")
        .reset_index(drop=True)
    )


def expected_calibration_error(y_true, y_probability, n_bins=10):
    """Count-weighted ECE over uniform probability bins."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_index = np.clip(np.digitize(y_probability, edges[1:-1]), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        mask = bin_index == b
        if mask.any():
            total += mask.sum() / len(y_probability) * abs(
                y_true[mask].mean() - y_probability[mask].mean()
            )
    return float(total)


def calibration_report(y_true, y_probability, metrics, n_bins=10):
    """Reliability self-check for a Path B (natural-prevalence) classifier.

    Returns the sklearn calibration_curve points (predicted vs observed per bin),
    ECE, and log loss. No correction is applied -- this only measures how well the
    raw Random Forest probabilities are calibrated when trained at natural
    prevalence (RF is not a log-loss learner, so this is the honest check on
    whether a post-hoc step would have been warranted).
    """
    prob_true, prob_pred = metrics["calibration_curve"](
        y_true, y_probability, n_bins=n_bins, strategy="uniform"
    )
    return {
        "n_bins": n_bins,
        "ece": expected_calibration_error(y_true, y_probability, n_bins),
        "log_loss": float(
            metrics["log_loss"](y_true, np.clip(y_probability, 1e-7, 1 - 1e-7))
        ),
        "reliability_pred": [float(v) for v in prob_pred],
        "reliability_obs": [float(v) for v in prob_true],
    }


def classification_metrics(y_true, y_probability, metrics):
    y_pred = (y_probability >= 0.5).astype(int)
    results = {
        "positive_rate": float(np.mean(y_true)),
        "predicted_positive_rate_at_0_5": float(np.mean(y_pred)),
        "brier": float(metrics["brier_score_loss"](y_true, y_probability)),
        "precision_at_0_5": float(metrics["precision_score"](y_true, y_pred, zero_division=0)),
        "recall_at_0_5": float(metrics["recall_score"](y_true, y_pred, zero_division=0)),
    }
    if len(np.unique(y_true)) == 2:
        results["roc_auc"] = float(metrics["roc_auc_score"](y_true, y_probability))
        results["average_precision"] = float(metrics["average_precision_score"](y_true, y_probability))
        results["calibration"] = calibration_report(y_true, y_probability, metrics)
    else:
        results["roc_auc"] = None
        results["average_precision"] = None
        results["calibration"] = None
    return results


def regression_metrics(y_true, y_pred, metrics):
    mse = metrics["mean_squared_error"](y_true, y_pred)
    return {
        "mae": float(metrics["mean_absolute_error"](y_true, y_pred)),
        "rmse": float(np.sqrt(mse)),
        "r2": float(metrics["r2_score"](y_true, y_pred)),
        "target_mean": float(np.mean(y_true)),
    }


def positive_class_probability(model, rows):
    estimator = model.named_steps["model"]
    probabilities = model.predict_proba(rows)
    class_positions = {label: index for index, label in enumerate(estimator.classes_)}
    if 1 not in class_positions:
        return np.zeros(len(rows), dtype=float)
    return probabilities[:, class_positions[1]]


def build_classifier(args, deps):
    # Path B: natural prevalence (no class_weight) and NO post-hoc calibration --
    # the raw forest vote-fraction is reported as the probability and checked by
    # calibration_report(). RF needs the median imputer because, unlike the GBMs,
    # it cannot consume the NaN features the catalog produces (e.g. local maxima
    # with no nearby history).
    return deps["Pipeline"](
        steps=[
            ("imputer", deps["SimpleImputer"](strategy="median")),
            (
                "model",
                deps["RandomForestClassifier"](
                    n_estimators=args.n_estimators,
                    max_depth=args.max_depth,
                    min_samples_leaf=args.min_samples_leaf,
                    max_features=args.max_features,
                    random_state=args.random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def build_regressor(args, deps):
    return deps["Pipeline"](
        steps=[
            ("imputer", deps["SimpleImputer"](strategy="median")),
            (
                "model",
                deps["RandomForestRegressor"](
                    n_estimators=args.n_estimators,
                    max_depth=args.max_depth,
                    min_samples_leaf=args.regressor_min_samples_leaf,
                    max_features=args.max_features,
                    random_state=args.random_state,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def write_feature_importances(model, feature_columns, output_path):
    estimator = model.named_steps["model"]
    importances = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": estimator.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    importances.to_csv(output_path, index=False)


def train_classifier(target, train, validation, test, feature_columns, output_dir, args, deps):
    joblib = deps["joblib"]
    if train[target].nunique() < 2:
        print(f"Skipping {target}; training split has only one class.")
        return None

    model = build_classifier(args, deps)
    model.fit(train[feature_columns], train[target])

    validation_probability = positive_class_probability(model, validation[feature_columns])
    test_probability = positive_class_probability(model, test[feature_columns])
    model_path = output_dir / f"{target}.joblib"
    importance_path = output_dir / f"{target}_feature_importances.csv"
    joblib.dump(model, model_path)
    write_feature_importances(model, feature_columns, importance_path)

    return {
        "target": target,
        "task": "classification",
        "model_path": str(model_path),
        "feature_importances_path": str(importance_path),
        "validation": classification_metrics(validation[target].to_numpy(), validation_probability, deps),
        "test": classification_metrics(test[target].to_numpy(), test_probability, deps),
    }


def train_regressor(target, train, validation, test, feature_columns, output_dir, args, deps):
    joblib = deps["joblib"]
    train = train.dropna(subset=[target])
    validation = validation.dropna(subset=[target])
    test = test.dropna(subset=[target])

    if train.empty or validation.empty or test.empty:
        print(f"Skipping {target}; one split has no positive aftershock targets.")
        return None

    # Heavy-tailed distance targets are learned in log1p(km) space; magnitude is
    # left on its natural scale.
    use_log = target in LOG_DISTANCE_TARGETS
    y_train = np.log1p(train[target].to_numpy()) if use_log else train[target].to_numpy()

    model = build_regressor(args, deps)
    model.fit(train[feature_columns], y_train)

    validation_pred = model.predict(validation[feature_columns])
    test_pred = model.predict(test[feature_columns])
    if use_log:
        # Back-transform to kilometres so metrics are reported on the natural
        # scale; clip the tiny negatives expm1 can produce near zero.
        validation_pred = np.clip(np.expm1(validation_pred), 0.0, None)
        test_pred = np.clip(np.expm1(test_pred), 0.0, None)
    model_path = output_dir / f"{target}.joblib"
    importance_path = output_dir / f"{target}_feature_importances.csv"
    joblib.dump(model, model_path)
    write_feature_importances(model, feature_columns, importance_path)

    return {
        "target": target,
        "task": "regression_positive_cases_only",
        "target_transform": "log1p" if use_log else "identity",
        "model_path": str(model_path),
        "feature_importances_path": str(importance_path),
        "validation": regression_metrics(validation[target].to_numpy(), validation_pred, deps),
        "test": regression_metrics(test[target].to_numpy(), test_pred, deps),
    }


def main():
    args = parse_args()
    if not args.input_csv.exists():
        raise FileNotFoundError(
            f"Input CSV does not exist: {args.input_csv}. "
            "Run src/scripts/build_training_dataset.py first."
        )

    deps = require_training_dependencies()
    feature_columns = load_feature_columns(args.input_csv)
    df = pd.read_csv(args.input_csv, low_memory=False)
    missing_columns = sorted(set(feature_columns + CLASSIFICATION_TARGETS + REGRESSION_TARGETS) - set(df.columns))
    if missing_columns:
        raise ValueError(f"Training CSV is missing columns: {missing_columns}")

    train, validation, test = split_by_year(df, args)
    train = limit_rows(train, args.max_train_rows, args.random_state)
    validation = limit_rows(validation, args.max_validation_rows, args.random_state + 1)
    test = limit_rows(test, args.max_test_rows, args.random_state + 2)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "model_family": "random_forest",
        "input_csv": str(args.input_csv),
        "feature_columns": feature_columns,
        "hyperparameters": {
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "min_samples_leaf": args.min_samples_leaf,
            "regressor_min_samples_leaf": args.regressor_min_samples_leaf,
            "max_features": args.max_features,
            "random_state": args.random_state,
            "imputer": "median",
            "class_weight": None,
            "calibration": "natural_prevalence_path_b",
        },
        "splits": {
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "test_rows": int(len(test)),
            "train_end_year": args.train_end_year,
            "validation_year": args.validation_year,
            "test_start_year": args.test_start_year,
            "max_train_rows": args.max_train_rows,
            "max_validation_rows": args.max_validation_rows,
            "max_test_rows": args.max_test_rows,
        },
        "models": [],
    }

    for target in CLASSIFICATION_TARGETS:
        result = train_classifier(target, train, validation, test, feature_columns, args.output_dir, args, deps)
        if result is not None:
            metrics["models"].append(result)
            calib = result["test"].get("calibration")
            if calib is not None:
                print(
                    f"  [calib] {target:<32} test ECE={calib['ece']:.4f} "
                    f"logloss={calib['log_loss']:.4f} "
                    f"Brier={result['test']['brier']:.4f} "
                    f"ROC={result['test']['roc_auc']:.4f}"
                )

    for regression_target in REGRESSION_TARGETS:
        regression_result = train_regressor(
            regression_target, train, validation, test, feature_columns, args.output_dir, args, deps
        )
        if regression_result is not None:
            metrics["models"].append(regression_result)

    metrics_path = args.output_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (args.output_dir / "feature_columns.txt").write_text(
        "\n".join(feature_columns) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote metrics: {metrics_path}")
    print(f"Trained models: {len(metrics['models'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
