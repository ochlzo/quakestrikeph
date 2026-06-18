"""Generate a self-contained HTML evaluation report from a pick report.

Renders any report shaped like repick_report.json / test_pick_report.json:
each family's metrics per target plus the highlighted (best) family. Used for
both the deployment report (validation-selected picks) and the descriptive
test-set report, via CLI flags.
"""

import argparse
import json
from pathlib import Path

FAMILIES = ["xgboost", "lightgbm", "random_forest", "catboost"]
LABEL = {"xgboost": "XGBoost", "lightgbm": "LightGBM", "random_forest": "Random Forest", "catboost": "CatBoost"}
COLOR = {"xgboost": "#2563eb", "lightgbm": "#16a34a", "random_forest": "#d97706", "catboost": "#9333ea"}

FAMILY_TH = "".join(f"<th>{LABEL[f]}</th>" for f in FAMILIES)

TARGET_LABEL = {
    "aftershock_24h": "Any aftershock (24h)",
    "aftershock_dist_0_10km_24h": "Aftershock 0-10 km",
    "aftershock_dist_10_25km_24h": "Aftershock 10-25 km",
    "aftershock_dist_25_50km_24h": "Aftershock 25-50 km",
    "aftershock_dist_50_100km_24h": "Aftershock 50-100 km",
    "aftershock_dist_100_200km_24h": "Aftershock 100-200 km",
    "aftershock_dist_200_pluskm_24h": "Aftershock 200+ km",
}
REG_LABEL = {
    "max_aftershock_mag_24h": "Max aftershock magnitude",
    "max_aftershock_distance_km_24h": "Max aftershock distance (km)",
}
CLS_TARGETS = list(TARGET_LABEL)
REG_TARGETS = list(REG_LABEL)


def fmt(x, p=4):
    return f"{x:.{p}f}" if isinstance(x, (int, float)) else "—"


