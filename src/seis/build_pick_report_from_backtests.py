"""Assemble a per-target pick report from the four families' 2025 backtests.

Reads each family's backtest_metrics.json (all produced on the identical 2025
backtest at deployment prevalence via the production inference path) and emits a
repick-report-shaped JSON that build_html_report.py consumes:

    classification[target] = {prevalence, count, pick, families{fam:{brier,ece,
                              roc_auc,average_precision}}}
    regression[target]     = {pick, families{fam:{r2,mae,rmse}}}

The "pick" per target is the single best family on the primary metric for that
task: lowest Brier for classification (Path B trains at natural prevalence, so
the raw Brier IS the calibrated Brier), highest R² for regression.
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
        # Primary metric: lowest Brier wins.
        pick = min(fam_metrics, key=lambda f: fam_metrics[f]["brier"])
        ref = families[pick]["metrics"]["classification"][target]
        out[target] = {
            "prevalence": ref["positive_rate"],
            "count": ref["count"],
            "pick": pick,
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
        # Primary metric: highest R² wins (skip families with no R²).
        scored = {f: m["r2"] for f, m in fam_metrics.items() if m.get("r2") is not None}
        pick = max(scored, key=scored.get) if scored else next(iter(fam_metrics))
        out[target] = {"pick": pick, "families": fam_metrics}
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
        "classification": build_classification(families),
        "regression": build_regression(families),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    print("\nRecommended (best) model per target:")
    for target in CLASSIFICATION_TARGETS:
        node = report["classification"][target]
        print(f"  {target:<30} -> {node['pick']:<14} (Brier {node['families'][node['pick']]['brier']:.4f})")
    for target in REGRESSION_TARGETS:
        node = report["regression"][target]
        print(f"  {target:<30} -> {node['pick']:<14} (R2 {node['families'][node['pick']]['r2']:.4f})")


if __name__ == "__main__":
    main()
