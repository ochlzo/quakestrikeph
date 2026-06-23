"""Assemble a per-target pick report from the four families' 2025 backtests.

Reads each family's backtest_metrics.json (all produced on the identical 2025
backtest at deployment prevalence via the production inference path) and emits a
repick-report-shaped JSON that build_html_report.py consumes:

    classification[target] = {prevalence, count, pick, families{fam:{brier,ece,
                              roc_auc,average_precision}}}
    regression[target]     = {pick, families{fam:{r2,mae,rmse}}}

The "pick" per target is the family with the highest weighted, normalized score
(not a single-metric winner). For each target, every metric is min-max normalized
across the four families (1 = best family on that metric, 0 = worst) so metrics
on very different numeric ranges contribute comparably, then combined with task
weights:

  Classification: Brier 50%, ECE 25%, Average Precision 15%, ROC-AUC 10%
                  (Brier/ECE are lower-is-better; AP/ROC higher-is-better)
  Regression:     RMSE 50%, MAE 30%, R² 20%
                  (RMSE/MAE lower-is-better; R² higher-is-better)

Rationale: once ROC-AUC is ~0.98+, family differences there are negligible, so
probability accuracy (Brier) and calibration (ECE) dominate. For regression, large
misses matter most (a 40 km vs 180 km distance error, or 0.3 vs 1.2 magnitude), so
RMSE is weighted above MAE and R². Path B trains at natural prevalence, so the raw
Brier IS the calibrated Brier.
"""

import argparse
import json
from pathlib import Path

# Code-side family keys (must match build_html_report.py FAMILIES) -> the
# backtest_metrics.json each one writes. Note random_forest's output dir uses a
# hyphen while the family key uses an underscore.
FAMILY_BACKTESTS = {
    "xgboost": "src/outputs/xgboost/backtests_mc_1_0/backtest_metrics.json",
    "lightgbm": "src/outputs/lightgbm/backtests_mc_1_0/backtest_metrics.json",
    "random_forest": "src/outputs/random-forest/backtests_mc_1_0/backtest_metrics.json",
    "catboost": "src/outputs/catboost/backtests_mc_1_0/backtest_metrics.json",
}

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

CLS_KEYS = ["brier", "ece", "roc_auc", "average_precision"]
REG_KEYS = ["r2", "mae", "rmse"]

# Weighted scoring. Each metric is min-max normalized across the four families
# per target (1 = best, 0 = worst), then combined with these weights. The pick is
# the highest weighted score. LOWER_BETTER metrics are inverted during normalize.
CLS_WEIGHTS = {"brier": 0.50, "ece": 0.25, "average_precision": 0.15, "roc_auc": 0.10}
REG_WEIGHTS = {"rmse": 0.50, "mae": 0.30, "r2": 0.20}
LOWER_BETTER = {"brier", "ece", "rmse", "mae"}


def normalize_metric(values, lower_better):
    """Min-max normalize fam->value to fam->[0,1] with 1 = best.

    A missing value (None) scores 0 (treated as worst). When all families tie
    (zero spread) every family scores 1.0 so the metric does not break the tie.
    """
    present = [v for v in values.values() if v is not None]
    if not present:
        return {fam: 0.0 for fam in values}
    lo, hi = min(present), max(present)
    out = {}
    for fam, value in values.items():
        if value is None:
            out[fam] = 0.0
        elif hi == lo:
            out[fam] = 1.0
        else:
            frac = (value - lo) / (hi - lo)
            out[fam] = (1.0 - frac) if lower_better else frac
    return out


def weighted_scores(fam_metrics, weights):
    """fam->metrics dict and metric weights -> fam->weighted score (higher=better)."""
    normalized = {
        metric: normalize_metric(
            {fam: fam_metrics[fam].get(metric) for fam in fam_metrics},
            metric in LOWER_BETTER,
        )
        for metric in weights
    }
    return {
        fam: round(sum(weights[m] * normalized[m][fam] for m in weights), 6)
        for fam in fam_metrics
    }