def cls_table(rp, badge_label):
    rows = []
    for t in CLS_TARGETS:
        node = rp["classification"][t]
        pick = node["pick"]
        cells = [
            f'<td class="target">{TARGET_LABEL[t]}'
            f'<span class="sub">prevalence {node["prevalence"]*100:.1f}% · n={node["count"]:,}</span></td>'
        ]
        for fam in FAMILIES:
            m = node["families"][fam]
            best = fam == pick
            note = f'<span class="badge ok">{badge_label}</span>' if best else ""
            cells.append(
                f'<td class="{"win" if best else ""}"><b>{fmt(m["brier"])}</b>'
                f'<span class="sub">ECE {fmt(m.get("ece"),3)} · AUC {fmt(m.get("roc_auc"),3)} · AP {fmt(m.get("average_precision"),3)}</span>'
                f"{note}</td>"
            )
        cells.append(f'<td class="pick">{LABEL[pick]}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def reg_table(rp, badge_label):
    rows = []
    for t in REG_TARGETS:
        node = rp["regression"][t]
        pick = node["pick"]
        cells = [f'<td class="target">{REG_LABEL[t]}</td>']
        for fam in FAMILIES:
            m = node["families"].get(fam, {})
            best = fam == pick
            note = f'<span class="badge ok">{badge_label}</span>' if best else ""
            cells.append(
                f'<td class="{"win" if best else ""}"><b>R² {fmt(m.get("r2"),3)}</b>'
                f'<span class="sub">MAE {fmt(m.get("mae"),3)} · RMSE {fmt(m.get("rmse"),3)}</span>{note}</td>'
            )
        cells.append(f'<td class="pick">{LABEL[pick]}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def cls_series(rp, key):
    return {fam: [rp["classification"][t]["families"][fam][key] for t in CLS_TARGETS] for fam in FAMILIES}


def reg_series(rp):
    return {fam: [rp["regression"][t]["families"].get(fam, {}).get("r2") for t in REG_TARGETS] for fam in FAMILIES}


def datasets_js(per_fam_series):
    out = []
    for fam in FAMILIES:
        out.append(
            "{label:%r,data:%s,backgroundColor:%r,borderColor:%r,borderWidth:2,fill:false}"
            % (
                LABEL[fam],
                json.dumps([None if v is None else round(v, 4) for v in per_fam_series[fam]]),
                COLOR[fam] + "cc",
                COLOR[fam],
            )
        )
    return "[" + ",".join(out) + "]"


def build(source_path, out_path, eval_label, pick_col_label, badge_label, deployment):
    rp = json.loads(Path(source_path).read_text())
    n = rp.get("evaluation_rows", rp["classification"]["aftershock_24h"]["count"])

    cd_labels = [TARGET_LABEL[t] for t in CLS_TARGETS]
    reg_chart_labels = ["Max magnitude", "Max distance (km)"]
    mapping_rows = "".join(
        f"<tr><td>{TARGET_LABEL[t]}</td><td class='pick'>{LABEL[rp['classification'][t]['pick']]}</td></tr>"
        for t in CLS_TARGETS
    ) + "".join(
        f"<tr><td>{REG_LABEL[t]} (reg.)</td><td class='pick'>{LABEL[rp['regression'][t]['pick']]}</td></tr>"
        for t in REG_TARGETS
    )

    if deployment:
        note = ('Every family is isotonic-calibrated and scored on ' + eval_label +
                ' the models were never trained on, at deployment prevalence — so these are genuine '
                'out-of-sample numbers. The deployed model for each target is the strongest family on this set.')
        green_bullet = "Green cell = best family for that target, which is the one deployed (right column)."
        mapping_title = "Deployed model per target (live SEIS mapping)"
        mapping_lead = 'What <code>HYBRID_MODEL_MAPPING</code> in <code>src/seis/predict.py</code> serves.'
    else:
        note = ('Each family is isotonic-calibrated and scored on ' + eval_label +
                '. The highlighted family per target is the one that performed best here. This is a '
                'descriptive view of test-set performance — it is NOT the deployed selection.')
        green_bullet = "Green cell = best-performing family for that target on this set (right column)."
        mapping_title = "Best-performing model per target (" + eval_label + ")"
        mapping_lead = "Strongest family per target on this set — descriptive, not the deployed mapping."

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEIS Aftershock Models — Evaluation Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{{--bg:#0f172a;--card:#fff;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:#f1f5f9;line-height:1.5}}
header{{background:linear-gradient(135deg,#1e3a8a,#0f172a);color:#fff;padding:36px 40px}}
header h1{{margin:0 0 6px;font-size:26px}}
header p{{margin:0;color:#cbd5e1;font-size:14px}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 20px 60px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}}
h2{{font-size:19px;margin:4px 0 4px;border-left:4px solid #2563eb;padding-left:10px}}
.lead{{color:var(--muted);font-size:14px;margin:2px 0 16px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:#f8fafc;font-weight:600;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.03em}}
td b{{font-size:14px}}
.sub{{display:block;color:var(--muted);font-size:11px;margin-top:2px}}
td.target{{font-weight:600;min-width:150px}}
td.win{{background:#ecfdf5}}
td.win b{{color:#15803d}}
td.pick{{font-weight:600;color:#1d4ed8;white-space:nowrap}}
td.na{{color:#94a3b8;font-style:italic}}
.badge{{display:inline-block;font-size:10px;padding:2px 7px;border-radius:10px;font-weight:600;margin-top:3px}}
.badge.ok{{background:#dcfce7;color:#15803d}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
.chart-box{{position:relative;height:300px}}
.note{{font-size:12.5px;color:var(--muted);background:#f8fafc;border-left:3px solid #cbd5e1;padding:10px 12px;border-radius:0 6px 6px 0;margin-top:12px}}
.legend{{font-size:12px;color:var(--muted);margin-top:8px}}
code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}}
footer{{text-align:center;color:#94a3b8;font-size:12px;padding:20px}}
</style></head>
<body>
<header>
<h1>SEIS Aftershock Models — Evaluation Report</h1>
<p>{len(FAMILIES)} model families ({" · ".join(LABEL[f] for f in FAMILIES)}) across 9 prediction targets · evaluated on {eval_label} ({n:,} events) at real-world prevalence</p>
</header>
<div class="wrap">

<div class="card">
<h2>How to read this report</h2>
<p class="lead">Each target is predicted by all {len(FAMILIES)} model families.</p>
<ul style="font-size:13.5px;margin:0;padding-left:20px">
<li><b>Calibrated Brier</b> — accuracy of the predicted probability (lower is better). The primary score, because the product outputs probabilities.</li>
<li><b>ECE</b> — calibration error: how closely "70% chance" matches reality (lower is better).</li>
<li><b>ROC-AUC / AP</b> — ranking quality: can the model tell risky events from safe ones (higher is better, max 1.0).</li>
<li><b>R²</b> (regression) — share of variance explained (higher is better).</li>
<li>{green_bullet}</li>
</ul>
<div class="note">{note}</div>
</div>

<div class="card">
<h2>Classification — calibrated metrics by target &amp; model</h2>
<p class="lead">Bold = calibrated Brier (primary). Smaller line = ECE · AUC · AP. Green = best.</p>
<table>
<thead><tr><th>Target</th>{FAMILY_TH}<th>{pick_col_label}</th></tr></thead>
<tbody>
{cls_table(rp, badge_label)}
</tbody></table>
</div>

<div class="grid">
<div class="card"><h2>Calibrated Brier (lower better)</h2><div class="chart-box"><canvas id="brierChart"></canvas></div></div>
<div class="card"><h2>ROC-AUC (higher better)</h2><div class="chart-box"><canvas id="aucChart"></canvas></div></div>
</div>

<div class="grid">
<div class="card"><h2>Average Precision (higher better)</h2><div class="chart-box"><canvas id="apChart"></canvas></div></div>
<div class="card"><h2>Regression R² (higher better)</h2><div class="chart-box"><canvas id="regChart"></canvas></div>
<div class="legend">All {len(FAMILIES)} families train both regressors.</div></div>
</div>

<div class="card">
<h2>Regression — magnitude &amp; distance</h2>
<p class="lead">Predicting the largest aftershock’s size and how far it reaches.</p>
<table>
<thead><tr><th>Target</th>{FAMILY_TH}<th>{pick_col_label}</th></tr></thead>
<tbody>
{reg_table(rp, badge_label)}
</tbody></table>
</div>

<div class="card">
<h2>{mapping_title}</h2>
<p class="lead">{mapping_lead}</p>
<table style="max-width:520px"><thead><tr><th>Target</th><th>Model</th></tr></thead><tbody>
{mapping_rows}
</tbody></table>
</div>

</div>
<footer>Generated from {Path(source_path).name}</footer>
__SCRIPT__
</body></html>"""

    script = """<script>
Chart.defaults.font.family="-apple-system,Segoe UI,Roboto,sans-serif";
Chart.defaults.font.size=11;
const LABELS=__LABELS__;
function bar(id,datasets,opts){new Chart(document.getElementById(id),{type:'bar',data:{labels:LABELS,datasets:datasets},options:Object.assign({responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{ticks:{maxRotation:55,minRotation:35}}}},opts||{})});}
bar('brierChart',__BRIER__,{scales:{y:{beginAtZero:true,title:{display:true,text:'Calibrated Brier'}}}});
bar('aucChart',__AUC__,{scales:{y:{min:0.9,max:1.0,title:{display:true,text:'ROC-AUC'}}}});
bar('apChart',__AP__,{scales:{y:{min:0.6,max:1.0,title:{display:true,text:'Average Precision'}}}});
new Chart(document.getElementById('regChart'),{type:'bar',data:{labels:__REGLABELS__,datasets:__REGR2__},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{y:{beginAtZero:true,max:1.0,title:{display:true,text:'R2'}}}}});
</script>"""
    script = (
        script.replace("__LABELS__", json.dumps(cd_labels))
        .replace("__BRIER__", datasets_js(cls_series(rp, "brier")))
        .replace("__AUC__", datasets_js(cls_series(rp, "roc_auc")))
        .replace("__AP__", datasets_js(cls_series(rp, "average_precision")))
        .replace("__REGLABELS__", json.dumps(reg_chart_labels))
        .replace("__REGR2__", datasets_js(reg_series(rp)))
    )
    html = html.replace("__SCRIPT__", script)
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="src/outputs/seis/calibration/repick_report.json")
    p.add_argument("--output", default="src/docs/seis_evaluation_report.html")
    p.add_argument("--eval-label", default="a held-out set")
    p.add_argument("--pick-label", default="Deployed pick")
    p.add_argument("--badge-label", default="deployed")
    p.add_argument("--test", action="store_true",
                   help="Descriptive test-set report (not the deployment mapping).")
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    build(a.source, a.output, a.eval_label, a.pick_label, a.badge_label, deployment=not a.test)
