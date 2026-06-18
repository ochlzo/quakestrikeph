"""Descriptive picker on the TEST set (2025+): which family performed best per target.

Reads the held-out test metrics (``backtest_metrics.json`` from ``backtest.py``)
and, for each target, marks the best-performing family -- lowest calibrated Brier
for classification, highest R^2 for regression.

This is a DESCRIPTIVE view of test-set performance, NOT the deployed selection.
Deployment picks are chosen on the validation set by ``repick_bins.py`` (selecting
on the test set would be hindsight). Output mirrors repick_report.json so the
same report generator can render it.
"""

import argparse
import json
from pathlib import Path

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

DEFAULT_BACKTEST = Path("src/outputs/seis/backtests_mc_1_0/backtest_metrics.json")
DEFAULT_OUTPUT = Path("src/outputs/seis/calibration/test_pick_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backtest", type=Path, default=DEFAULT_BACKTEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.backtest.exists():
        raise FileNotFoundError(
            f"{args.backtest} not found. Run `python src/seis/backtest.py --max-events 0` first."
        )
    bt = json.loads(args.backtest.read_text())["metrics"]
    cls = bt["classification_per_family"]
    reg = bt["regression_per_family"]
    count = cls["xgboost"][CLASSIFICATION_TARGETS[0]]["count"]

    report = {
        "selection_basis": "TEST set (2025+) -- descriptive best-per-target; NOT the deployed selection",
        "evaluation_rows": count,
        "classification": {},
        "regression": {},
        "hybrid_model_mapping": {},
    }

    for t in CLASSIFICATION_TARGETS:
        families = {
            f: {
                "brier": cls[f][t]["brier"],
                "ece": cls[f][t].get("ece"),
                "roc_auc": cls[f][t].get("roc_auc"),
                "average_precision": cls[f][t].get("average_precision"),
            }
            for f in FAMILIES
        }
        pick = min(FAMILIES, key=lambda f: families[f]["brier"])
        report["classification"][t] = {
            "prevalence": cls[pick][t]["positive_rate"],
            "count": cls[pick][t]["count"],
            "pick": pick,
            "families": families,
        }
        report["hybrid_model_mapping"][t] = pick

    for t in REGRESSION_TARGETS:
        families = {
            f: {
                "r2": reg[f][t].get("r2"),
                "mae": reg[f][t].get("mae"),
                "rmse": reg[f][t].get("rmse"),
            }
            for f in FAMILIES
        }
        pick = max(FAMILIES, key=lambda f: families[f].get("r2") or -1e9)
        report["regression"][t] = {"pick": pick, "families": families}
        report["hybrid_model_mapping"][t] = pick

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"BEST-ON-TEST per target (2025+, n={count}; descriptive, not deployed)\n")
    print("Classification:")
    print(f"  {'target':30s} {'BEST':14s} {'Brier':>8s} {'AUC':>7s}")
    for t in CLASSIFICATION_TARGETS:
        r = report["classification"][t]
        p = r["pick"]
        print(f"  {t:30s} {p:14s} {r['families'][p]['brier']:>8.4f} {r['families'][p]['roc_auc']:>7.3f}")
    print("\nRegression:")
    for t in REGRESSION_TARGETS:
        r = report["regression"][t]
        p = r["pick"]
        print(f"  {t:30s} {p:14s} R2={r['families'][p]['r2']:.3f}")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        import sys
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