def load_metrics(paths):
    families = {}
    for fam, path in paths.items():
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Backtest metrics not found for {fam}: {p}")
        families[fam] = json.loads(p.read_text())
    return families


def check_same_eval(families):
    configs = {fam: data["config"] for fam, data in families.items()}
    keys = ("test_start_year", "test_end_year", "sample_mode", "sampled_rows")
    signature = {fam: tuple(cfg.get(k) for k in keys) for fam, cfg in configs.items()}
    distinct = set(signature.values())
    if len(distinct) != 1:
        raise ValueError(
            "Backtests are NOT comparable (differing eval config):\n"
            + "\n".join(f"  {fam}: {sig}" for fam, sig in signature.items())
        )
    return configs[next(iter(configs))]


def build_classification(families):
    out = {}
    for target in CLASSIFICATION_TARGETS:
        fam_metrics = {}
        for fam, data in families.items():
            node = data["metrics"]["classification"][target]
            fam_metrics[fam] = {k: node.get(k) for k in CLS_KEYS}
        # Weighted, normalized score (Brier 50 / ECE 25 / AP 15 / ROC 10).
        scores = weighted_scores(fam_metrics, CLS_WEIGHTS)
        pick = max(scores, key=scores.get)
        ref = families[pick]["metrics"]["classification"][target]
        out[target] = {
            "prevalence": ref["positive_rate"],
            "count": ref["count"],
            "pick": pick,
            "pick_score": scores[pick],
            "scores": scores,
            "families": fam_metrics,
        }
    return out


def build_regression(families):
    out = {}
    for target in REGRESSION_TARGETS:
        fam_metrics = {}
        for fam, data in families.items():
            node = data["metrics"]["regression"].get(target, {})
            fam_metrics[fam] = {k: node.get(k) for k in REG_KEYS}
        # Weighted, normalized score (RMSE 50 / MAE 30 / R² 20).
        scores = weighted_scores(fam_metrics, REG_WEIGHTS)
        pick = max(scores, key=scores.get)
        out[target] = {
            "pick": pick,
            "pick_score": scores[pick],
            "scores": scores,
            "families": fam_metrics,
        }
    return out


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--output",
        default="src/outputs/seis/backtest_pick_report.json",
        type=Path,
    )
    return p.parse_args()


def main():
    args = parse_args()
    families = load_metrics(FAMILY_BACKTESTS)
    config = check_same_eval(families)

    report = {
        "source": "2025 backtest (production inference path, natural prevalence, Path B)",
        "evaluation_rows": config.get("sampled_rows"),
        "test_start_year": config.get("test_start_year"),
        "test_end_year": config.get("test_end_year"),
        "families": list(FAMILY_BACKTESTS),
        "scoring": {
            "method": "per-target min-max normalization across families (1=best), weighted sum",
            "classification_weights": CLS_WEIGHTS,
            "regression_weights": REG_WEIGHTS,
            "lower_is_better": sorted(LOWER_BETTER),
        },
        "classification": build_classification(families),
        "regression": build_regression(families),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    print("\nRecommended model per target (highest weighted score):")
    for target in CLASSIFICATION_TARGETS:
        node = report["classification"][target]
        fam = node["families"][node["pick"]]
        print(
            f"  {target:<34} -> {node['pick']:<14} "
            f"score {node['pick_score']:.3f} (Brier {fam['brier']:.4f}, ECE {fam['ece']:.4f})"
        )
    for target in REGRESSION_TARGETS:
        node = report["regression"][target]
        fam = node["families"][node["pick"]]
        print(
            f"  {target:<34} -> {node['pick']:<14} "
            f"score {node['pick_score']:.3f} (RMSE {fam['rmse']:.3f}, MAE {fam['mae']:.3f}, R2 {fam['r2']:.3f})"
        )


if __name__ == "__main__":
    main()
