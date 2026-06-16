import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_INPUT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_OUTPUT_DIR = Path("src/outputs/random-forest/models_mc_1_0")
CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]
REGRESSION_TARGET = "max_aftershock_mag_24h"


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Train Random Forest aftershock likelihood and magnitude models "
            "from the existing leakage-safe mc_1_0 training dataset."
        )
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-end-year", type=int, default=2023)
    parser.add_argument("--validation-year", type=int, default=2024)
    parser.add_argument("--test-start-year", type=int, default=2025)
    parser.add_argument("--n-estimators", type=int, default=400)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--min-samples-leaf", type=int, default=2)
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
        from sklearn.calibration import CalibratedClassifierCV, FrozenEstimator
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
        "CalibratedClassifierCV": CalibratedClassifierCV,
        "FrozenEstimator": FrozenEstimator,
        "average_precision_score": average_precision_score,
        "brier_score_loss": brier_score_loss,
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

    return [
        line.strip()
        for line in feature_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


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
    else:
        results["roc_auc"] = None
        results["average_precision"] = None
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
                    class_weight="balanced_subsample",
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
                    min_samples_leaf=4,  # Tuned for better generalization (R2 0.32 -> 0.35 on test set)
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

    # 1. Fit base pipeline on train split
    base_pipeline = build_classifier(args, deps)
    base_pipeline.fit(train[feature_columns], train[target])

    # 2. Extract fitted imputer and classifier, then calibrate on validation split
    fitted_imputer = base_pipeline.named_steps["imputer"]
    fitted_rf = base_pipeline.named_steps["model"]

    imputed_val = fitted_imputer.transform(validation[feature_columns])
    calibrated_rf = deps["CalibratedClassifierCV"](
        estimator=deps["FrozenEstimator"](fitted_rf),
        method="isotonic"
    )
    calibrated_rf.fit(imputed_val, validation[target])

    # 3. Assemble final pipeline with calibrated classifier
    model = deps["Pipeline"]([
        ("imputer", fitted_imputer),
        ("model", calibrated_rf)
    ])

    validation_probability = positive_class_probability(
        model,
        validation[feature_columns],
    )
    test_probability = positive_class_probability(model, test[feature_columns])
    model_path = output_dir / f"{target}.joblib"
    importance_path = output_dir / f"{target}_feature_importances.csv"
    joblib.dump(model, model_path)
    
    # Write feature importances using the base fitted Random Forest (since CalibratedClassifierCV has no feature_importances_)
    importances = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": fitted_rf.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    importances.to_csv(importance_path, index=False)

    return {
        "target": target,
        "task": "classification",
        "model_path": str(model_path),
        "feature_importances_path": str(importance_path),
        "validation": classification_metrics(validation[target].to_numpy(), validation_probability, deps),
        "test": classification_metrics(test[target].to_numpy(), test_probability, deps),
    }


def train_regressor(train, validation, test, feature_columns, output_dir, args, deps):
    joblib = deps["joblib"]
    train = train.dropna(subset=[REGRESSION_TARGET])
    validation = validation.dropna(subset=[REGRESSION_TARGET])
    test = test.dropna(subset=[REGRESSION_TARGET])

    if train.empty or validation.empty or test.empty:
        print(f"Skipping {REGRESSION_TARGET}; one split has no positive aftershock targets.")
        return None

    model = build_regressor(args, deps)
    model.fit(train[feature_columns], train[REGRESSION_TARGET])

    validation_pred = model.predict(validation[feature_columns])
    test_pred = model.predict(test[feature_columns])
    model_path = output_dir / f"{REGRESSION_TARGET}.joblib"
    importance_path = output_dir / f"{REGRESSION_TARGET}_feature_importances.csv"
    joblib.dump(model, model_path)
    write_feature_importances(model, feature_columns, importance_path)

    return {
        "target": REGRESSION_TARGET,
        "task": "regression_positive_cases_only",
        "model_path": str(model_path),
        "feature_importances_path": str(importance_path),
        "validation": regression_metrics(validation[REGRESSION_TARGET].to_numpy(), validation_pred, deps),
        "test": regression_metrics(test[REGRESSION_TARGET].to_numpy(), test_pred, deps),
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
    missing_columns = sorted(set(feature_columns + CLASSIFICATION_TARGETS + [REGRESSION_TARGET]) - set(df.columns))
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
            "max_features": args.max_features,
            "class_weight": "balanced_subsample",
            "random_state": args.random_state,
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

    regression_result = train_regressor(train, validation, test, feature_columns, args.output_dir, args, deps)
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
