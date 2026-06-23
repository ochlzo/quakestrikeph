"""Render the SEIS ensemble evaluation report (HTML) from the pick report JSON.

Consumes ``src/outputs/seis/backtest_pick_report.json`` (produced by
``build_pick_report_from_backtests.py``) and writes a single self-contained
``src/docs/seis_evaluation_report.html``: per-target metrics for all four
families on the 2025 backtest, with the weighted-score winner highlighted, plus
comparison charts and the recommended (= deployed) model per target.

The "pick" highlighted here is the weighted-score winner the report JSON records
(classification Brier 50 / ECE 25 / AP 15 / ROC 10; regression RMSE 50 / MAE 30 /
R^2 20), which is kept in sync with the deployed HYBRID_MODEL_MAPPING in
src/seis/predict.py.

Usage:
    python src/seis/build_html_report.py
    python src/seis/build_html_report.py \
        --pick-report src/outputs/seis/backtest_pick_report.json \
        --output src/docs/seis_evaluation_report.html
"""

import argparse
import json
from pathlib import Path

# Display order, labels, and chart colors (match the per-family reports).
FAMILIES = [
    ("xgboost", "XGBoost", "#2563eb"),
    ("lightgbm", "LightGBM", "#16a34a"),
    ("random_forest", "Random Forest", "#d97706"),
    ("catboost", "CatBoost", "#9333ea"),
]
DISP = {key: name for key, name, _ in FAMILIES}

CLS_TARGETS = [
    ("aftershock_24h", "Any aftershock (24h)"),
    ("aftershock_within_10km_24h", "Aftershock within 10 km"),
    ("aftershock_within_25km_24h", "Aftershock within 25 km"),
    ("aftershock_within_50km_24h", "Aftershock within 50 km"),
    ("aftershock_beyond_50km_24h", "Aftershock beyond 50 km"),
]
REG_TARGETS = [
    ("max_aftershock_mag_24h", "Max aftershock magnitude"),
    ("nearest_aftershock_distance_km_24h", "Nearest aftershock distance (km)"),
    ("median_aftershock_distance_km_24h", "Median aftershock distance (km)"),
    ("p90_aftershock_distance_km_24h", "P90 aftershock distance (km)"),
]
CLS_CHART_LABELS = [
    "Any aftershock (24h)", "Aftershock within 10 km", "Aftershock within 25 km",
    "Aftershock within 50 km", "Aftershock beyond 50 km",
]
REG_CHART_LABELS = ["Max magnitude", "Nearest dist (km)", "Median dist (km)", "P90 dist (km)"]

CLS_WEIGHT_ORDER = [("brier", "Brier"), ("ece", "ECE"), ("average_precision", "AP"), ("roc_auc", "ROC")]
REG_WEIGHT_ORDER = [("rmse", "RMSE"), ("mae", "MAE"), ("r2", "R²")]


def weight_text(weights, order):
    return " · ".join(
        f"{label} {int(round(weights[key] * 100))}%" for key, label in order if key in weights
    )


def overall_classification_pick(classification):
    """The single multiclass family chosen across all 5 classification targets.

    Mirrors build_pick_report_from_backtests.py: sum each family's per-target
    weighted score, return the highest. Derived from the pick report so this
    text can never drift from the data after a re-train.
    """
    overall = {}
    for tkey, _ in CLS_TARGETS:
        for fam, score in classification[tkey]["scores"].items():
            overall[fam] = overall.get(fam, 0.0) + score
    return max(overall, key=overall.get)


def score_sub(node):
    score = node.get("pick_score")
    return f'<span class="sub">score {score:.3f}</span>' if score is not None else ""


