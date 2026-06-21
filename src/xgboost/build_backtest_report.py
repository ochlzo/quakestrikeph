"""Build a comprehensive, self-contained HTML report for an XGBoost backtest.

Reads the backtest summary written by ``backtest_aftershock_predictions.py``
(``backtest_metrics.json``) and, when available, the per-event predictions
(``backtest_predictions.csv``) to add reliability curves, probability
distributions, and a regression actual-vs-predicted view.

The report is single-family (XGBoost) and oriented around the Path B story:
natural-prevalence probabilities checked for calibration on the production
inference path, with no post-hoc isotonic step.

Usage:
    python src/xgboost/build_backtest_report.py
    python src/xgboost/build_backtest_report.py \
        --backtest-dir src/outputs/xgboost/backtests_mc_1_0 \
        --output src/docs/xgboost_backtest_report.html
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ACCENT = "#2563eb"

CLS_TARGETS = [
    "aftershock_24h",
    "aftershock_within_10km_24h",
    "aftershock_within_25km_24h",
    "aftershock_within_50km_24h",
    "aftershock_within_100km_24h",
    "aftershock_within_200km_24h",
]
TARGET_LABEL = {
    "aftershock_24h": "Any aftershock",
    "aftershock_within_10km_24h": "Within 10 km",
    "aftershock_within_25km_24h": "Within 25 km",
    "aftershock_within_50km_24h": "Within 50 km",
    "aftershock_within_100km_24h": "Within 100 km",
    "aftershock_within_200km_24h": "Within 200 km",
}
TARGET_COLOR = {
    "aftershock_24h": "#2563eb",
    "aftershock_within_10km_24h": "#dc2626",
    "aftershock_within_25km_24h": "#ea580c",
    "aftershock_within_50km_24h": "#d97706",
    "aftershock_within_100km_24h": "#16a34a",
    "aftershock_within_200km_24h": "#9333ea",
}
REG_LABEL = {
    "max_aftershock_mag_24h": "Max aftershock magnitude",
    "nearest_aftershock_distance_km_24h": "Nearest aftershock distance (km)",
    "median_aftershock_distance_km_24h": "Median aftershock distance (km)",
    "p90_aftershock_distance_km_24h": "P90 aftershock distance (km)",
}


def fmt(value, places=4):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "&mdash;"
    if isinstance(value, (int, float)):
        return f"{value:.{places}f}"
    return str(value)


def reliability_curve(y_true, y_prob, n_bins=10):
    """Uniform-bin reliability points: predicted mean vs observed rate per bin."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_index = np.clip(np.digitize(y_prob, edges[1:-1]), 0, n_bins - 1)
    points = []
    for b in range(n_bins):
        mask = bin_index == b
        if mask.any():
            points.append(
                {
                    "x": round(float(y_prob[mask].mean()), 4),
                    "y": round(float(y_true[mask].mean()), 4),
                    "n": int(mask.sum()),
                }
            )
    return points


def probability_histogram(y_prob, n_bins=20):
    counts, edges = np.histogram(y_prob, bins=n_bins, range=(0.0, 1.0))
    centers = (edges[:-1] + edges[1:]) / 2.0
    return [round(float(c), 3) for c in centers], [int(c) for c in counts]


def reg_scatter(actual, predicted, max_points=1800, seed=42):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    mask = ~(np.isnan(actual) | np.isnan(predicted))
    actual, predicted = actual[mask], predicted[mask]
    if len(actual) > max_points:
        rng = np.random.default_rng(seed)
        idx = rng.choice(len(actual), size=max_points, replace=False)
        actual, predicted = actual[idx], predicted[idx]
    return [{"x": round(float(a), 3), "y": round(float(p), 3)} for a, p in zip(actual, predicted)]


def kpi_card(label, value, sub):
    return (
        f'<div class="kpi"><div class="kpi-val">{value}</div>'
        f'<div class="kpi-lab">{label}</div><div class="kpi-sub">{sub}</div></div>'
    )


