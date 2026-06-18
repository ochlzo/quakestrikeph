"""Re-pick the per-bin model family using calibrators fit on 2024, evaluated on 2025+.

This is the honest, fully out-of-sample selection:

  * Calibrators were fit on the 2024 validation year (``fit_calibrators.py``).
  * They are applied here to the raw 2025+ pool predictions
    (``full_pool_predictions.csv`` from ``calibration_score.py``).
  * Because the calibrators never saw 2025+ data, the resulting calibrated
    Brier/ECE are genuine out-of-sample estimates -- unlike the cross-fit in
    ``calibration_analysis.py`` (a diagnostic that fit and evaluated within the
    pool).

For each target it computes calibrated and raw metrics per family at the natural
pool prevalence, then picks the family with the best calibrated Brier as the
deployment recommendation, reporting AUC/AP alongside so ranking is visible.
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

from calibration_analysis import (  # noqa: E402
    CLASSIFICATION_TARGETS,
    FAMILIES,
    expected_calibration_error,
)

DEFAULT_PREDICTIONS = Path("src/outputs/seis/calibration/full_pool_predictions.csv")
DEFAULT_CALIBRATORS_DIR = Path("src/outputs/seis/calibration/calibrators")
DEFAULT_OUTPUT = Path("src/outputs/seis/calibration/repick_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--calibrators-dir", type=Path, default=DEFAULT_CALIBRATORS_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ece-bins", type=int, default=10)
    return parser.parse_args()


def require_deps():
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        roc_auc_score,
    )
    import joblib

    return {
        "average_precision_score": average_precision_score,
        "brier_score_loss": brier_score_loss,
        "roc_auc_score": roc_auc_score,
        "joblib": joblib,
    }


def main():
    args = parse_args()
    deps = require_deps()
    df = pd.read_csv(args.predictions)
    print(f"Loaded {len(df)} pool events\n", flush=True)

    report = {}
    for target in CLASSIFICATION_TARGETS:
        y = df[target].to_numpy(dtype=int)
        prevalence = float(y.mean())
        per_family = {}
        for family in FAMILIES:
            raw = df[f"prob_{family}_{target}"].to_numpy(dtype=float)
            cal_path = args.calibrators_dir / f"{family}__{target}.joblib"
            iso = deps["joblib"].load(cal_path)
            cal = iso.predict(raw)
            per_family[family] = {
                "raw_brier": float(deps["brier_score_loss"](y, raw)),
                "calibrated_brier": float(deps["brier_score_loss"](y, cal)),
                "raw_ece": expected_calibration_error(y, raw, args.ece_bins),
                "calibrated_ece": expected_calibration_error(y, cal, args.ece_bins),
                "roc_auc": float(deps["roc_auc_score"](y, raw)),
                "average_precision": float(deps["average_precision_score"](y, raw)),
            }
        pick = min(FAMILIES, key=lambda f: per_family[f]["calibrated_brier"])
        report[target] = {
            "prevalence": prevalence,
            "pick_calibrated": pick,
            "families": per_family,
        }

    # Print table.
    for target in CLASSIFICATION_TARGETS:
        r = report[target]
        print("=" * 84)
        print(f"{target}   prevalence={r['prevalence']:.4f}   PICK={r['pick_calibrated'].upper()}")
        print(f"  {'family':14s} {'calBrier':>9s} {'calECE':>8s} {'rawBrier':>9s} {'AUC':>7s} {'AP':>7s}")
        for family in FAMILIES:
            f = r["families"][family]
            star = " *" if family == r["pick_calibrated"] else "  "
            print(
                f"{star}{family:14s} {f['calibrated_brier']:>9.4f} {f['calibrated_ece']:>8.4f} "
                f"{f['raw_brier']:>9.4f} {f['roc_auc']:>7.3f} {f['average_precision']:>7.3f}"
            )
    print("=" * 84)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {args.output}")

    print("\nDEPLOYMENT MAPPING (calibrated-Brier pick):")
    for target in CLASSIFICATION_TARGETS:
        print(f'    "{target}": "{report[target]["pick_calibrated"]}",')


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