def cls_rows(classification):
    rows = []
    for tkey, tlabel in CLS_TARGETS:
        node = classification[tkey]
        pick = node["pick"]
        raw_winner = node.get("raw_winner", pick)
        cells = ""
        for fkey, _, _ in FAMILIES:
            m = node["families"][fkey]
            win = "win" if fkey == pick else ""
            
            badge = ""
            if fkey == pick:
                badge = '<span class="badge ok">ensemble pick</span>'
            elif fkey == raw_winner:
                badge = '<span class="badge" style="background:#f1f5f9;color:#475569">best standalone</span>'
                
            cells += (
                f'<td class="{win}"><b>{m["brier"]:.4f}</b>'
                f'<span class="sub">ECE {m["ece"]:.3f} · AUC {m["roc_auc"]:.3f} '
                f'· AP {m["average_precision"]:.3f}</span>{badge}</td>'
            )
        head = (
            f'<td class="target">{tlabel}'
            f'<span class="sub">prevalence {node["prevalence"] * 100:.1f}% · n={node["count"]:,}</span></td>'
        )
        rec = f'<td class="pick">{DISP[pick]}{score_sub(node)}</td>'
        rows.append(f"<tr>{head}{cells}{rec}</tr>")
    return "\n".join(rows)


def reg_rows(regression):
    rows = []
    for tkey, tlabel in REG_TARGETS:
        node = regression[tkey]
        pick = node["pick"]
        cells = ""
        for fkey, _, _ in FAMILIES:
            m = node["families"][fkey]
            win = "win" if fkey == pick else ""
            badge = '<span class="badge ok">ensemble pick</span>' if fkey == pick else ""
            cells += (
                f'<td class="{win}"><b>R² {m["r2"]:.3f}</b>'
                f'<span class="sub">MAE {m["mae"]:.3f} · RMSE {m["rmse"]:.3f}</span>{badge}</td>'
            )
        rec = f'<td class="pick">{DISP[pick]}{score_sub(node)}</td>'
        rows.append(f'<tr><td class="target">{tlabel}</td>{cells}{rec}</tr>')
    return "\n".join(rows)


def recommended_rows(classification, regression):
    parts = []
    for tkey, tlabel in CLS_TARGETS:
        parts.append(f"<tr><td>{tlabel}</td><td class='pick'>{DISP[classification[tkey]['pick']]}</td></tr>")
    for tkey, tlabel in REG_TARGETS:
        parts.append(f"<tr><td>{tlabel} (reg.)</td><td class='pick'>{DISP[regression[tkey]['pick']]}</td></tr>")
    return "".join(parts)


def chart_datasets(node_map, targets, metric):
    parts = []
    for fkey, fname, color in FAMILIES:
        data = [round(node_map[t]["families"][fkey][metric], 4) for t, _ in targets]
        parts.append(
            "{label:%s,data:%s,backgroundColor:'%scc',borderColor:'%s',borderWidth:2,fill:false}"
            % (json.dumps(fname), json.dumps(data), color, color)
        )
    return "[" + ",".join(parts) + "]"


