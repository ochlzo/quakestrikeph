import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_INPUT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_OUTPUT_DIR = Path("src/outputs/xgboost/models_mc_1_0")
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
# Backward-compatible alias: the single-target predict / backtest helpers import
# this and only use the magnitude regressor (distance routing lives in src/seis).
REGRESSION_TARGET = REGRESSION_TARGETS[0]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Train XGBoost aftershock likelihood and magnitude models "
            "from the existing leakage-safe mc_1_0 training dataset."
        )
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-end-year", type=int, default=2023)
    parser.add_argument("--validation-year", type=int, default=2024)
    parser.add_argument("--test-start-year", type=int, default=2025)
    parser.add_argument("--n-estimators", type=int, default=1200)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--subsample", type=float, default=0.85)
    parser.add_argument("--colsample-bytree", type=float, default=0.85)
    parser.add_argument("--min-child-weight", type=float, default=2.0)
    parser.add_argument("--reg-lambda", type=float, default=1.0)
    parser.add_argument("--early-stopping-rounds", type=int, default=100)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--max-train-rows", type=int, default=0)
    parser.add_argument("--max-validation-rows", type=int, default=0)
    parser.add_argument("--max-test-rows", type=int, default=0)
    return parser.parse_args()


def require_training_dependencies():
    try:
        import joblib
        import xgboost as xgb
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
            "Training requires xgboost, scikit-learn, pandas, numpy, and joblib. "
            "Install them with `python -m pip install -r requirements-xgboost.txt`."
        ) from error

    return {
        "joblib": joblib,
        "xgb": xgb,
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


def scale_pos_weight(y):
    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    if positives == 0:
        return 1.0
    return float(negatives / positives)


def best_iteration(model):
    iteration = getattr(model, "best_iteration", None)
    if iteration is None:
        iteration = getattr(model, "best_iteration_", None)
    if iteration is None:
        return None
    return int(iteration)


def write_feature_importances(model, feature_columns, output_path):
    importances = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)
    importances.to_csv(output_path, index=False)


def train_classifier(target, train, validation, test, feature_columns, output_dir, args, deps):
    xgb = deps["xgb"]
    joblib = deps["joblib"]
    if train[target].nunique() < 2:
        print(f"Skipping {target}; training split has only one class.")
        return None

    model = xgb.XGBClassifier(
        objective="binary:logistic",
        eval_metric="logloss",
        tree_method="hist",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
        min_child_weight=args.min_child_weight,
        reg_lambda=args.reg_lambda,
        scale_pos_weight=scale_pos_weight(train[target].to_numpy()),
        early_stopping_rounds=args.early_stopping_rounds,
        random_state=args.random_state,
        n_jobs=-1,
    )
    model.fit(
        train[feature_columns],
        train[target],
        eval_set=[(validation[feature_columns], validation[target])],
        verbose=False,
    )

    validation_probability = model.predict_proba(validation[feature_columns])[:, 1]
    test_probability = model.predict_proba(test[feature_columns])[:, 1]
    model_path = output_dir / f"{target}.joblib"
    json_model_path = output_dir / f"{target}.json"
    importance_path = output_dir / f"{target}_feature_importances.csv"
    joblib.dump(model, model_path)
    model.save_model(json_model_path)
    write_feature_importances(model, feature_columns, importance_path)

    return {
        "target": target,
        "task": "classification",
        "model_path": str(model_path),
        "json_model_path": str(json_model_path),
        "feature_importances_path": str(importance_path),
        "best_iteration": best_iteration(model),
        "validation": classification_metrics(validation[target].to_numpy(), validation_probability, deps),
        "test": classification_metrics(test[target].to_numpy(), test_probability, deps),
    }


def train_regressor(target, train, validation, test, feature_columns, output_dir, args, deps):
    xgb = deps["xgb"]
    joblib = deps["joblib"]
    train = train.dropna(subset=[target])
    validation = validation.dropna(subset=[target])
    test = test.dropna(subset=[target])

    if train.empty or validation.empty or test.empty:
        print(f"Skipping {target}; one split has no positive aftershock targets.")
        return None

    model = xgb.XGBRegressor(
        objective="reg:squarederror",
        eval_metric="rmse",
        tree_method="hist",
        n_estimators=args.n_estimators,
        learning_rate=args.learning_rate,
        max_depth=args.max_depth,
        subsample=args.subsample,
        colsample_bytree=args.colsample_bytree,
        min_child_weight=args.min_child_weight,
        reg_lambda=args.reg_lambda,
        early_stopping_rounds=args.early_stopping_rounds,
        random_state=args.random_state,
        n_jobs=-1,
    )
    model.fit(
        train[feature_columns],
        train[target],
        eval_set=[(validation[feature_columns], validation[target])],
        verbose=False,
    )

    validation_pred = model.predict(validation[feature_columns])
    test_pred = model.predict(test[feature_columns])
    model_path = output_dir / f"{target}.joblib"
    json_model_path = output_dir / f"{target}.json"
    importance_path = output_dir / f"{target}_feature_importances.csv"
    joblib.dump(model, model_path)
    model.save_model(json_model_path)
    write_feature_importances(model, feature_columns, importance_path)

    return {
        "target": target,
        "task": "regression_positive_cases_only",
        "model_path": str(model_path),
        "json_model_path": str(json_model_path),
        "feature_importances_path": str(importance_path),
        "best_iteration": best_iteration(model),
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
        "model_family": "xgboost",
        "input_csv": str(args.input_csv),
        "feature_columns": feature_columns,
        "hyperparameters": {
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "subsample": args.subsample,
            "colsample_bytree": args.colsample_bytree,
            "min_child_weight": args.min_child_weight,
            "reg_lambda": args.reg_lambda,
            "early_stopping_rounds": args.early_stopping_rounds,
            "random_state": args.random_state,
            "tree_method": "hist",
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
