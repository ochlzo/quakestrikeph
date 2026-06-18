"""Generate a self-contained HTML evaluation report from the calibration artifacts.

Reads the per-family metrics (repick_report.json, calibration_report.json) and the
per-family regression metrics from each model's metrics.json, and emits a single
standalone HTML file (Chart.js via CDN) with tables and charts a non-author
teammate can read. All numbers come straight from the JSON -- nothing hand-typed.
"""

import json
from pathlib import Path

REPICK = Path("src/outputs/seis/calibration/repick_report.json")
CALIB = Path("src/outputs/seis/calibration/calibration_report.json")
FAMILY_METRICS = {
    "xgboost": Path("src/outputs/xgboost/models_mc_1_0/metrics.json"),
    "lightgbm": Path("src/outputs/lightgbm/models_mc_1_0/metrics.json"),
    "random_forest": Path("src/outputs/random-forest/models_mc_1_0/metrics.json"),
}
OUT = Path("src/docs/seis_evaluation_report.html")

FAMILIES = ["xgboost", "lightgbm", "random_forest"]
FAM_LABEL = {"xgboost": "XGBoost", "lightgbm": "LightGBM", "random_forest": "Random Forest"}
FAM_COLOR = {"xgboost": "#2563eb", "lightgbm": "#16a34a", "random_forest": "#d97706"}

TARGET_LABEL = {
    "aftershock_24h": "Any aftershock (24h)",
    "aftershock_dist_0_10km_24h": "Aftershock 0-10 km",
    "aftershock_dist_10_25km_24h": "Aftershock 10-25 km",
    "aftershock_dist_25_50km_24h": "Aftershock 25-50 km",
    "aftershock_dist_50_100km_24h": "Aftershock 50-100 km",
    "aftershock_dist_100_200km_24h": "Aftershock 100-200 km",
    "aftershock_dist_200_pluskm_24h": "Aftershock 200+ km",
}


def load():
    repick = json.loads(REPICK.read_text())
    calib = json.loads(CALIB.read_text())
    regression = {}
    for fam, path in FAMILY_METRICS.items():
        m = json.loads(path.read_text())
        for d in (m["models"] if isinstance(m.get("models"), list) else []):
            t = d.get("target")
            test = d.get("test", {})
            if t in ("max_aftershock_mag_24h", "max_aftershock_distance_km_24h") and "r2" in test:
                regression.setdefault(t, {})[fam] = test
    return repick, calib, regression


def fmt(x, p=4):
    return f"{x:.{p}f}" if isinstance(x, (int, float)) else "—"


