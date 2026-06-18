"""Score all three model families over the full deployment pool.

Runs the *production* feature path (rebuilding features from the raw catalog
per event, exactly as ``predict.py`` does at inference time) over every event
in the 2025+ holdout pool, then batch-scores each family's seven classification
targets. The output is a wide CSV of true labels and predicted probabilities at
the natural pool prevalence -- the deployment-faithful input for calibration
analysis.

Why the production path and not the precomputed training-dataset features:
``build_training_dataset.py`` assigns the parent from the precomputed
Zaliapin-Ben-Zion clustering (``parent_id_key``), whereas the production
inference path re-derives the nearest-neighbor parent by scanning prior history
(``compute_parent_features``). The two yield different ``eta`` / ``parent_*``
feature values (a train/serve skew), so only the rebuilt production features
reflect what the deployed model actually sees.
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

SEIS_DIR = Path(__file__).resolve().parent
if str(SEIS_DIR) not in sys.path:
    sys.path.insert(0, str(SEIS_DIR))
LIGHTGBM_DIR = SEIS_DIR.parent / "lightgbm"
if str(LIGHTGBM_DIR) not in sys.path:
    sys.path.insert(0, str(LIGHTGBM_DIR))

from predict_aftershock import (  # noqa: E402
    DEFAULT_B_VALUE,
    DEFAULT_FRACTAL_DIMENSION,
    DEFAULT_LOG10_ETA0,
    DEFAULT_MIN_MAGNITUDE,
    build_prediction_features,
    filter_history_for_prediction,
    load_feature_columns,
    normalize_raw_catalog,
)
from predict import (  # noqa: E402
    CLASSIFICATION_TARGETS,
    DEFAULT_LGB_DIR,
    DEFAULT_RF_DIR,
    DEFAULT_XGB_DIR,
    load_hybrid_model,
    require_dependencies,
)

DEFAULT_LABELED_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_HISTORICAL_CSV = Path("dataset/phivolcs_earthquake_2018_2026.csv")
DEFAULT_FEATURE_COLUMNS = DEFAULT_LGB_DIR / "feature_columns.txt"
DEFAULT_OUTPUT_CSV = Path("src/outputs/seis/calibration/full_pool_predictions.csv")

FAMILY_DIRS = {
    "xgboost": DEFAULT_XGB_DIR,
    "lightgbm": DEFAULT_LGB_DIR,
    "random_forest": DEFAULT_RF_DIR,
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labeled-csv", type=Path, default=DEFAULT_LABELED_CSV)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--test-start-year", type=int, default=2025)
    parser.add_argument("--minimum-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--fractal-dimension", type=float, default=DEFAULT_FRACTAL_DIMENSION)
    parser.add_argument("--log10-eta0", type=float, default=DEFAULT_LOG10_ETA0)
    parser.add_argument(
        "--max-events",
        type=int,
        default=0,
        help="Cap the number of pool events scored (0 = full pool). Useful for smoke tests.",
    )
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def load_pool(labeled_csv, test_start_year, minimum_magnitude, max_events, random_seed):
    df = pd.read_csv(labeled_csv, low_memory=False)
    df["event_time"] = pd.to_datetime(df["event_time"], errors="coerce")
    df = df.dropna(subset=["event_time", "latitude", "longitude", "depth_km", "magnitude"])
    pool = df[
        (df["event_year"] >= test_start_year) & (df["magnitude"] >= minimum_magnitude)
    ].copy()
    pool = pool.sort_values(["event_time", "event_id"], kind="mergesort").reset_index(drop=True)
    if max_events and max_events > 0 and len(pool) > max_events:
        # Random natural-rate sample (NOT balanced) so prevalence matches deployment.
        pool = pool.sample(n=max_events, random_state=random_seed).sort_values(
            ["event_time", "event_id"], kind="mergesort"
        ).reset_index(drop=True)
    return pool


def load_all_family_models(args, deps):
    models = {}
    for family, models_dir in FAMILY_DIRS.items():
        models[family] = {}
        for target in CLASSIFICATION_TARGETS:
            model = load_hybrid_model(target, family, models_dir, deps)
            # Single-row inference in the loop is cheap; keep threading off to avoid overhead.
            if hasattr(model, "set_params"):
                try:
                    model.set_params(n_jobs=1)
                except Exception:
                    pass
            models[family][target] = model
    return models


def build_feature_matrix(pool, history, args, feature_columns):
    """Run the production feature builder per event; return X + metadata + labels."""
    feat_args = argparse.Namespace(
        b_value=args.b_value,
        fractal_dimension=args.fractal_dimension,
        log10_eta0=args.log10_eta0,
    )
    feature_rows = []
    meta = []
    t0 = time.time()
    for index, row in pool.iterrows():
        event = {
            "event_time": row["event_time"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "depth_km": float(row["depth_km"]),
            "magnitude": float(row["magnitude"]),
        }
        prediction_history = filter_history_for_prediction(
            history, event["event_time"], args.minimum_magnitude
        )
        feature_row = build_prediction_features(
            prediction_history, event, feat_args, feature_columns
        )
        feature_rows.append(feature_row.iloc[0])
        meta.append(
            {
                "event_id": row["event_id"],
                "event_time": row["event_time"].isoformat(),
                "magnitude": float(row["magnitude"]),
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
        )
        if (index + 1) % 1000 == 0:
            elapsed = time.time() - t0
            rate = (index + 1) / elapsed
            remaining = (len(pool) - index - 1) / rate
            print(
                f"  features {index + 1}/{len(pool)} "
                f"({rate:.1f}/s, ~{remaining / 60:.1f} min remaining)",
                flush=True,
            )
    X = pd.DataFrame(feature_rows, columns=feature_columns)
    meta_df = pd.DataFrame(meta)
    labels = pool[CLASSIFICATION_TARGETS].astype(int).reset_index(drop=True)
    print(f"  built {len(X)} feature rows in {(time.time() - t0) / 60:.1f} min", flush=True)
    return X, meta_df, labels


def batch_positive_probability(model, X):
    """Vectorized positive-class probability for a single model over many rows.

    Handles sklearn Pipelines (Random Forest) and bare classifiers
    (XGBoost/LightGBM), indexing by the classifier's ``classes_``.
    """
    probabilities = model.predict_proba(X)
    classifier = model.named_steps["model"] if hasattr(model, "named_steps") else model
    class_positions = {label: idx for idx, label in enumerate(classifier.classes_)}
    if 1 not in class_positions:
        return np.zeros(len(X), dtype=float)
    return probabilities[:, class_positions[1]]


def score_families(models, X):
    probs = {}
    for family, target_models in models.items():
        print(f"  scoring {family}...", flush=True)
        for target, model in target_models.items():
            probs[f"prob_{family}_{target}"] = batch_positive_probability(model, X)
    return pd.DataFrame(probs)


def main():
    args = parse_args()
    deps = require_dependencies()
    feature_columns = load_feature_columns(args.feature_columns)

    print("Loading historical catalog...", flush=True)
    history = normalize_raw_catalog(pd.read_csv(args.historical_csv, low_memory=False))
    print(f"  {len(history)} history rows", flush=True)

    pool = load_pool(
        args.labeled_csv,
        args.test_start_year,
        args.minimum_magnitude,
        args.max_events,
        args.random_seed,
    )
    print(f"Pool: {len(pool)} events (test_start_year={args.test_start_year}, "
          f"mc>={args.minimum_magnitude})", flush=True)

    print("Loading models for all three families...", flush=True)
    models = load_all_family_models(args, deps)

    print("Building production features per event...", flush=True)
    X, meta_df, labels = build_feature_matrix(pool, history, args, feature_columns)

    print("Batch-scoring families...", flush=True)
    probs_df = score_families(models, X)

    out = pd.concat([meta_df, labels, probs_df], axis=1)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.output_csv, index=False)
    print(f"Wrote {args.output_csv} ({len(out)} rows, {len(out.columns)} cols)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
