"""Re-decide the per-bin model picks on calibration measured at deployment prevalence.

Consumes the wide predictions CSV from ``calibration_score.py`` (full pool,
natural prevalence, production features) and, per classification target, for
each model family, computes:

  * Brier, ECE (10 equal-width bins), ROC-AUC, average precision,
    recall/precision @ 0.5 -- all at the natural pool prevalence.
  * No-skill Brier at pool prevalence and the model's edge over it.
  * Isotonic-calibrated Brier/ECE using a 2-fold cross-fit, applied EQUALLY
    to all families (removes the unequal-preprocessing confound that
    favored the boosting models in the original comparison).
  * Bootstrap 95% CIs on each family's Brier and on the Brier *difference*
    between the top-2 families, so "best" is only claimed when the gap clears
    sampling noise.

Output: a JSON report plus a printed per-bin comparison table and a verdict on
whether each current recommendation survives.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]
FAMILIES = ["xgboost", "lightgbm", "random_forest", "catboost"]

# Current per-bin pick from src/docs/model_recommendations.md (Brier-first on balanced 500).
CURRENT_PICK = {
    "aftershock_24h": "xgboost",
    "aftershock_dist_0_10km_24h": "xgboost",
    "aftershock_dist_10_25km_24h": "lightgbm",
    "aftershock_dist_25_50km_24h": "lightgbm",
    "aftershock_dist_50_100km_24h": "xgboost",
    "aftershock_dist_100_200km_24h": "xgboost",
    "aftershock_dist_200_pluskm_24h": "lightgbm",
}

DEFAULT_PREDICTIONS = Path("src/outputs/seis/calibration/full_pool_predictions.csv")
DEFAULT_OUTPUT = Path("src/outputs/seis/calibration/calibration_report.json")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--ece-bins", type=int, default=10)
    parser.add_argument("--random-seed", type=int, default=42)
    return parser.parse_args()


def require_deps():
    try:
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import (
            average_precision_score,
            brier_score_loss,
            precision_score,
            recall_score,
            roc_auc_score,
        )
        from sklearn.model_selection import StratifiedKFold
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError("Analysis requires scikit-learn.") from error
    return {
        "IsotonicRegression": IsotonicRegression,
        "StratifiedKFold": StratifiedKFold,
        "average_precision_score": average_precision_score,
        "brier_score_loss": brier_score_loss,
        "precision_score": precision_score,
        "recall_score": recall_score,
        "roc_auc_score": roc_auc_score,
    }


def expected_calibration_error(y_true, prob, n_bins):
    """10-bin equal-width ECE: sum_b (n_b/N) * |acc_b - conf_b|."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true)
    for lo, hi in zip(edges[:-1], edges[1:]):
        # Last bin is closed on the right so prob == 1.0 is counted.
        if hi == 1.0:
            mask = (prob >= lo) & (prob <= hi)
        else:
            mask = (prob >= lo) & (prob < hi)
        if not mask.any():
            continue
        conf = prob[mask].mean()
        acc = y_true[mask].mean()
        ece += (mask.sum() / n) * abs(acc - conf)
    return float(ece)


def isotonic_cross_fit(y_true, prob, deps, seed):
    """Out-of-fold isotonic-calibrated probabilities via 2-fold stratified CV.

    Each fold's calibrator is fit on the other fold, so every probability is
    calibrated by a model that did not see it -- a fair, leak-free estimate of
    post-calibration quality, applied identically to all families.
    """
    calibrated = np.empty_like(prob, dtype=float)
    skf = deps["StratifiedKFold"](n_splits=2, shuffle=True, random_state=seed)
    for train_idx, test_idx in skf.split(prob.reshape(-1, 1), y_true):
        iso = deps["IsotonicRegression"](out_of_bounds="clip")
        iso.fit(prob[train_idx], y_true[train_idx])
        calibrated[test_idx] = iso.predict(prob[test_idx])
    return calibrated


