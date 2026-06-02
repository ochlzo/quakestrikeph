import csv
import json
from datetime import datetime
from pathlib import Path


RF_TRAINING_METRICS = Path("src/outputs/random-forest/models_mc_1_0/metrics.json")
RF_BACKTEST_METRICS = Path("src/outputs/random-forest/backtests_mc_1_0/backtest_metrics.json")
MODEL_COMPARISON_CSV = Path(
    "src/outputs/model-comparison/mc_1_0/lightgbm_vs_random_forest_metrics.csv"
)
BACKTEST_COMPARISON_CSV = Path(
    "src/outputs/model-comparison/mc_1_0/lightgbm_vs_random_forest_backtest_metrics.csv"
)
RF_REPORT = Path("src/reports/random_forest_model_report.html")
COMPARISON_REPORT = Path("src/reports/lightgbm_vs_random_forest_comparison_report.html")


CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_dist_0_10km_24h",
    "aftershock_dist_10_25km_24h",
    "aftershock_dist_25_50km_24h",
    "aftershock_dist_50_100km_24h",
    "aftershock_dist_100_200km_24h",
    "aftershock_dist_200_pluskm_24h",
]
REGRESSION_TARGET = "max_aftershock_mag_24h"


TARGET_LABELS = {
    "aftershock_24h": "Any aftershock within 24h",
    "aftershock_dist_0_10km_24h": "Aftershock 0-10 km within 24h",
    "aftershock_dist_10_25km_24h": "Aftershock 10-25 km within 24h",
    "aftershock_dist_25_50km_24h": "Aftershock 25-50 km within 24h",
    "aftershock_dist_50_100km_24h": "Aftershock 50-100 km within 24h",
    "aftershock_dist_100_200km_24h": "Aftershock 100-200 km within 24h",
    "aftershock_dist_200_pluskm_24h": "Aftershock 200+ km within 24h",
    "max_aftershock_mag_24h": "Maximum aftershock magnitude within 24h",
}


CLASSIFIER_RECOMMENDATIONS = {
    "aftershock_24h": (
        "LightGBM",
        "Use LightGBM for current deployment: backtest Brier and recall at 0.5 are materially better, while RF only has a tiny AP edge.",
    ),
    "aftershock_dist_0_10km_24h": (
        "LightGBM",
        "Use LightGBM: RF AUC is essentially tied, but LightGBM has better AP, Brier, and recall at 0.5.",
    ),
    "aftershock_dist_10_25km_24h": (
        "LightGBM",
        "Use LightGBM: it wins backtest AUC, AP, Brier, and recall by a wide margin.",
    ),
    "aftershock_dist_25_50km_24h": (
        "LightGBM",
        "Use LightGBM for current binary alerts because its Brier and recall are better. RF is a ranking candidate after threshold calibration.",
    ),
    "aftershock_dist_50_100km_24h": (
        "LightGBM",
        "Use LightGBM for current binary alerts. RF ranks better on AUC/AP, but its default threshold is too conservative and Brier is worse.",
    ),
    "aftershock_dist_100_200km_24h": (
        "LightGBM",
        "Use LightGBM for current alerts: it has better backtest AUC, Brier, and recall. RF has a small AP edge worth revisiting after calibration.",
    ),
    "aftershock_dist_200_pluskm_24h": (
        "LightGBM",
        "Use LightGBM for calibrated alerting because Brier and recall are better. RF has stronger ranking metrics and should be threshold-tuned separately.",
    ),
}