def build(pick_report_path, output_path):
    report = json.loads(Path(pick_report_path).read_text(encoding="utf-8"))
    classification = report["classification"]
    regression = report["regression"]
    scoring = report.get("scoring", {})
    cls_w = weight_text(scoring.get("classification_weights", {}), CLS_WEIGHT_ORDER)
    reg_w = weight_text(scoring.get("regression_weights", {}), REG_WEIGHT_ORDER)
    rows = report.get("evaluation_rows")
    year = report.get("test_start_year")
    end_year = report.get("test_end_year")
    year_label = f"{year}" if end_year in (None, year) else f"{year}–{end_year}"
    rows_label = f"{rows:,}" if isinstance(rows, int) else "?"

    weights_line = ""
    if cls_w or reg_w:
        weights_line = (
            f'<li><b>Pick = weighted score</b> &mdash; per target, each metric is min-max '
            f'normalized across the four families (1 = best) then weighted. '
            f'Classification: {cls_w}. Regression: {reg_w}.</li>'
        )

    # The overall classification winner is the family whose per-target scores sum
    # highest -- derived from the report so this sentence never goes stale.
    cls_pick = overall_classification_pick(classification)
    cls_pick_line = (
        f'{DISP[cls_pick]} was selected overall as it had the highest summed '
        f'classification score across all 5 targets.'
    )

    html = TEMPLATE
    html = html.replace("__YEAR__", year_label)
    html = html.replace("__ROWS__", rows_label)
    html = html.replace("__WEIGHTS_LINE__", weights_line)
    html = html.replace("__CLS_PICK_LINE__", cls_pick_line)
    html = html.replace("__CLS_ROWS__", cls_rows(classification))
    html = html.replace("__REG_ROWS__", reg_rows(regression))
    html = html.replace("__REC_ROWS__", recommended_rows(classification, regression))
    html = html.replace("__CLS_LABELS__", json.dumps(CLS_CHART_LABELS))
    html = html.replace("__REG_LABELS__", json.dumps(REG_CHART_LABELS))
    html = html.replace("__BRIER_DS__", chart_datasets(classification, CLS_TARGETS, "brier"))
    html = html.replace("__AUC_DS__", chart_datasets(classification, CLS_TARGETS, "roc_auc"))
    html = html.replace("__AP_DS__", chart_datasets(classification, CLS_TARGETS, "average_precision"))
    html = html.replace("__REG_DS__", chart_datasets(regression, REG_TARGETS, "r2"))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Wrote {output_path} ({len(html):,} bytes)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEIS Aftershock Models — Evaluation Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#0f172a;--card:#fff;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:#f1f5f9;line-height:1.5}
