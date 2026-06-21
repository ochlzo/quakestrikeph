"""Compare two calibration strategies for the XGBoost classifiers, judged on the
2025+ test set (untouched by either calibration mechanism):

  * Path A -- train with scale_pos_weight (the current models), then apply a
    post-hoc sklearn IsotonicRegression fit on the 2024 validation year.
  * Path B -- train at natural prevalence (scale_pos_weight = 1.0) with log loss,
    so the model's own output is the probability. No post-hoc step.

For context we also report Path A's RAW (uncalibrated) scores. Probability
accuracy is measured with Brier and log loss (lower is better), calibration with
ECE and sklearn.calibration.calibration_curve, and ranking with ROC-AUC.
"""

import argparse

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

DF = "src/training_set/training_dataset_mc_1_0.csv"
MODELS = "src/outputs/xgboost/models_mc_1_0"
TARGETS = [
    "aftershock_24h",
    "aftershock_within_10km_24h",
    "aftershock_within_25km_24h",
    "aftershock_within_50km_24h",
    "aftershock_within_100km_24h",
    "aftershock_within_200km_24h",
]
# Identical to the training script defaults so Path B differs from Path A only in
# scale_pos_weight.
HP = dict(
    objective="binary:logistic",
    eval_metric="logloss",
    tree_method="hist",
    n_estimators=1200,
    learning_rate=0.03,
    max_depth=4,
    subsample=0.85,
    colsample_bytree=0.85,
    min_child_weight=2.0,
    reg_lambda=1.0,
    early_stopping_rounds=100,
    random_state=42,
    n_jobs=-1,
)


def ece(y, p, n_bins=10):
    """Expected Calibration Error with uniform bins (count-weighted)."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.sum() / len(p) * abs(y[m].mean() - p[m].mean())
    return total


def safe_logloss(y, p):
    return log_loss(y, np.clip(p, 1e-7, 1 - 1e-7))


def scale_pos_weight(y):
    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    return float(neg / pos) if pos else 1.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--test-year",
        type=int,
        default=2024,
        help="Single year held out as the test set. val=test_year-1, train<=test_year-2.",
    )
    args = parser.parse_args()
    test_year = args.test_year
    val_year = test_year - 1
    train_end = test_year - 2

    feats = [l.strip() for l in open(f"{MODELS}/feature_columns.txt") if l.strip()]
    df = pd.read_csv(DF, low_memory=False)
    train = df[df.event_year <= train_end]
    val = df[df.event_year == val_year]
    test = df[df.event_year == test_year]
    print(
        f"test_year={test_year}  ->  train(<= {train_end})={len(train)}  "
        f"val({val_year})={len(val)}  test({test_year})={len(test)}\n"
    )

    rows = []
    curves = {}
    for t in TARGETS:
        yval, ytest = val[t].to_numpy(), test[t].to_numpy()

        # Path A: train fresh with scale_pos_weight, then fit isotonic on val
        mA = xgb.XGBClassifier(scale_pos_weight=scale_pos_weight(train[t].to_numpy()), **HP)
        mA.fit(train[feats], train[t], eval_set=[(val[feats], val[t])], verbose=False)
        pA_val = mA.predict_proba(val[feats])[:, 1]
        pA_raw = mA.predict_proba(test[feats])[:, 1]
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(pA_val, yval)
        pA_cal = iso.predict(pA_raw)

        # Path B: natural prevalence, no post-hoc calibration
        mB = xgb.XGBClassifier(scale_pos_weight=1.0, **HP)
        mB.fit(train[feats], train[t], eval_set=[(val[feats], val[t])], verbose=False)
        pB = mB.predict_proba(test[feats])[:, 1]

        for name, p in [
            ("A-raw (no calib)", pA_raw),
            ("A: spw+isotonic", pA_cal),
            ("B: natural prev", pB),
        ]:
            rows.append(
                dict(
                    target=t,
                    path=name,
                    brier=brier_score_loss(ytest, p),
                    logloss=safe_logloss(ytest, p),
                    ece=ece(ytest, p),
                    roc=roc_auc_score(ytest, p),
                )
            )
        # keep the headline calibration_curve
        prob_true_A, prob_pred_A = calibration_curve(ytest, pA_cal, n_bins=10, strategy="uniform")
        prob_true_B, prob_pred_B = calibration_curve(ytest, pB, n_bins=10, strategy="uniform")
        curves[t] = (prob_pred_A, prob_true_A, prob_pred_B, prob_true_B)

    res = pd.DataFrame(rows)
    pd.set_option("display.float_format", lambda v: f"{v:.4f}")
    print("=== TEST-SET METRICS (Brier/logloss/ECE: lower better; ROC: higher) ===")
    print(res.to_string(index=False))

    print("\n=== MEANS ACROSS THE 6 TARGETS ===")
    print(res.groupby("path")[["brier", "logloss", "ece", "roc"]].mean().to_string())

    pp_A, pt_A, pp_B, pt_B = curves["aftershock_24h"]
    print("\n=== calibration_curve(aftershock_24h, 10 uniform bins) ===")
    print("  Path A (spw+isotonic):  pred -> obs")
    for a, b in zip(pp_A, pt_A):
        print(f"      {a:.3f} -> {b:.3f}")
    print("  Path B (natural prev):  pred -> obs")
    for a, b in zip(pp_B, pt_B):
        print(f"      {a:.3f} -> {b:.3f}")


if __name__ == "__main__":
    main()
