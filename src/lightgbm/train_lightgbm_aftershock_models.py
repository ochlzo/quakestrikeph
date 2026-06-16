import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_INPUT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_OUTPUT_DIR = Path("src/outputs/lightgbm/models_mc_1_0")
CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]
REGRESSION_TARGETS = [
    "max_aftershock_mag_24h",
    "max_aftershock_distance_km_24h",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train LightGBM aftershock likelihood and magnitude models."
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-end-year", type=int, default=2023)
    parser.add_argument("--validation-year", type=int, default=2024)
    parser.add_argument("--test-start-year", type=int, default=2025)
    return parser.parse_args()


def require_training_dependencies():
    try:
        import joblib
        import lightgbm as lgb
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
            "Training requires lightgbm, scikit-learn, and joblib. "
            "Install them in your Python environment before running this script."
        ) from error

    return {
        "joblib": joblib,
        "lgb": lgb,
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


def train_classifier(target, train, validation, test, feature_columns, output_dir, deps):
    lgb = deps["lgb"]
    joblib = deps["joblib"]
    if train[target].nunique() < 2:
        print(f"Skipping {target}; training split has only one class.")
        return None

    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=2000,
        learning_rate=0.03,
        num_leaves=31,
        subsample=0.85,
        colsample_bytree=0.85,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        train[feature_columns],
        train[target],
        eval_set=[(validation[feature_columns], validation[target])],
        eval_metric="binary_logloss",
        callbacks=[lgb.early_stopping(stopping_rounds=100), lgb.log_evaluation(period=0)],
    )

    validation_probability = model.predict_proba(validation[feature_columns])[:, 1]
    test_probability = model.predict_proba(test[feature_columns])[:, 1]
    model_path = output_dir / f"{target}.joblib"
    text_model_path = output_dir / f"{target}.txt"
    joblib.dump(model, model_path)
    model.booster_.save_model(text_model_path, num_iteration=model.best_iteration_)

    return {
        "target": target,
        "task": "classification",
        "model_path": str(model_path),
        "text_model_path": str(text_model_path),
        "best_iteration": int(model.best_iteration_ or model.n_estimators),
        "validation": classification_metrics(validation[target].to_numpy(), validation_probability, deps),
        "test": classification_metrics(test[target].to_numpy(), test_probability, deps),
    }


def train_regressor(target, train, validation, test, feature_columns, output_dir, deps):
    lgb = deps["lgb"]
    joblib = deps["joblib"]
    train = train.dropna(subset=[target])
    validation = validation.dropna(subset=[target])
    test = test.dropna(subset=[target])

    if train.empty or validation.empty or test.empty:
        print(f"Skipping {target}; one split has no positive aftershock targets.")
        return None

    model = lgb.LGBMRegressor(
        objective="regression",
        n_estimators=2000,
        learning_rate=0.03,
        num_leaves=31,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(
        train[feature_columns],
        train[target],
        eval_set=[(validation[feature_columns], validation[target])],
        eval_metric="l2",
        callbacks=[lgb.early_stopping(stopping_rounds=100), lgb.log_evaluation(period=0)],
    )

    validation_pred = model.predict(validation[feature_columns])
    test_pred = model.predict(test[feature_columns])
    model_path = output_dir / f"{target}.joblib"
    text_model_path = output_dir / f"{target}.txt"
    joblib.dump(model, model_path)
    model.booster_.save_model(text_model_path, num_iteration=model.best_iteration_)

    return {
        "target": target,
        "task": "regression_positive_cases_only",
        "model_path": str(model_path),
        "text_model_path": str(text_model_path),
        "best_iteration": int(model.best_iteration_ or model.n_estimators),
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
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "input_csv": str(args.input_csv),
        "feature_columns": feature_columns,
        "splits": {
            "train_rows": int(len(train)),
            "validation_rows": int(len(validation)),
            "test_rows": int(len(test)),
            "train_end_year": args.train_end_year,
            "validation_year": args.validation_year,
            "test_start_year": args.test_start_year,
        },
        "models": [],
    }

    for target in CLASSIFICATION_TARGETS:
        result = train_classifier(target, train, validation, test, feature_columns, args.output_dir, deps)
        if result is not None:
            metrics["models"].append(result)

    for target in REGRESSION_TARGETS:
        regression_result = train_regressor(target, train, validation, test, feature_columns, args.output_dir, deps)
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