def bootstrap_brier_ci(y_true, prob, n_boot, seed):
    rng = np.random.default_rng(seed)
    n = len(y_true)
    stats = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        yt = y_true[idx]
        p = prob[idx]
        stats[b] = np.mean((p - yt) ** 2)
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def bootstrap_brier_diff_ci(y_true, prob_a, prob_b, n_boot, seed):
    """Paired bootstrap CI on Brier(a) - Brier(b). Negative => a better."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    diffs = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        yt = y_true[idx]
        ba = np.mean((prob_a[idx] - yt) ** 2)
        bb = np.mean((prob_b[idx] - yt) ** 2)
        diffs[i] = ba - bb
    return (
        float(np.percentile(diffs, 2.5)),
        float(np.percentile(diffs, 97.5)),
        float(np.mean(diffs)),
    )


def analyze_target(df, target, deps, args):
    y_true = df[target].astype(int).to_numpy()
    prevalence = float(y_true.mean())
    no_skill_brier = prevalence * (1.0 - prevalence)

    per_family = {}
    for family in FAMILIES:
        prob = df[f"prob_{family}_{target}"].to_numpy(dtype=float)
        cal = isotonic_cross_fit(y_true, prob, deps, args.random_seed)
        pred05 = (prob >= 0.5).astype(int)
        brier = float(deps["brier_score_loss"](y_true, prob))
        brier_lo, brier_hi = bootstrap_brier_ci(y_true, prob, args.bootstrap, args.random_seed)
        per_family[family] = {
            "brier": brier,
            "brier_ci95": [brier_lo, brier_hi],
            "ece": expected_calibration_error(y_true, prob, args.ece_bins),
            "roc_auc": float(deps["roc_auc_score"](y_true, prob)),
            "average_precision": float(deps["average_precision_score"](y_true, prob)),
            "recall_at_0_5": float(deps["recall_score"](y_true, pred05, zero_division=0)),
            "precision_at_0_5": float(deps["precision_score"](y_true, pred05, zero_division=0)),
            "brier_edge_over_noskill": no_skill_brier - brier,
            "calibrated_brier": float(deps["brier_score_loss"](y_true, cal)),
            "calibrated_ece": expected_calibration_error(y_true, cal, args.ece_bins),
        }

    # Rank by raw Brier (the criterion under audit) and by calibrated Brier.
    by_brier = sorted(FAMILIES, key=lambda f: per_family[f]["brier"])
    by_cal_brier = sorted(FAMILIES, key=lambda f: per_family[f]["calibrated_brier"])
    by_auc = sorted(FAMILIES, key=lambda f: -per_family[f]["roc_auc"])

    # Top-2 raw-Brier difference CI: is the winner's edge real, or noise?
    a, b = by_brier[0], by_brier[1]
    diff_lo, diff_hi, diff_mean = bootstrap_brier_diff_ci(
        y_true,
        df[f"prob_{a}_{target}"].to_numpy(dtype=float),
        df[f"prob_{b}_{target}"].to_numpy(dtype=float),
        args.bootstrap,
        args.random_seed,
    )
    brier_winner_significant = diff_hi < 0.0  # entire CI below 0 => a beats b

    return {
        "prevalence": prevalence,
        "positives": int(y_true.sum()),
        "count": int(len(y_true)),
        "no_skill_brier": no_skill_brier,
        "families": per_family,
        "rank_by_brier": by_brier,
        "rank_by_calibrated_brier": by_cal_brier,
        "rank_by_auc": by_auc,
        "brier_top2": [a, b],
        "brier_top2_diff_mean": diff_mean,
        "brier_top2_diff_ci95": [diff_lo, diff_hi],
        "brier_winner_significant": brier_winner_significant,
        "current_pick": CURRENT_PICK[target],
    }


def fmt(x, p=4):
    return f"{x:.{p}f}"


def print_report(report):
    for target in CLASSIFICATION_TARGETS:
        r = report[target]
        print("=" * 92)
        print(
            f"{target}   prevalence={fmt(r['prevalence'],4)} "
            f"({r['positives']}/{r['count']})   no-skill Brier={fmt(r['no_skill_brier'])}"
        )
        header = (
            f"  {'family':14s} {'Brier':>8s} {'Brier_CI':>17s} {'edge':>8s} "
            f"{'ECE':>7s} {'AUC':>7s} {'AP':>7s} {'calBrier':>9s} {'calECE':>7s}"
        )
        print(header)
        for family in FAMILIES:
            f = r["families"][family]
            ci = f"[{fmt(f['brier_ci95'][0],3)},{fmt(f['brier_ci95'][1],3)}]"
            star = " *" if family == r["current_pick"] else "  "
            print(
                f"{star}{family:14s} {fmt(f['brier']):>8s} {ci:>17s} "
                f"{fmt(f['brier_edge_over_noskill'],4):>8s} {fmt(f['ece'],4):>7s} "
                f"{fmt(f['roc_auc'],3):>7s} {fmt(f['average_precision'],3):>7s} "
                f"{fmt(f['calibrated_brier'],4):>9s} {fmt(f['calibrated_ece'],4):>7s}"
            )
        sig = "REAL (CI excludes 0)" if r["brier_winner_significant"] else "NOT significant (CI spans 0)"
        print(
            f"  Brier rank: {r['rank_by_brier']}  | calBrier rank: {r['rank_by_calibrated_brier']}  "
            f"| AUC rank: {r['rank_by_auc']}"
        )
        print(
            f"  top-2 Brier diff ({r['brier_top2'][0]}-{r['brier_top2'][1]}): "
            f"mean={fmt(r['brier_top2_diff_mean'],4)} CI={[fmt(x,4) for x in r['brier_top2_diff_ci95']]} -> {sig}"
        )
        # Verdict on the current recommendation.
        verdict = build_verdict(r)
        print(f"  CURRENT PICK = {r['current_pick']}  -> {verdict}")
    print("=" * 92)


def build_verdict(r):
    pick = r["current_pick"]
    brier_best = r["rank_by_brier"][0]
    cal_best = r["rank_by_calibrated_brier"][0]
    notes = []
    if pick == brier_best:
        if r["brier_winner_significant"]:
            notes.append("survives (best raw Brier, gap significant)")
        else:
            notes.append("best raw Brier but gap within noise")
    else:
        notes.append(f"NOT best raw Brier (best={brier_best})")
    if pick != cal_best:
        notes.append(f"after equal isotonic calibration, best={cal_best}")
    else:
        notes.append("still best after calibration")
    return "; ".join(notes)


def main():
    args = parse_args()
    deps = require_deps()
    if not args.predictions.exists():
        raise FileNotFoundError(
            f"Predictions CSV not found: {args.predictions}. Run calibration_score.py first."
        )
    df = pd.read_csv(args.predictions)
    print(f"Loaded {len(df)} scored events from {args.predictions}\n")

    report = {}
    for target in CLASSIFICATION_TARGETS:
        report[target] = analyze_target(df, target, deps, args)

    print_report(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