CSS = """
:root {
  --ink: #17202c;
  --muted: #5e6b7a;
  --line: #d8e0e8;
  --paper: #f7f9fb;
  --panel: #ffffff;
  --green: #1f8f5f;
  --blue: #2d64c8;
  --amber: #b56a00;
  --red: #b93838;
  --gray: #7c8794;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font: 14px/1.55 "Segoe UI", Arial, sans-serif;
}
.page { max-width: 1240px; margin: 0 auto; padding: 32px 24px 52px; }
header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  align-items: end;
  padding-bottom: 20px;
  border-bottom: 2px solid var(--ink);
}
h1, h2, h3 { margin: 0; letter-spacing: 0; line-height: 1.15; }
h1 { font-size: 34px; }
h2 { margin-top: 34px; margin-bottom: 14px; font-size: 22px; }
h3 { font-size: 15px; margin-bottom: 8px; }
p { margin: 0 0 12px; }
.subtitle { color: var(--muted); max-width: 820px; margin-top: 10px; font-size: 15px; }
.stamp {
  text-align: right;
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 18px;
}
.metric {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
}
.metric strong { display: block; font-size: 22px; line-height: 1.1; margin-top: 3px; }
.metric span { color: var(--muted); font-size: 12px; }
.note {
  background: #fff7e8;
  border-left: 4px solid var(--amber);
  padding: 12px 14px;
  margin: 12px 0 18px;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--panel);
  border: 1px solid var(--line);
}
th, td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  text-align: right;
  vertical-align: top;
}
th:first-child, td:first-child,
th:nth-child(2), td:nth-child(2) { text-align: left; }
th {
  background: #eef3f8;
  color: #233044;
  font-weight: 700;
  font-size: 12px;
}
tr:last-child td { border-bottom: 0; }
.target { font-family: Consolas, "Courier New", monospace; font-size: 12px; }
.winner {
  display: inline-block;
  min-width: 86px;
  padding: 2px 8px;
  border-radius: 999px;
  color: white;
  text-align: center;
  font-size: 12px;
}
.winner.lightgbm { background: var(--blue); }
.winner.random_forest { background: var(--green); }
.winner.mixed { background: var(--amber); }
.small { color: var(--muted); font-size: 12px; }
.sources {
  font-family: Consolas, "Courier New", monospace;
  color: var(--muted);
  background: #f0f3f6;
  padding: 12px;
  border-radius: 6px;
  overflow-wrap: anywhere;
}
@media (max-width: 860px) {
  header, .grid { grid-template-columns: 1fr; }
  .stamp { text-align: left; }
  table { font-size: 12px; }
  th, td { padding: 7px 6px; }
}
"""


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_comparison(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {
        (row["target"], row["metric"]): row
        for row in rows
    }


def fmt(value, digits=4):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.1f}%"


def html_doc(title, subtitle, body):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>{CSS}</style>
</head>
<body>
  <main class="page">
    <header>
      <div>
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>
      </div>
      <div class="stamp">Generated<br>{generated_at}</div>
    </header>
    {body}
  </main>
