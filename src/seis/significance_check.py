"""Are the per-family differences on the test set real, or within noise?

For each target, paired bootstrap of the metric difference between families on
the 2025+ test set (backtest_predictions.csv):

  * Classification: Brier difference (deployed pick vs the test winner, and the
    test winner vs the runner-up).
  * Regression: squared-error difference (R^2/MSE is monotone in it).

A 95% CI that straddles 0 means the two models are a statistical tie -- so a
"flip" between validation and test is just noise, not a real regression. A CI
fully on one side means the gap is real.

Reads the deployed mapping from repick_report.json; the test winner is the
lowest-Brier / highest-R^2 family on the test set.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# The console table prints non-ASCII (Delta, em-dash). On Windows the default
# cp1252 stdout raises UnicodeEncodeError; force UTF-8 so the run never crashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

PRED = Path("src/outputs/seis/backtests_mc_1_0/backtest_predictions.csv")
REPICK = Path("src/outputs/seis/calibration/repick_report.json")

FAMILIES = ["xgboost", "lightgbm", "random_forest", "catboost"]
SHORT = {"xgboost": "xgb", "lightgbm": "lgbm", "random_forest": "rf", "catboost": "cb"}
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
N_BOOT = 2000
SEED = 42


def boot_delta(err_a, err_b, n_boot=N_BOOT, seed=SEED):
    """Bootstrap CI for mean(err_a) - mean(err_b), paired by row.

    err_* are per-row losses (squared error). Negative point => a is better.
    """
    rng = np.random.default_rng(seed)
    n = len(err_a)
    point = float(err_a.mean() - err_b.mean())
    deltas = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        deltas[i] = err_a[idx].mean() - err_b[idx].mean()
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return point, float(lo), float(hi)


def verdict(lo, hi):
    if lo > 0 or hi < 0:
        return "REAL gap"
    return "tie (within noise)"


OUTPUT = Path("src/outputs/seis/calibration/significance_report.json")


def main():
    df = pd.read_csv(PRED)
    mapping = json.loads(REPICK.read_text())["hybrid_model_mapping"]
    report = {"n": int(len(df)), "n_boot": N_BOOT, "classification": {}, "regression": {}}

    print(f"Paired bootstrap on the test set (n={len(df):,}, {N_BOOT} resamples)\n")
    print(f"{'target':28s} {'test win':6s} {'deployed':8s} "
          f"{'dep-win ΔBrier [95% CI]':28s} {'verdict':20s} {'win vs runner-up':22s}")
    for t in CLASSIFICATION_TARGETS:
        y = df[f"actual_{t}"].to_numpy(dtype=float)
        sq = {f: (df[f"prob_{f}_{t}"].to_numpy(dtype=float) - y) ** 2 for f in FAMILIES}
        brier = {f: float(sq[f].mean()) for f in FAMILIES}
        order = sorted(FAMILIES, key=lambda f: brier[f])
        win, runner = order[0], order[1]
        dep = mapping[t]

        if dep == win:
            dep_line, dverd, dep_ci = "(deployed IS the test winner)", "deployed is winner", None
        else:
            p, lo, hi = boot_delta(sq[dep], sq[win])
            dep_line, dverd, dep_ci = f"{p:+.4f} [{lo:+.4f},{hi:+.4f}]", verdict(lo, hi), [p, lo, hi]

        pr, lor, hir = boot_delta(sq[win], sq[runner])
        report["classification"][t] = {
            "test_winner": win, "deployed": dep, "runner_up": runner,
            "brier": brier,
            "deployed_vs_winner": {"delta": dep_ci[0] if dep_ci else 0.0,
                                   "ci": dep_ci[1:] if dep_ci else [0.0, 0.0],
                                   "verdict": dverd},
            "winner_vs_runnerup": {"delta": pr, "ci": [lor, hir], "verdict": verdict(lor, hir)},
        }
        print(f"{t:28s} {SHORT[win]:6s} {SHORT[dep]:8s} {dep_line:28s} {dverd:20s} "
              f"{verdict(lor, hir)+' vs '+SHORT[runner]:22s}")

    print("\nREGRESSION — deployed pick vs test winner (squared-error Δ):\n")
    for t in REGRESSION_TARGETS:
        y = df[f"actual_{t}"].to_numpy(dtype=float)
        m = ~np.isnan(y)
        yv = y[m]
        sq = {f: (df[f"pred_{f}_{t}"].to_numpy(dtype=float)[m] - yv) ** 2 for f in FAMILIES}
        mse = {f: float(sq[f].mean()) for f in FAMILIES}
        win = min(FAMILIES, key=lambda f: mse[f])
        dep = mapping[t]
        if dep == win:
            line, vd, ci = "(deployed IS the test winner)", "deployed is winner", None
        else:
            p, lo, hi = boot_delta(sq[dep], sq[win])
            line, vd, ci = f"{p:+.2f} [{lo:+.2f},{hi:+.2f}]", verdict(lo, hi), [p, lo, hi]
        report["regression"][t] = {
            "test_winner": win, "deployed": dep, "mse": mse,
            "deployed_vs_winner": {"delta": ci[0] if ci else 0.0,
                                   "ci": ci[1:] if ci else [0.0, 0.0], "verdict": vd},
        }
        print(f"{t:30s} {SHORT[win]:8s} {SHORT[dep]:8s} {line:30s} {vd}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {OUTPUT}")


if __name__ == "__main__":
    main()