def cls_table_rows(classification):
    rows = []
    for target in CLS_TARGETS:
        m = classification.get(target)
        if m is None:
            continue
        rows.append(
            "<tr>"
            f'<td class="target">{TARGET_LABEL.get(target, target)}'
            f'<span class="sub">{target}</span></td>'
            f'<td>{m["count"]:,}</td>'
            f'<td>{m["positive_rate"]*100:.1f}%</td>'
            f'<td><b>{fmt(m.get("roc_auc"),4)}</b></td>'
            f'<td>{fmt(m.get("average_precision"),4)}</td>'
            f'<td><b>{fmt(m.get("brier"),4)}</b></td>'
            f'<td class="{calib_class(m.get("ece"))}">{fmt(m.get("ece"),4)}</td>'
            f'<td>{fmt(m.get("precision_at_0_5"),3)}</td>'
            f'<td>{fmt(m.get("recall_at_0_5"),3)}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def calib_class(ece):
    if ece is None:
        return ""
    if ece <= 0.02:
        return "good"
    if ece <= 0.05:
        return "ok"
    return "warn"


def reg_table_rows(regression):
    rows = []
    for target, m in regression.items():
        if not m or m.get("count", 0) == 0:
            continue
        rows.append(
            "<tr>"
            f'<td class="target">{REG_LABEL.get(target, target)}'
            f'<span class="sub">{target}</span></td>'
            f'<td>{m["count"]:,}</td>'
            f'<td><b>{fmt(m.get("r2"),3)}</b></td>'
            f'<td>{fmt(m.get("mae"),3)}</td>'
            f'<td>{fmt(m.get("rmse"),3)}</td>'
            f'<td>{fmt(m.get("actual_mean"),3)}</td>'
            f'<td>{fmt(m.get("predicted_mean"),3)}</td>'
            "</tr>"
        )
    return "\n".join(rows)


def dataset_js(label, points_or_values, color, line=False, fill=False):
    return (
        "{label:%s,data:%s,backgroundColor:%s,borderColor:%s,borderWidth:2,"
        "fill:%s,tension:0.1,pointRadius:%d,showLine:%s}"
        % (
            json.dumps(label),
            json.dumps(points_or_values),
            json.dumps(color + "cc"),
            json.dumps(color),
            "true" if fill else "false",
            3 if line else 0,
            "true" if line else "false",
        )
    )


def build(backtest_dir, output_path):
    backtest_dir = Path(backtest_dir)
    metrics_path = backtest_dir / "backtest_metrics.json"
    predictions_path = backtest_dir / "backtest_predictions.csv"
    if not metrics_path.exists():
        raise FileNotFoundError(f"Backtest metrics not found: {metrics_path}")

    report = json.loads(metrics_path.read_text(encoding="utf-8"))
    config = report["config"]
    classification = report["metrics"]["classification"]
    regression = report["metrics"]["regression"]

    # Headline (the primary occurrence target).
    head = classification.get("aftershock_24h", {})
    year_label = (
        f"{config.get('test_start_year')}"
        if config.get("test_end_year") in (None, config.get("test_start_year"))
        else f"{config.get('test_start_year')}–{config.get('test_end_year')}"
    )

    kpis = "".join(
        [
            kpi_card("Events backtested", f"{config.get('sampled_rows', 0):,}",
                     f"year {year_label} &middot; {config.get('sample_mode','')}"),
            kpi_card("ROC-AUC", fmt(head.get("roc_auc"), 4), "any aftershock (24h)"),
            kpi_card("Brier", fmt(head.get("brier"), 4), "probability accuracy"),
            kpi_card("ECE", fmt(head.get("ece"), 4), "calibration error"),
            kpi_card("Base rate", f"{head.get('positive_rate',0)*100:.1f}%", "natural prevalence"),
        ]
    )

    # Chart series from the metrics file (always available).
    cls_labels = [TARGET_LABEL[t] for t in CLS_TARGETS if t in classification]
    present = [t for t in CLS_TARGETS if t in classification]
    auc_vals = [round(classification[t]["roc_auc"], 4) for t in present]
    brier_vals = [round(classification[t]["brier"], 4) for t in present]
    ece_vals = [round(classification[t]["ece"], 4) for t in present]
    ap_vals = [round(classification[t]["average_precision"], 4) for t in present]

    # CSV-derived charts (reliability, histogram, regression) when present.
    reliability_datasets = []
    hist_labels, hist_counts = [], []
    reg_scatters = {}  # target -> list of {x,y} points (actual vs predicted)
    have_csv = predictions_path.exists()
    if have_csv:
        predictions = pd.read_csv(predictions_path, low_memory=False)
        for target in present:
            actual_col = f"actual_{target}"
            prob_col = f"predicted_probability_{target}"
            if actual_col in predictions and prob_col in predictions:
                y = predictions[actual_col].to_numpy(dtype=float)
                p = predictions[prob_col].to_numpy(dtype=float)
                pts = reliability_curve(y, p, n_bins=10)
                reliability_datasets.append(
                    dataset_js(TARGET_LABEL[target], pts, TARGET_COLOR[target], line=True)
                )
        if "predicted_probability_aftershock_24h" in predictions:
            hist_labels, hist_counts = probability_histogram(
                predictions["predicted_probability_aftershock_24h"].to_numpy(dtype=float)
            )
        # One predicted-vs-actual scatter per regression target present.
        for target in REG_LABEL:
            actual_col = f"actual_{target}"
            pred_col = f"predicted_{target}"
            if {actual_col, pred_col} <= set(predictions.columns):
                points = reg_scatter(predictions[actual_col], predictions[pred_col])
                if points:
                    reg_scatters[target] = points

    reliability_card = ""
    if reliability_datasets:
        reliability_card = """
<div class="card">
<h2>Reliability &mdash; calibration on the production path</h2>
<p class="lead">Predicted probability (x) vs observed frequency (y), 10 uniform bins. The dashed line is perfect calibration. Curves hugging it mean the raw probabilities are trustworthy with no post-hoc correction (Path B).</p>
<div class="chart-box tall"><canvas id="reliabilityChart"></canvas></div>
</div>"""

    hist_card = ""
    if hist_counts:
        hist_card = """
<div class="card"><h2>Predicted probability distribution</h2>
<p class="lead">How confident the model is across all backtested events (any-aftershock target).</p>
<div class="chart-box"><canvas id="histChart"></canvas></div></div>"""

    regression_card = ""
    if reg_scatters:
        scatter_cards = []
        for i, (target, points) in enumerate(reg_scatters.items()):
            unit = "magnitude" if "mag" in target else "km"
            scatter_cards.append(
                f'<div class="card"><h2>{REG_LABEL.get(target, target)} &mdash; predicted vs actual</h2>'
                f'<p class="lead">Each point is one event with an observed aftershock; '
                f'dashed line = perfect prediction ({len(points):,} shown, {unit}).</p>'
                f'<div class="chart-box tall"><canvas id="scatter{i}"></canvas></div></div>'
            )
        # Two scatters per row.
        regression_card = "".join(
            f'<div class="grid">{scatter_cards[j]}{scatter_cards[j + 1] if j + 1 < len(scatter_cards) else ""}</div>'
            for j in range(0, len(scatter_cards), 2)
        )

    csv_note = (
        ""
        if have_csv
        else '<div class="note">backtest_predictions.csv was not found, so reliability/'
        "distribution/regression charts are omitted. Re-run the backtest to enable them.</div>"
    )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>XGBoost Aftershock Backtest &mdash; {year_label}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1e293b;background:#f1f5f9;line-height:1.5}}
header{{background:linear-gradient(135deg,#1e3a8a,#0f172a);color:#fff;padding:34px 40px}}
header h1{{margin:0 0 6px;font-size:25px}}
header p{{margin:0;color:#cbd5e1;font-size:14px}}
.wrap{{max-width:1080px;margin:0 auto;padding:24px 20px 60px}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:22px 24px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
h2{{font-size:18px;margin:2px 0 4px;border-left:4px solid {ACCENT};padding-left:10px}}
.lead{{color:#64748b;font-size:13.5px;margin:2px 0 16px}}
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin:18px 0}}
@media(max-width:760px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
.kpi{{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
.kpi-val{{font-size:24px;font-weight:700;color:#0f172a}}
.kpi-lab{{font-size:12px;font-weight:600;color:#475569;margin-top:4px;text-transform:uppercase;letter-spacing:.03em}}
.kpi-sub{{font-size:11px;color:#94a3b8;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid #e2e8f0;vertical-align:top}}
th{{background:#f8fafc;font-weight:600;color:#475569;font-size:11.5px;text-transform:uppercase;letter-spacing:.03em}}
td b{{font-size:14px}}
.sub{{display:block;color:#94a3b8;font-size:11px;margin-top:2px;font-weight:400}}
td.target{{font-weight:600;min-width:140px}}
td.good{{background:#ecfdf5;color:#15803d;font-weight:600}}
td.ok{{background:#fefce8;color:#a16207;font-weight:600}}
td.warn{{background:#fef2f2;color:#b91c1c;font-weight:600}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
.chart-box{{position:relative;height:300px}}
.chart-box.tall{{height:360px}}
.note{{font-size:12.5px;color:#64748b;background:#f8fafc;border-left:3px solid #cbd5e1;padding:10px 12px;border-radius:0 6px 6px 0;margin-top:12px}}
code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}}
.meta td{{font-size:12.5px}} .meta td:first-child{{color:#64748b;width:230px}}
footer{{text-align:center;color:#94a3b8;font-size:12px;padding:20px}}
</style></head>
<body>
<header>
<h1>XGBoost Aftershock Backtest &mdash; {year_label}</h1>
<p>Production-path backtest &middot; natural-prevalence (Path B) probabilities, no post-hoc calibration &middot; {config.get('sampled_rows',0):,} events</p>
</header>
<div class="wrap">

<div class="kpis">{kpis}</div>

<div class="card">
<h2>What this report shows</h2>
<p class="lead">Every event was scored through the real serving path &mdash; features rebuilt per event from the raw catalog by <code>src/scripts/feature_engineering.py</code>, exactly as deployment does &mdash; then compared to the observed outcome.</p>
<ul style="font-size:13.5px;margin:0;padding-left:20px">
<li><b>ROC-AUC / AP</b> &mdash; ranking quality: can the model separate risky from safe events (higher is better, max 1.0).</li>
<li><b>Brier</b> &mdash; squared error of the predicted probability (lower is better); the primary score for a probability product.</li>
<li><b>ECE</b> &mdash; calibration error: does "70% chance" happen 70% of the time (lower is better). Green &le;0.02, amber &le;0.05.</li>
<li><b>R&sup2; / MAE</b> (regression) &mdash; variance explained and average error for the magnitude/distance targets.</li>
</ul>
{csv_note}
</div>

<div class="card">
<h2>Classification &mdash; metrics by target</h2>
<p class="lead">Cumulative containment: "at least one aftershock within R km in 24h". Nested and monotone by construction.</p>
<table>
<thead><tr><th>Target</th><th>n</th><th>Base rate</th><th>ROC-AUC</th><th>AP</th><th>Brier</th><th>ECE</th><th>Prec@.5</th><th>Rec@.5</th></tr></thead>
<tbody>
{cls_table_rows(classification)}
</tbody></table>
</div>

<div class="grid">
<div class="card"><h2>ROC-AUC by target</h2><div class="chart-box"><canvas id="aucChart"></canvas></div></div>
<div class="card"><h2>Brier &amp; ECE by target</h2><div class="chart-box"><canvas id="brierChart"></canvas></div></div>
</div>

{reliability_card}
{hist_card}

<div class="card">
<h2>Regression &mdash; magnitude &amp; distance</h2>
<p class="lead">Conditional targets (defined only when an aftershock occurs). Distance regressors are learned in log1p(km) space.</p>
<table>
<thead><tr><th>Target</th><th>n</th><th>R&sup2;</th><th>MAE</th><th>RMSE</th><th>Actual mean</th><th>Pred mean</th></tr></thead>
<tbody>
{reg_table_rows(regression)}
</tbody></table>
</div>

{regression_card}

<div class="card">
<h2>Run configuration</h2>
<table class="meta">
<tr><td>Model family</td><td>{config.get('model_family')}</td></tr>
<tr><td>Models directory</td><td><code>{config.get('models_dir')}</code></td></tr>
<tr><td>Labeled CSV</td><td><code>{config.get('labeled_csv')}</code></td></tr>
<tr><td>Historical catalog</td><td><code>{config.get('historical_csv')}</code></td></tr>
<tr><td>Test year(s)</td><td>{year_label}</td></tr>
<tr><td>Sample mode</td><td>{config.get('sample_mode')} ({config.get('sampled_rows',0):,} of {config.get('candidate_rows',0):,} candidates)</td></tr>
<tr><td>Minimum magnitude</td><td>{config.get('minimum_magnitude')}</td></tr>
</table>
</div>

</div>
<footer>Generated from {metrics_path.name}{' + ' + predictions_path.name if have_csv else ''}</footer>
__SCRIPT__
</body></html>"""

    script = """<script>
Chart.defaults.font.family="-apple-system,Segoe UI,Roboto,sans-serif";
Chart.defaults.font.size=11;
const CLS_LABELS=__CLS_LABELS__;
new Chart(document.getElementById('aucChart'),{type:'bar',data:{labels:CLS_LABELS,datasets:[{label:'ROC-AUC',data:__AUC__,backgroundColor:'#2563ebcc',borderColor:'#2563eb',borderWidth:1},{label:'Avg precision',data:__AP__,backgroundColor:'#16a34acc',borderColor:'#16a34a',borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{min:0.9,max:1.0,title:{display:true,text:'score'}},x:{ticks:{maxRotation:40,minRotation:20}}}}});
new Chart(document.getElementById('brierChart'),{type:'bar',data:{labels:CLS_LABELS,datasets:[{label:'Brier',data:__BRIER__,backgroundColor:'#dc2626cc',borderColor:'#dc2626',borderWidth:1},{label:'ECE',data:__ECE__,backgroundColor:'#d97706cc',borderColor:'#d97706',borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true,title:{display:true,text:'error (lower better)'}},x:{ticks:{maxRotation:40,minRotation:20}}}}});
__RELIABILITY__
__HIST__
__SCATTER__
</script>"""

    reliability_js = ""
    if reliability_datasets:
        ideal = "{label:'Perfect calibration',data:[{x:0,y:0},{x:1,y:1}],borderColor:'#94a3b8',borderDash:[6,4],borderWidth:1.5,pointRadius:0,showLine:true,fill:false}"
        datasets = "[" + ideal + "," + ",".join(reliability_datasets) + "]"
        reliability_js = (
            "new Chart(document.getElementById('reliabilityChart'),{type:'scatter',data:{datasets:"
            + datasets
            + "},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},"
            "scales:{x:{min:0,max:1,title:{display:true,text:'predicted probability'}},"
            "y:{min:0,max:1,title:{display:true,text:'observed frequency'}}}}});"
        )

    hist_js = ""
    if hist_counts:
        hist_js = (
            "new Chart(document.getElementById('histChart'),{type:'bar',data:{labels:"
            + json.dumps(hist_labels)
            + ",datasets:[{label:'events',data:"
            + json.dumps(hist_counts)
            + ",backgroundColor:'#2563ebcc',borderColor:'#2563eb',borderWidth:1}]},"
            "options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},"
            "scales:{x:{title:{display:true,text:'predicted P(aftershock)'}},y:{title:{display:true,text:'count'}}}}});"
        )

    scatter_blocks = []
    for i, (target, points) in enumerate(reg_scatters.items()):
        xs = [p["x"] for p in points]
        lo, hi = (min(xs), max(xs)) if xs else (0, 1)
        unit = "magnitude" if "mag" in target else "km"
        ideal = (
            "{label:'Perfect',data:[{x:%f,y:%f},{x:%f,y:%f}],borderColor:'#94a3b8',borderDash:[6,4],"
            "borderWidth:1.5,pointRadius:0,showLine:true}" % (lo, lo, hi, hi)
        )
        scatter_blocks.append(
            "new Chart(document.getElementById('scatter%d'),{type:'scatter',data:{datasets:[" % i
            + "{label:'events',data:"
            + json.dumps(points)
            + ",backgroundColor:'rgba(37,99,235,0.22)',pointRadius:2.5},"
            + ideal
            + "]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},"
            + "scales:{x:{title:{display:true,text:'actual (%s)'}},y:{title:{display:true,text:'predicted (%s)'}}}}});"
            % (unit, unit)
        )
    scatter_js = "\n".join(scatter_blocks)

    script = (
        script.replace("__CLS_LABELS__", json.dumps(cls_labels))
        .replace("__AUC__", json.dumps(auc_vals))
        .replace("__AP__", json.dumps(ap_vals))
        .replace("__BRIER__", json.dumps(brier_vals))
        .replace("__ECE__", json.dumps(ece_vals))
        .replace("__RELIABILITY__", reliability_js)
        .replace("__HIST__", hist_js)
        .replace("__SCATTER__", scatter_js)
    )
    html = html.replace("__SCRIPT__", script)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({len(html):,} bytes)")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backtest-dir",
        type=Path,
        default=Path("src/outputs/xgboost/backtests_mc_1_0"),
        help="Directory holding backtest_metrics.json (and optionally backtest_predictions.csv).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/docs/xgboost_backtest_report.html"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        build(args.backtest_dir, args.output)
    except Exception as error:
        import sys

        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
