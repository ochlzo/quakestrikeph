"""Walk-forward (expanding-window) model selection across years.

Single-year selection is fragile: the best family per target flips between 2024
and 2025 (and those flips are statistically real). This picks each family on
MULTIPLE held-out years instead, so the choice reflects which family is
consistently strong rather than which got lucky in one year.

Each fold mirrors the production train/val/test structure, shifted in time. For
an evaluation year Y:
    train     = event_year <= Y-2        (all families)
    early-stop = event_year == Y-1        (XGBoost/LightGBM only; RF ignores)
    evaluate  = event_year == Y
Models use the same hyperparameters as production. 2025+ is never an evaluation
year here -- it stays the sealed final test.

For each (fold, family, target):
  * Classification: calibrated Brier via 5-fold OOF isotonic on the eval year,
    plus ROC-AUC / AP (rank-based, from raw probs).
  * Regression: R^2 / MAE on the eval year.

Aggregating across folds (mean + how many folds each family wins) gives a
robust per-target pick. Output: walk_forward_report.json + a printed table.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
DEFAULT_OUTPUT = Path("src/outputs/seis/calibration/walk_forward_report.json")

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


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--eval-years", type=int, nargs="+", default=[2021, 2022, 2023, 2024])
    p.add_argument("--random-state", type=int, default=42)
    return p.parse_args()


def feature_columns(csv):
    path = csv.with_suffix(".features.txt")
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def deps():
    import joblib  # noqa: F401
    import lightgbm as lgb
    import xgboost as xgb
    from catboost import CatBoostClassifier, CatBoostRegressor
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import (
        average_precision_score,
        brier_score_loss,
        mean_absolute_error,
        mean_squared_error,
        r2_score,
        roc_auc_score,
    )
    from sklearn.model_selection import StratifiedKFold
    from sklearn.pipeline import Pipeline

    return dict(
        lgb=lgb, xgb=xgb, CBC=CatBoostClassifier, CBR=CatBoostRegressor,
        RFC=RandomForestClassifier, RFR=RandomForestRegressor,
        SimpleImputer=SimpleImputer, Pipeline=Pipeline, IsotonicRegression=IsotonicRegression,
        StratifiedKFold=StratifiedKFold, brier=brier_score_loss, auc=roc_auc_score,
        ap=average_precision_score, mae=mean_absolute_error, mse=mean_squared_error, r2=r2_score,
    )


# ---- model builders (production-matching hyperparameters) --------------------
def xgb_cls(d, spw):
    return d["xgb"].XGBClassifier(
        objective="binary:logistic", eval_metric="logloss", tree_method="hist",
        n_estimators=1200, learning_rate=0.03, max_depth=4, subsample=0.85,
        colsample_bytree=0.85, min_child_weight=2.0, reg_lambda=1.0,
        scale_pos_weight=spw, early_stopping_rounds=100, random_state=42, n_jobs=-1,
    )


def xgb_reg(d):
    return d["xgb"].XGBRegressor(
        objective="reg:squarederror", eval_metric="rmse", tree_method="hist",
        n_estimators=1200, learning_rate=0.03, max_depth=4, subsample=0.85,
        colsample_bytree=0.85, min_child_weight=2.0, reg_lambda=1.0,
        early_stopping_rounds=100, random_state=42, n_jobs=-1,
    )


def lgb_cls(d):
    return d["lgb"].LGBMClassifier(
        objective="binary", n_estimators=2000, learning_rate=0.03, num_leaves=31,
        subsample=0.85, colsample_bytree=0.85, class_weight="balanced",
        random_state=42, n_jobs=-1, verbose=-1,
    )


def lgb_reg(d):
    return d["lgb"].LGBMRegressor(
        objective="regression", n_estimators=2000, learning_rate=0.03, num_leaves=31,
        subsample=0.85, colsample_bytree=0.85, random_state=42, n_jobs=-1, verbose=-1,
    )


def rf_cls(d):
    return d["Pipeline"]([
        ("imputer", d["SimpleImputer"](strategy="median")),
        ("model", d["RFC"](n_estimators=400, min_samples_leaf=2, max_features="sqrt",
                           class_weight="balanced_subsample", random_state=42, n_jobs=-1)),
    ])


def rf_reg(d):
    return d["Pipeline"]([
        ("imputer", d["SimpleImputer"](strategy="median")),
        ("model", d["RFR"](n_estimators=400, min_samples_leaf=4, max_features="sqrt",
                           random_state=42, n_jobs=-1)),
    ])


def cb_cls(d):
    return d["CBC"](
        loss_function="Logloss", eval_metric="Logloss", iterations=2000,
        learning_rate=0.03, depth=4, bootstrap_type="Bernoulli", subsample=0.85,
        rsm=0.85, auto_class_weights="Balanced", early_stopping_rounds=100,
        random_seed=42, thread_count=-1, allow_writing_files=False, verbose=False,
    )


def cb_reg(d):
    return d["CBR"](
        loss_function="RMSE", eval_metric="RMSE", iterations=2000,
        learning_rate=0.03, depth=4, bootstrap_type="Bernoulli", subsample=0.85,
        rsm=0.85, early_stopping_rounds=100,
        random_seed=42, thread_count=-1, allow_writing_files=False, verbose=False,
    )


def oof_calibrated_brier(d, raw, y, seed):
    raw = np.asarray(raw, float); y = np.asarray(y, int)
    oof = np.zeros(len(y))
    skf = d["StratifiedKFold"](n_splits=5, shuffle=True, random_state=seed)
    for tr, te in skf.split(raw.reshape(-1, 1), y):
        iso = d["IsotonicRegression"](out_of_bounds="clip").fit(raw[tr], y[tr])
        oof[te] = iso.predict(raw[te])
    return float(d["brier"](y, oof))


def fit_predict_cls(d, family, Xtr, ytr, Xes, yes, Xev):
    if family == "xgboost":
        spw = float((ytr == 0).sum() / max((ytr == 1).sum(), 1))
        m = xgb_cls(d, spw)
        m.fit(Xtr, ytr, eval_set=[(Xes, yes)], verbose=False)
        return m.predict_proba(Xev)[:, 1]
    if family == "lightgbm":
        m = lgb_cls(d)
        m.fit(Xtr, ytr, eval_set=[(Xes, yes)],
              callbacks=[d["lgb"].early_stopping(100), d["lgb"].log_evaluation(0)])
        return m.predict_proba(Xev)[:, 1]
    if family == "catboost":
        m = cb_cls(d)
        m.fit(Xtr, ytr, eval_set=(Xes, yes), use_best_model=True, verbose=False)
        return m.predict_proba(Xev)[:, 1]
    m = rf_cls(d)  # RF: no early stopping; train on train split only (mirrors production)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xev)[:, 1]


def fit_predict_reg(d, family, Xtr, ytr, Xes, yes, Xev):
    if family == "xgboost":
        m = xgb_reg(d)
        m.fit(Xtr, ytr, eval_set=[(Xes, yes)], verbose=False)
        return m.predict(Xev)
    if family == "lightgbm":
        m = lgb_reg(d)
        m.fit(Xtr, ytr, eval_set=[(Xes, yes)],
              callbacks=[d["lgb"].early_stopping(100), d["lgb"].log_evaluation(0)])
        return m.predict(Xev)
    if family == "catboost":
        m = cb_reg(d)
        m.fit(Xtr, ytr, eval_set=(Xes, yes), use_best_model=True, verbose=False)
        return m.predict(Xev)
    m = rf_reg(d)
    m.fit(Xtr, ytr)
    return m.predict(Xev)


def main():
    args = parse_args()
    d = deps()
    feats = feature_columns(args.input_csv)
    df = pd.read_csv(args.input_csv, low_memory=False)
    print(f"Loaded {len(df)} rows; folds eval on {args.eval_years}\n", flush=True)

    # results[target][family] = list of per-fold metrics
    cls_res = {t: {f: [] for f in FAMILIES} for t in CLASSIFICATION_TARGETS}
    reg_res = {t: {f: [] for f in FAMILIES} for t in REGRESSION_TARGETS}

    for Y in args.eval_years:
        train = df[df["event_year"] <= Y - 2]
        es = df[df["event_year"] == Y - 1]
        ev = df[df["event_year"] == Y]
        if train.empty or es.empty or ev.empty:
            print(f"[skip fold Y={Y}] insufficient data", flush=True)
            continue
        print(f"Fold Y={Y}: train<= {Y-2} ({len(train)}), es={Y-1} ({len(es)}), eval={Y} ({len(ev)})", flush=True)
        Xtr_all, Xes_all, Xev_all = train[feats], es[feats], ev[feats]

        for t in CLASSIFICATION_TARGETS:
            ytr, yes, yev = train[t].to_numpy(int), es[t].to_numpy(int), ev[t].to_numpy(int)
            if len(np.unique(ytr)) < 2 or len(np.unique(yev)) < 2:
                continue
            for f in FAMILIES:
                raw = fit_predict_cls(d, f, Xtr_all, ytr, Xes_all, yes, Xev_all)
                cls_res[t][f].append({
                    "fold": Y,
                    "brier": oof_calibrated_brier(d, raw, yev, args.random_state),
                    "roc_auc": float(d["auc"](yev, raw)),
                    "average_precision": float(d["ap"](yev, raw)),
                })
            print(f"  [cls] {t} done", flush=True)

        for t in REGRESSION_TARGETS:
            mtr = train[t].notna().to_numpy()
            mes = es[t].notna().to_numpy()
            mev = ev[t].notna().to_numpy()
            if mtr.sum() == 0 or mev.sum() == 0:
                continue
            ytr = train[t].to_numpy(float)[mtr]
            yes = es[t].to_numpy(float)[mes]
            yev = ev[t].to_numpy(float)[mev]
            for f in FAMILIES:
                pred = fit_predict_reg(d, f, Xtr_all[mtr], ytr, Xes_all[mes], yes, Xev_all[mev])
                reg_res[t][f].append({
                    "fold": Y,
                    "r2": float(d["r2"](yev, pred)),
                    "mae": float(d["mae"](yev, pred)),
                })
            print(f"  [reg] {t} done", flush=True)

    # ---- aggregate + pick ----
    report = {"eval_years": args.eval_years, "classification": {}, "regression": {}, "hybrid_model_mapping": {}}

    for t in CLASSIFICATION_TARGETS:
        fam_means = {}
        for f in FAMILIES:
            folds = cls_res[t][f]
            if not folds:
                continue
            fam_means[f] = {
                "mean_brier": float(np.mean([x["brier"] for x in folds])),
                "mean_roc_auc": float(np.mean([x["roc_auc"] for x in folds])),
                "mean_average_precision": float(np.mean([x["average_precision"] for x in folds])),
                "per_fold_brier": {x["fold"]: round(x["brier"], 4) for x in folds},
            }
        if not fam_means:
            continue
        pick = min(fam_means, key=lambda f: fam_means[f]["mean_brier"])
        wins = {f: 0 for f in fam_means}
        for i in range(len(cls_res[t][pick])):
            fold_best = min(fam_means, key=lambda f: cls_res[t][f][i]["brier"])
            wins[fold_best] += 1
        report["classification"][t] = {"pick": pick, "fold_wins": wins, "families": fam_means}
        report["hybrid_model_mapping"][t] = pick

    for t in REGRESSION_TARGETS:
        fam_means = {}
        for f in FAMILIES:
            folds = reg_res[t][f]
            if not folds:
                continue
            fam_means[f] = {
                "mean_r2": float(np.mean([x["r2"] for x in folds])),
                "mean_mae": float(np.mean([x["mae"] for x in folds])),
                "per_fold_r2": {x["fold"]: round(x["r2"], 3) for x in folds},
            }
        if not fam_means:
            continue
        pick = max(fam_means, key=lambda f: fam_means[f]["mean_r2"])
        report["regression"][t] = {"pick": pick, "families": fam_means}
        report["hybrid_model_mapping"][t] = pick

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\nWALK-FORWARD PICK (robust across folds)\n")
    print("Classification:")
    fold_win_header = "fold wins (" + "/".join(SHORT[f] for f in FAMILIES) + ")"
    print(f"  {'target':30s} {'PICK':6s} {'mean Brier':>10s} {fold_win_header:>28s}")
    for t in CLASSIFICATION_TARGETS:
        if t not in report["classification"]:
            continue
        r = report["classification"][t]
        w = r["fold_wins"]
        wins = "/".join(str(w.get(f, 0)) for f in FAMILIES)
        print(f"  {t:30s} {SHORT[r['pick']]:6s} {r['families'][r['pick']]['mean_brier']:>10.4f} {wins:>24s}")
    print("\nRegression:")
    for t in REGRESSION_TARGETS:
        if t not in report["regression"]:
            continue
        r = report["regression"][t]
        print(f"  {t:30s} {SHORT[r['pick']]:6s} mean R2={r['families'][r['pick']]['mean_r2']:.3f}")
    print(f"\nWrote {args.output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
