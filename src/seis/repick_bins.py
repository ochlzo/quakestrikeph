"""Pick the deployed family per target on a held-out evaluation set.

Each family is compared on data the base models were not trained on, and the
best-scoring family per target is deployed:

  * Classification: calibrated Brier estimated by 5-fold OUT-OF-FOLD isotonic
    calibration on validation_raw_predictions.csv. In-fold calibration avoids
    in-sample optimism and treats every family identically. Lowest Brier wins.
  * Regression: validation R^2 from each family's metrics.json. Highest R^2 wins.

Outputs repick_report.json (full per-family metrics + the deployed mapping) and
prints a table.
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

FAMILIES = ["xgboost", "lightgbm", "random_forest"]
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

DEFAULT_VAL_PREDICTIONS = Path(
    "src/outputs/seis/calibration/calibrators/validation_raw_predictions.csv"
)
DEFAULT_FAMILY_METRICS = {
    "xgboost": Path("src/outputs/xgboost/models_mc_1_0/metrics.json"),
    "lightgbm": Path("src/outputs/lightgbm/models_mc_1_0/metrics.json"),
    "random_forest": Path("src/outputs/random-forest/models_mc_1_0/metrics.json"),
}
DEFAULT_OUTPUT = Path("src/outputs/seis/calibration/repick_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--val-predictions", type=Path, default=DEFAULT_VAL_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def oof_calibrated_probs(raw, y, n_splits, seed):
    """5-fold out-of-fold isotonic-calibrated probabilities on 2024 (no in-sample leak)."""
    from sklearn.isotonic import IsotonicRegression
    from sklearn.model_selection import StratifiedKFold

    raw = np.asarray(raw, dtype=float)
    y = np.asarray(y, dtype=int)
    oof = np.zeros(len(y), dtype=float)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr, te in skf.split(raw.reshape(-1, 1), y):
        iso = IsotonicRegression(out_of_bounds="clip").fit(raw[tr], y[tr])
        oof[te] = iso.predict(raw[te])
    return oof


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


def metrics_2024(raw, y, n_splits, seed, deps):
    """Full held-out 2024 metrics for one family/target.

    Brier and ECE use out-of-fold isotonic-calibrated probabilities; ROC-AUC and
    Average Precision are rank-based and use the raw probabilities.
    """
    raw = np.asarray(raw, dtype=float)
    y = np.asarray(y, dtype=int)
    oof = oof_calibrated_probs(raw, y, n_splits, seed)
    out = {
        "brier": float(deps["brier_score_loss"](y, oof)),
        "ece": expected_calibration_error(y, oof),
        "roc_auc": None,
        "average_precision": None,
    }
    if len(np.unique(y)) == 2:
        out["roc_auc"] = float(deps["roc_auc_score"](y, raw))
        out["average_precision"] = float(deps["average_precision_score"](y, raw))
    return out


def require_deps():
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        roc_auc_score,
    )

    return {
        "brier_score_loss": brier_score_loss,
        "roc_auc_score": roc_auc_score,
        "average_precision_score": average_precision_score,
    }


def load_regression_validation():
    """2024 validation metrics per family per regression target, from metrics.json."""
    out = {t: {} for t in REGRESSION_TARGETS}
    for family, path in DEFAULT_FAMILY_METRICS.items():
        m = json.loads(path.read_text())
        for d in m.get("models", []):
            t = d.get("target")
            if t in REGRESSION_TARGETS:
                val = d.get("validation", {})
                out[t][family] = {
                    "r2": val.get("r2"),
                    "mae": val.get("mae"),
                    "rmse": val.get("rmse"),
                }
    return out


def main():
    args = parse_args()
    deps = require_deps()

    val = pd.read_csv(args.val_predictions)
    count = int(len(val))

    report = {
        "selection_basis": (
            "Held-out evaluation set -- classification: 5-fold OOF "
            "isotonic-calibrated Brier; regression: validation R^2 from metrics.json"
        ),
        "evaluation_rows": count,
        "classification": {},
        "regression": {},
        "hybrid_model_mapping": {},
    }

    # --- Classification: full held-out metrics; pick by calibrated Brier ------
    for target in CLASSIFICATION_TARGETS:
        y = val[target].to_numpy(dtype=int)
        fam_info = {}
        for family in FAMILIES:
            raw = val[f"prob_{family}_{target}"].to_numpy(dtype=float)
            fam_info[family] = metrics_2024(raw, y, args.n_splits, args.random_seed, deps)
        pick = min(FAMILIES, key=lambda f: fam_info[f]["brier"])
        report["classification"][target] = {
            "prevalence": float(y.mean()),
            "count": count,
            "pick": pick,
            "families": fam_info,
        }
        report["hybrid_model_mapping"][target] = pick

    # --- Regression: pick by held-out R^2 ------------------------------------
    reg_val = load_regression_validation()
    for target in REGRESSION_TARGETS:
        fam_info = {family: dict(reg_val[target].get(family, {})) for family in FAMILIES}
        pick = max(FAMILIES, key=lambda f: fam_info[f].get("r2") or -1e9)
        report["regression"][target] = {"pick": pick, "families": fam_info}
        report["hybrid_model_mapping"][target] = pick

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # --- Print ---------------------------------------------------------------
    print(f"MODEL PICK per target (held-out evaluation set, n={count}; "
          "best score deployed)\n")
    print("Classification:")
    print(f"  {'target':30s} {'PICK':14s} {'Brier':>8s} {'AUC':>7s}")
    for t in CLASSIFICATION_TARGETS:
        r = report["classification"][t]
        p = r["pick"]
        print(
            f"  {t:30s} {p:14s} {r['families'][p]['brier']:>8.4f} "
            f"{r['families'][p]['roc_auc']:>7.3f}"
        )
    print("\nRegression:")
    for t in REGRESSION_TARGETS:
        r = report["regression"][t]
        p = r["pick"]
        print(f"  {t:30s} {p:14s} R2={r['families'][p].get('r2'):.3f}")

    print("\nHYBRID_MODEL_MAPPING:")
    for t, f in report["hybrid_model_mapping"].items():
        print(f'    "{t}": "{f}",')
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