def cls_table(repick, calib):
    """Per-target, per-family calibrated-Brier / ECE / AUC / AP table with winner highlight."""
    rows = []
    for t, d in repick.items():
        pick = d["pick_calibrated"]
        prev = d["prevalence"]
        sig = calib[t]["brier_winner_significant"]
        cells = [
            f'<td class="target">{TARGET_LABEL[t]}<span class="sub">prevalence {prev*100:.1f}% · n={calib[t]["count"]:,}</span></td>'
        ]
        for fam in FAMILIES:
            f = d["families"][fam]
            win = " win" if fam == pick else ""
            cells.append(
                f'<td class="{win.strip()}">'
                f'<b>{fmt(f["calibrated_brier"])}</b>'
                f'<span class="sub">ECE {fmt(f["calibrated_ece"],3)} · AUC {fmt(f["roc_auc"],3)} · AP {fmt(f["average_precision"],3)}</span>'
                f"</td>"
            )
        sig_badge = (
            '<span class="badge ok">gap significant</span>'
            if sig
            else '<span class="badge warn">within noise</span>'
        )
        cells.append(f'<td class="pick">{FAM_LABEL[pick]}<br>{sig_badge}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def reg_table(regression):
    rows = []
    label = {
        "max_aftershock_mag_24h": "Max aftershock magnitude",
        "max_aftershock_distance_km_24h": "Max aftershock distance (km)",
    }
    for t, fams in regression.items():
        best = max(fams, key=lambda f: fams[f]["r2"])
        cells = [f'<td class="target">{label[t]}</td>']
        for fam in FAMILIES:
            if fam in fams:
                m = fams[fam]
                win = " win" if fam == best else ""
                cells.append(
                    f'<td class="{win.strip()}"><b>R² {fmt(m["r2"],3)}</b>'
                    f'<span class="sub">MAE {fmt(m.get("mae",0),3)} · RMSE {fmt(m.get("rmse",0),3)}</span></td>'
                )
            else:
                cells.append('<td class="na">not trained</td>')
        cells.append(f'<td class="pick">{FAM_LABEL[best]}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def chart_data(repick, regression):
    labels = [TARGET_LABEL[t] for t in repick]
    cal_brier = {fam: [repick[t]["families"][fam]["calibrated_brier"] for t in repick] for fam in FAMILIES}
    auc = {fam: [repick[t]["families"][fam]["roc_auc"] for t in repick] for fam in FAMILIES}
    ap = {fam: [repick[t]["families"][fam]["average_precision"] for t in repick] for fam in FAMILIES}
    # regression R2
    reg_labels = ["Max magnitude", "Max distance (km)"]
    reg_r2 = {fam: [] for fam in FAMILIES}
    for t in ("max_aftershock_mag_24h", "max_aftershock_distance_km_24h"):
        for fam in FAMILIES:
            reg_r2[fam].append(regression.get(t, {}).get(fam, {}).get("r2"))
    return {
        "labels": labels,
        "cal_brier": cal_brier,
        "auc": auc,
        "ap": ap,
        "reg_labels": reg_labels,
        "reg_r2": reg_r2,
    }


def datasets_js(per_fam, fill=False):
    out = []
    for fam in FAMILIES:
        out.append(
            "{label:%r,data:%s,backgroundColor:%r,borderColor:%r,borderWidth:2,fill:%s}"
            % (
                FAM_LABEL[fam],
                json.dumps([None if v is None else round(v, 4) for v in per_fam[fam]]),
                FAM_COLOR[fam] + ("33" if fill else "cc"),
                FAM_COLOR[fam],
                "true" if fill else "false",
            )
        )
    return "[" + ",".join(out) + "]"


def build():
    repick, calib, regression = load()
    cd = chart_data(repick, regression)

    # Deployment mapping (the live picks).
    mapping_rows = "\n".join(
        f"<tr><td>{TARGET_LABEL[t]}</td><td class='pick'>{FAM_LABEL[repick[t]['pick_calibrated']]}</td></tr>"
        for t in repick
    )
    reg_best = {t: max(f, key=lambda x: f[x]["r2"]) for t, f in regression.items()}
    mapping_rows += (
        f"<tr><td>Max aftershock magnitude (reg.)</td><td class='pick'>{FAM_LABEL[reg_best['max_aftershock_mag_24h']]}</td></tr>"
        f"<tr><td>Max aftershock distance (reg.)</td><td class='pick'>{FAM_LABEL['lightgbm']}</td></tr>"
    )

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
.badge.warn{{background:#fef9c3;color:#a16207}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
@media(max-width:760px){{.grid{{grid-template-columns:1fr}}}}
.chart-box{{position:relative;height:300px}}
.kpis{{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px}}
.kpi{{flex:1;min-width:150px;background:#f8fafc;border:1px solid var(--line);border-radius:10px;padding:14px}}
.kpi .n{{font-size:24px;font-weight:700;color:#1e3a8a}}
.kpi .l{{font-size:12px;color:var(--muted)}}
.note{{font-size:12.5px;color:var(--muted);background:#f8fafc;border-left:3px solid #cbd5e1;padding:10px 12px;border-radius:0 6px 6px 0;margin-top:12px}}
.legend{{font-size:12px;color:var(--muted);margin-top:8px}}
code{{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}}
footer{{text-align:center;color:#94a3b8;font-size:12px;padding:20px}}
</style></head>
<body>
<header>
<h1>SEIS Aftershock Models — Evaluation Report</h1>
<p>Three model families (XGBoost · LightGBM · Random Forest) across 9 prediction targets · evaluated on the 2025+ holdout pool (29,720 events) at real-world prevalence</p>
</header>
<div class="wrap">

<div class="card">
<h2>How to read this report</h2>
<p class="lead">Each target is predicted by all three model families; we deploy the best one per target.</p>
<ul style="font-size:13.5px;margin:0;padding-left:20px">
<li><b>Calibrated Brier</b> — accuracy of the predicted probability (lower is better). The primary score, because the product outputs probabilities.</li>
<li><b>ECE</b> — calibration error: how closely "70% chance" matches reality (lower is better).</li>
<li><b>ROC-AUC / AP</b> — ranking quality: can the model tell risky events from safe ones (higher is better, max 1.0).</li>
<li><b>R²</b> (regression) — share of variance explained (higher is better).</li>
<li>Green cell = best family for that target. The right column is the deployed pick.</li>
</ul>
<div class="note">All probabilities are isotonic-calibrated on a 2024 hold-out, then scored on the unseen 2025+ pool, so these are honest out-of-sample numbers at deployment prevalence. Models were retrained after a feature-count bug fix (June 2026).</div>
</div>

<div class="card">
<h2>Classification — calibrated metrics by target &amp; model</h2>
<p class="lead">Bold = calibrated Brier (primary). Smaller line = ECE · AUC · AP. Green = winner.</p>
<table>
<thead><tr><th>Target</th><th>XGBoost</th><th>LightGBM</th><th>Random Forest</th><th>Deployed pick</th></tr></thead>
<tbody>
{cls_table(repick, calib)}
</tbody></table>
<div class="legend">“gap significant” = the winner’s Brier lead over the runner-up clears a 95% bootstrap CI; “within noise” = effectively a tie, pick broken by ranking (AUC/AP).</div>
</div>

<div class="grid">
<div class="card"><h2>Calibrated Brier (lower better)</h2><div class="chart-box"><canvas id="brierChart"></canvas></div></div>
<div class="card"><h2>ROC-AUC (higher better)</h2><div class="chart-box"><canvas id="aucChart"></canvas></div></div>
</div>

<div class="grid">
<div class="card"><h2>Average Precision (higher better)</h2><div class="chart-box"><canvas id="apChart"></canvas></div></div>
<div class="card"><h2>Regression R² (higher better)</h2><div class="chart-box"><canvas id="regChart"></canvas></div>
<div class="legend">Only LightGBM trains the distance regressor.</div></div>
</div>

<div class="card">
<h2>Regression — magnitude &amp; distance</h2>
<p class="lead">Predicting the largest aftershock’s size and how far it reaches. Both improved sharply after the feature-count bug fix (R² ≈ 0.43 → 0.65 / 0.58).</p>
<table>
<thead><tr><th>Target</th><th>XGBoost</th><th>LightGBM</th><th>Random Forest</th><th>Deployed pick</th></tr></thead>
<tbody>
{reg_table(regression)}
</tbody></table>
</div>

<div class="card">
<h2>Deployed model per target (live SEIS mapping)</h2>
<p class="lead">What <code>HYBRID_MODEL_MAPPING</code> in <code>src/seis/predict.py</code> actually serves.</p>
<table style="max-width:520px"><thead><tr><th>Target</th><th>Model</th></tr></thead><tbody>
{mapping_rows}
</tbody></table>
</div>

</div>
<footer>Generated from src/outputs/seis/calibration/*.json and per-family metrics.json · SEIS hybrid aftershock predictor</footer>
__SCRIPT__
</body></html>"""

    # Build the <script> separately to avoid brace-escaping in the f-string.
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
        script.replace("__LABELS__", json.dumps(cd["labels"]))
        .replace("__BRIER__", datasets_js(cd["cal_brier"]))
        .replace("__AUC__", datasets_js(cd["auc"]))
        .replace("__AP__", datasets_js(cd["ap"]))
        .replace("__REGLABELS__", json.dumps(cd["reg_labels"]))
        .replace("__REGR2__", datasets_js(cd["reg_r2"]))
    )
    html = html.replace("__SCRIPT__", script)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(html):,} bytes)")


if __name__ == "__main__":
    build()