header{background:linear-gradient(135deg,#1e3a8a,#0f172a);color:#fff;padding:36px 40px}
header h1{margin:0 0 6px;font-size:26px}
header p{margin:0;color:#cbd5e1;font-size:14px}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 60px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}
h2{font-size:19px;margin:4px 0 4px;border-left:4px solid #2563eb;padding-left:10px}
.lead{color:var(--muted);font-size:14px;margin:2px 0 16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f8fafc;font-weight:600;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td b{font-size:14px}
.sub{display:block;color:var(--muted);font-size:11px;margin-top:2px}
td.target{font-weight:600;min-width:150px}
td.win{background:#ecfdf5}
td.win b{color:#15803d}
td.pick{font-weight:600;color:#1d4ed8;white-space:nowrap}
td.na{color:#94a3b8;font-style:italic}
.badge{display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;margin-top:3px}
.badge.ok{background:#dcfce7;color:#15803d}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
.chart-box{position:relative;height:300px}
.note{font-size:12.5px;color:var(--muted);background:#f8fafc;border-left:3px solid #cbd5e1;padding:10px 12px;border-radius:0 6px 6px 0;margin-top:12px}
.legend{font-size:12px;color:var(--muted);margin-top:8px}
code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}
footer{text-align:center;color:#94a3b8;font-size:12px;padding:20px}
</style></head>
<body>
<header>
<h1>SEIS Aftershock Models — Evaluation Report</h1>
<p>4 model families (XGBoost · LightGBM · Random Forest · CatBoost) across 10 prediction targets · evaluated on the __YEAR__ backtest (__ROWS__ events) at real-world prevalence</p>
</header>
<div class="wrap">

<div class="card">
<h2>How to read this report</h2>
<p class="lead">Each target is predicted by all 4 model families.</p>
<ul style="font-size:13.5px;margin:0;padding-left:20px">
<li><b>Brier</b> — accuracy of the predicted probability (lower is better). Under Path B these are raw model probabilities, no post-hoc calibration.</li>
<li><b>ECE</b> — calibration error: how closely "70% chance" matches reality (lower is better).</li>
<li><b>ROC-AUC / AP</b> — ranking quality: can the model tell risky events from safe ones (higher is better, max 1.0).</li>
<li><b>R² / MAE / RMSE</b> (regression) — variance explained and error magnitude; RMSE punishes large misses most.</li>
__WEIGHTS_LINE__
<li><b>Ensemble Pick</b> — highlighted in green. For all classification targets, a single multi-class model (<code>aftershock_spatial_zone_24h</code>) must be served to guarantee disjoint probabilities. __CLS_PICK_LINE__</li>
<li>Green cell = the chosen ensemble model for that target (right column).</li>
</ul>
<div class="note">Every family is trained at natural prevalence (Path B — no post-hoc calibration) and scored on the __YEAR__ backtest through the production inference path. The highlighted family per target is the chosen ensemble model, and this selection <b>is the deployed mapping</b> (kept in sync with HYBRID_MODEL_MAPPING in src/seis/predict.py).</div>
</div>

<div class="card">
<h2>Classification — metrics by target &amp; model</h2>
<p class="lead">Bold = Brier (primary, Path B — natural prevalence). Smaller line = ECE · AUC · AP. Green = weighted-score winner.</p>
<table>
<thead><tr><th>Target</th><th>XGBoost</th><th>LightGBM</th><th>Random Forest</th><th>CatBoost</th><th>Recommended</th></tr></thead>
<tbody>
__CLS_ROWS__
</tbody></table>
</div>

<div class="grid">
<div class="card"><h2>Brier (lower better)</h2><div class="chart-box"><canvas id="brierChart"></canvas></div></div>
<div class="card"><h2>ROC-AUC (higher better)</h2><div class="chart-box"><canvas id="aucChart"></canvas></div></div>
</div>

<div class="grid">
<div class="card"><h2>Average Precision (higher better)</h2><div class="chart-box"><canvas id="apChart"></canvas></div></div>
<div class="card"><h2>Regression R² (higher better)</h2><div class="chart-box"><canvas id="regChart"></canvas></div>
<div class="legend">All 4 families train all 4 regressors.</div></div>
</div>

<div class="card">
<h2>Regression — magnitude &amp; distance</h2>
<p class="lead">Predicting the largest aftershock’s size and how far it reaches. Bold = R²; smaller line = MAE · RMSE. Green = weighted-score winner.</p>
<table>
<thead><tr><th>Target</th><th>XGBoost</th><th>LightGBM</th><th>Random Forest</th><th>CatBoost</th><th>Recommended</th></tr></thead>
<tbody>
__REG_ROWS__
</tbody></table>
</div>

<div class="card">
<h2>Recommended model per target (the __YEAR__ backtest)</h2>
<p class="lead">Weighted-score winner per target — this is the deployed HYBRID_MODEL_MAPPING.</p>
<table style="max-width:520px"><thead><tr><th>Target</th><th>Model</th></tr></thead><tbody>
__REC_ROWS__
</tbody></table>
</div>

</div>
<footer>Generated from backtest_pick_report.json</footer>
<script>
Chart.defaults.font.family="-apple-system,Segoe UI,Roboto,sans-serif";
Chart.defaults.font.size=11;
const LABELS=__CLS_LABELS__;
function bar(id,datasets,opts){new Chart(document.getElementById(id),{type:'bar',data:{labels:LABELS,datasets:datasets},options:Object.assign({responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{ticks:{maxRotation:55,minRotation:35}}}},opts||{})});}
bar('brierChart',__BRIER_DS__,{scales:{y:{beginAtZero:true,title:{display:true,text:'Brier'}}}});
bar('aucChart',__AUC_DS__,{scales:{y:{min:0.9,max:1.0,title:{display:true,text:'ROC-AUC'}}}});
bar('apChart',__AP_DS__,{scales:{y:{min:0.6,max:1.0,title:{display:true,text:'Average Precision'}}}});
new Chart(document.getElementById('regChart'),{type:'bar',data:{labels:__REG_LABELS__,datasets:__REG_DS__},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true,max:1.0,title:{display:true,text:'R2'}}}}});
</script>
</body></html>"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pick-report", type=Path, default=Path("src/outputs/seis/backtest_pick_report.json"))
    p.add_argument("--output", type=Path, default=Path("src/docs/seis_evaluation_report.html"))
    return p.parse_args()


if __name__ == "__main__":
    try:
        args = parse_args()
        build(args.pick_report, args.output)
    except Exception as error:
        import sys

        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