</body>
</html>
"""


def rf_training_row(model):
    test = model["test"]
    if model["task"] == "classification":
        return (
            f"<tr><td class='target'>{model['target']}</td>"
            f"<td>{TARGET_LABELS[model['target']]}</td>"
            f"<td>{fmt(test['roc_auc'])}</td>"
            f"<td>{fmt(test['average_precision'])}</td>"
            f"<td>{fmt(test['brier'])}</td>"
            f"<td>{fmt(test['precision_at_0_5'])}</td>"
            f"<td>{fmt(test['recall_at_0_5'])}</td>"
            f"<td>{pct(test['predicted_positive_rate_at_0_5'])}</td></tr>"
        )
    return (
        f"<tr><td class='target'>{model['target']}</td>"
        f"<td>{TARGET_LABELS[model['target']]}</td>"
        f"<td colspan='2'>regression</td>"
        f"<td>MAE {fmt(test['mae'])}</td>"
        f"<td>RMSE {fmt(test['rmse'])}</td>"
        f"<td>R2 {fmt(test['r2'])}</td>"
        f"<td>-</td></tr>"
    )


def rf_backtest_row(target, metrics):
    if target in metrics["classification"]:
        item = metrics["classification"][target]
        return (
            f"<tr><td class='target'>{target}</td>"
            f"<td>{TARGET_LABELS[target]}</td>"
            f"<td>{fmt(item['roc_auc'])}</td>"
            f"<td>{fmt(item['average_precision'])}</td>"
            f"<td>{fmt(item['brier'])}</td>"
            f"<td>{fmt(item['precision_at_0_5'])}</td>"
            f"<td>{fmt(item['recall_at_0_5'])}</td>"
            f"<td>{pct(item['predicted_positive_rate_at_0_5'])}</td></tr>"
        )
    item = metrics["regression"][target]
    return (
        f"<tr><td class='target'>{target}</td>"
        f"<td>{TARGET_LABELS[target]}</td>"
        f"<td colspan='2'>regression</td>"
        f"<td>MAE {fmt(item['mae'])}</td>"
        f"<td>RMSE {fmt(item['rmse'])}</td>"
        f"<td>R2 {fmt(item['r2'])}</td>"
        f"<td>{item['count']} cases</td></tr>"
    )


def winner_badge(winner):
    class_name = winner.replace(" ", "_").lower()
    return f"<span class='winner {class_name}'>{winner}</span>"


def comparison_value(comparison, target, metric, model):
    return comparison[(target, metric)][model]


def comparison_delta(comparison, target, metric):
    return comparison[(target, metric)]["rf_minus_lightgbm"]


def recommendation_row(target, split_comparison, backtest_comparison):
    if target == REGRESSION_TARGET:
        recommendation = "Random Forest"
        reason = (
            "RF wins MAE, RMSE, and R2 in both chronological test-split metrics "
            "and the production-style backtest."
        )
        return (
            f"<tr><td class='target'>{target}</td><td>{TARGET_LABELS[target]}</td>"
            f"<td>{winner_badge(recommendation)}</td><td>{reason}</td>"
            f"<td>Backtest delta: MAE {fmt(comparison_delta(backtest_comparison, target, 'mae'))}, "
            f"RMSE {fmt(comparison_delta(backtest_comparison, target, 'rmse'))}, "
            f"R2 {fmt(comparison_delta(backtest_comparison, target, 'r2'))}</td></tr>"
        )

    recommendation, reason = CLASSIFIER_RECOMMENDATIONS[target]
    auc_winner = backtest_comparison[(target, "roc_auc")]["winner"]
    ap_winner = backtest_comparison[(target, "average_precision")]["winner"]
    brier_winner = backtest_comparison[(target, "brier")]["winner"]
    recall_winner = backtest_comparison[(target, "recall_at_0_5")]["winner"]
    signal = (
        f"Backtest winners: AUC {auc_winner}, AP {ap_winner}, "
        f"Brier {brier_winner}, Recall@0.5 {recall_winner}."
    )
    return (
        f"<tr><td class='target'>{target}</td><td>{TARGET_LABELS[target]}</td>"
        f"<td>{winner_badge(recommendation)}</td><td>{reason}</td>"
        f"<td>{signal}</td></tr>"
    )


def build_rf_report():
    training = read_json(RF_TRAINING_METRICS)
    backtest = read_json(RF_BACKTEST_METRICS)
    backtest_metrics = backtest["metrics"]

    classifier_models = [
        model for model in training["models"]
        if model["task"] == "classification"
    ]
    mean_auc = np_mean([model["test"]["roc_auc"] for model in classifier_models])
    mean_ap = np_mean([model["test"]["average_precision"] for model in classifier_models])
    mean_backtest_auc = np_mean([
        backtest_metrics["classification"][target]["roc_auc"]
        for target in CLASSIFICATION_TARGETS
    ])
    mean_backtest_ap = np_mean([
        backtest_metrics["classification"][target]["average_precision"]
        for target in CLASSIFICATION_TARGETS
    ])
    regression = backtest_metrics["regression"][REGRESSION_TARGET]

    training_rows = "\n".join(rf_training_row(model) for model in training["models"])
    backtest_rows = "\n".join(
        rf_backtest_row(target, backtest_metrics)
        for target in [*CLASSIFICATION_TARGETS, REGRESSION_TARGET]
    )

    body = f"""
    <section class="grid">
      <div class="metric"><span>Mean test ROC AUC</span><strong>{fmt(mean_auc)}</strong></div>
      <div class="metric"><span>Mean test AP</span><strong>{fmt(mean_ap)}</strong></div>
      <div class="metric"><span>Mean backtest ROC AUC</span><strong>{fmt(mean_backtest_auc)}</strong></div>
      <div class="metric"><span>Backtest magnitude MAE</span><strong>{fmt(regression['mae'])}</strong></div>
    </section>

    <h2>Executive Summary</h2>
    <p>The Random Forest baseline uses the same leakage-safe mc_1_0 dataset and feature contract as LightGBM. It trains seven binary classifiers and one positive-case magnitude regressor.</p>
    <div class="note">The RF classifiers rank events well, but the default 0.5 decision threshold is conservative. Precision is often high, while recall is low for distance-bin targets. The RF magnitude regressor is the strongest Random Forest result.</div>

    <h2>Chronological Test-Split Metrics</h2>
    <table>
      <thead><tr><th>Target</th><th>Description</th><th>ROC AUC</th><th>AP</th><th>Brier / MAE</th><th>Precision / RMSE</th><th>Recall / R2</th><th>Predicted positive</th></tr></thead>
      <tbody>{training_rows}</tbody>
    </table>

    <h2>Production-Style Backtest Metrics</h2>
    <p class="small">Backtest config: {backtest['config']['sample_mode']} sample, {backtest['config']['sampled_rows']} rows, test_start_year {backtest['config']['test_start_year']}.</p>
    <table>
      <thead><tr><th>Target</th><th>Description</th><th>ROC AUC</th><th>AP</th><th>Brier / MAE</th><th>Precision / RMSE</th><th>Recall / R2</th><th>Predicted positive</th></tr></thead>
      <tbody>{backtest_rows}</tbody>
    </table>

    <h2>Artifacts</h2>
    <div class="sources">
      training metrics: {RF_TRAINING_METRICS}<br>
      backtest metrics: {RF_BACKTEST_METRICS}<br>
      predictions: src/outputs/random-forest/backtests_mc_1_0/backtest_predictions.csv<br>
      models: src/outputs/random-forest/models_mc_1_0/
    </div>
    """
    RF_REPORT.write_text(
        html_doc(
            "QuakeStrikePH Random Forest Model Report",
            "Random Forest baseline for 24h aftershock likelihood, distance-bin likelihood, and maximum aftershock magnitude.",
            body,
        ),
        encoding="utf-8",
    )


def build_comparison_report():
    split_comparison = read_comparison(MODEL_COMPARISON_CSV)
    backtest_comparison = read_comparison(BACKTEST_COMPARISON_CSV)

    recommendation_rows = "\n".join(
        recommendation_row(target, split_comparison, backtest_comparison)
        for target in [*CLASSIFICATION_TARGETS, REGRESSION_TARGET]
    )

    backtest_rows = []
    for target in CLASSIFICATION_TARGETS:
        backtest_rows.append(
            f"<tr><td class='target'>{target}</td><td>{TARGET_LABELS[target]}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'roc_auc', 'lightgbm'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'roc_auc', 'random_forest'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'average_precision', 'lightgbm'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'average_precision', 'random_forest'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'brier', 'lightgbm'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'brier', 'random_forest'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'recall_at_0_5', 'lightgbm'))}</td>"
            f"<td>{fmt(comparison_value(backtest_comparison, target, 'recall_at_0_5', 'random_forest'))}</td></tr>"
        )
    backtest_rows.append(
        f"<tr><td class='target'>{REGRESSION_TARGET}</td><td>{TARGET_LABELS[REGRESSION_TARGET]}</td>"
        f"<td colspan='2'>MAE: LGBM {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'mae', 'lightgbm'))} / RF {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'mae', 'random_forest'))}</td>"
        f"<td colspan='2'>RMSE: LGBM {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'rmse', 'lightgbm'))} / RF {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'rmse', 'random_forest'))}</td>"
        f"<td colspan='2'>R2: LGBM {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'r2', 'lightgbm'))} / RF {fmt(comparison_value(backtest_comparison, REGRESSION_TARGET, 'r2', 'random_forest'))}</td>"
        f"<td colspan='2'>{winner_badge('Random Forest')}</td></tr>"
    )

    body = f"""
    <section class="grid">
      <div class="metric"><span>Classifier deployment recommendation</span><strong>LightGBM</strong></div>
      <div class="metric"><span>Magnitude recommendation</span><strong>RF</strong></div>
      <div class="metric"><span>RF tuning priority</span><strong>Thresholds</strong></div>
      <div class="metric"><span>Primary evidence</span><strong>Backtest</strong></div>
    </section>

    <h2>Recommendation Summary</h2>
    <p>Recommendations prioritize production-style backtest behavior. For classifiers, calibrated probability quality and usable recall at the current 0.5 threshold are weighted ahead of small AUC/AP wins. For regression, lower MAE/RMSE and higher R2 decide the recommendation.</p>
    <table>
      <thead><tr><th>Target</th><th>Description</th><th>Recommended model</th><th>Reason</th><th>Evidence signal</th></tr></thead>
      <tbody>{recommendation_rows}</tbody>
    </table>

    <h2>Backtest Comparison</h2>
    <table>
      <thead><tr><th>Target</th><th>Description</th><th>LGBM AUC</th><th>RF AUC</th><th>LGBM AP</th><th>RF AP</th><th>LGBM Brier</th><th>RF Brier</th><th>LGBM Recall</th><th>RF Recall</th></tr></thead>
      <tbody>{"".join(backtest_rows)}</tbody>
    </table>

    <h2>Interpretation</h2>
    <p>LightGBM remains the safer classifier family for current deployment because it produces better-calibrated probabilities and much better recall at the current operating threshold. Random Forest is useful as a ranking baseline on several distance-bin targets, but it should not replace LightGBM classifiers until threshold tuning or probability calibration is performed.</p>
    <p>Random Forest is the recommended model for <span class="target">{REGRESSION_TARGET}</span>. It improves the production-style backtest magnitude estimate on MAE, RMSE, and R2.</p>

    <h2>Artifacts</h2>
    <div class="sources">
      split comparison: {MODEL_COMPARISON_CSV}<br>
      backtest comparison: {BACKTEST_COMPARISON_CSV}<br>
      LightGBM backtest: src/outputs/lightgbm/backtests_mc_1_0/backtest_metrics.json<br>
      Random Forest backtest: {RF_BACKTEST_METRICS}
    </div>
    """
    COMPARISON_REPORT.write_text(
        html_doc(
            "QuakeStrikePH LightGBM vs Random Forest Comparison",
            "Per-target comparison and deployment recommendation using chronological test-split metrics plus the production-style backtest.",
            body,
        ),
        encoding="utf-8",
    )


def np_mean(values):
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def main():
    build_rf_report()
    build_comparison_report()
    print(f"Wrote {RF_REPORT}")
    print(f"Wrote {COMPARISON_REPORT}")


if __name__ == "__main__":
    main()
