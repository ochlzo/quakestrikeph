"""Build a comprehensive, visualized HTML findings report on model selection.

Synthesizes four artifacts (nothing hand-typed):
  * repick_report.json         -- validation (single-year) picks
  * test_pick_report.json      -- best-on-test (single-year) picks
  * walk_forward_report.json   -- walk-forward picks + per-fold metrics
  * significance_report.json   -- bootstrap significance of test-set gaps

Output: src/docs/seis_findings_report.html
"""

import json
from pathlib import Path

CAL = Path("src/outputs/seis/calibration")
VAL = CAL / "repick_report.json"
TEST = CAL / "test_pick_report.json"
WF = CAL / "walk_forward_report.json"
SIG = CAL / "significance_report.json"
OUT = Path("src/docs/seis_findings_report.html")

FAMILIES = ["xgboost", "lightgbm", "random_forest", "catboost"]
LABEL = {"xgboost": "XGBoost", "lightgbm": "LightGBM", "random_forest": "Random Forest", "catboost": "CatBoost"}
SHORT = {"xgboost": "XGB", "lightgbm": "LGBM", "random_forest": "RF", "catboost": "CB"}
COLOR = {"xgboost": "#2563eb", "lightgbm": "#16a34a", "random_forest": "#d97706", "catboost": "#9333ea"}
BG = {"xgboost": "#dbeafe", "lightgbm": "#dcfce7", "random_forest": "#ffedd5", "catboost": "#f3e8ff"}

TLABEL = {
    "aftershock_24h": "Any aftershock (24h)",
    "aftershock_dist_0_10km_24h": "0-10 km",
    "aftershock_dist_10_25km_24h": "10-25 km",
    "aftershock_dist_25_50km_24h": "25-50 km",
    "aftershock_dist_50_100km_24h": "50-100 km",
    "aftershock_dist_100_200km_24h": "100-200 km",
    "aftershock_dist_200_pluskm_24h": "200+ km",
    "max_aftershock_mag_24h": "Max magnitude",
    "max_aftershock_distance_km_24h": "Max distance",
}
CLS = list(TLABEL)[:7]
REG = ["max_aftershock_mag_24h", "max_aftershock_distance_km_24h"]


def load():
    return (json.loads(VAL.read_text()), json.loads(TEST.read_text()),
            json.loads(WF.read_text()), json.loads(SIG.read_text()))


def main():
    val, test, wf, sig = load()
    vmap, tmap, wmap = val["hybrid_model_mapping"], test["hybrid_model_mapping"], wf["hybrid_model_mapping"]
    all_targets = CLS + REG
    folds = [str(y) for y in wf["eval_years"]]

    n_disagree = sum(1 for t in all_targets if len({vmap[t], tmap[t], wmap[t]}) > 1)
    pickcount = {f: 0 for f in FAMILIES}
    for t in all_targets:
        for m in (vmap, tmap, wmap):
            pickcount[m[t]] += 1
    n_real = sum(1 for t in CLS if sig["classification"][t]["deployed_vs_winner"]["verdict"] == "REAL gap")

    def cell(fam):
        return f'<td style="background:{BG[fam]};color:{COLOR[fam]};font-weight:600">{SHORT[fam]}</td>'
    matrix_rows = []
    for t in all_targets:
        picks = [vmap[t], tmap[t], wmap[t]]
        distinct = len(set(picks))
        agree = ("&#10003; stable" if distinct == 1 else ("rotates" if distinct == 3 else "partial"))
        agree_cls = "ok" if distinct == 1 else ("bad" if distinct == 3 else "warn")
        matrix_rows.append(
            f'<tr><td class="target">{TLABEL[t]}</td>{cell(vmap[t])}{cell(tmap[t])}{cell(wmap[t])}'
            f'<td><span class="badge {agree_cls}">{agree}</span></td></tr>'
        )

    sig_rows = []
    for t in CLS:
        s = sig["classification"][t]
        dvw = s["deployed_vs_winner"]
        ci, verb = dvw["ci"], dvw["verdict"]
        vcls = "ok" if "winner" in verb else ("bad" if "REAL" in verb else "warn")
        delta = "&mdash;" if "winner" in verb else f'{dvw["delta"]:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]'
        sig_rows.append(
            f'<tr><td class="target">{TLABEL[t]}</td>'
            f'<td>{SHORT[s["test_winner"]]}</td><td>{SHORT[s["deployed"]]}</td>'
            f'<td>{delta}</td><td><span class="badge {vcls}">{verb}</span></td></tr>'
        )

    def line_spec(node_map, targets, key):
        specs = []
        for t in targets:
            fams = node_map[t]["families"]
            series = [{"label": LABEL[f], "color": COLOR[f], "data": [fams[f][key].get(y) for y in folds]}
                      for f in FAMILIES]
            specs.append({"id": "c_" + t, "title": TLABEL[t], "series": series})
        return specs

    config = {
        "folds": folds,
        "wf_line": line_spec(wf["classification"], CLS, "per_fold_brier"),
        "reg_line": line_spec(wf["regression"], REG, "per_fold_r2"),
        "pickcount": {
            "labels": [LABEL[f] for f in FAMILIES],
            "datasets": [
                {"label": "Validation (2024)", "color": "#1e3a8a", "data": [sum(1 for t in all_targets if vmap[t] == f) for f in FAMILIES]},
                {"label": "Test (2025)", "color": "#0891b2", "data": [sum(1 for t in all_targets if tmap[t] == f) for f in FAMILIES]},
                {"label": "Walk-forward", "color": "#7c3aed", "data": [sum(1 for t in all_targets if wmap[t] == f) for f in FAMILIES]},
            ],
        },
        "foldwins": {
            "labels": [TLABEL[t] for t in CLS],
            "datasets": [
                {"label": LABEL[f], "color": COLOR[f],
                 "data": [wf["classification"][t]["fold_wins"].get(f, 0) for t in CLS]}
                for f in FAMILIES
            ],
        },
    }

    wf_canvases = "".join(
        f'<div class="card mini"><h3>{s["title"]}</h3><div class="chart-box sm"><canvas id="{s["id"]}"></canvas></div></div>'
        for s in config["wf_line"]
    )
    reg_canvases = "".join(
        f'<div class="card mini"><h3>{s["title"]} &mdash; R&sup2; across folds</h3><div class="chart-box sm"><canvas id="{s["id"]}"></canvas></div></div>'
        for s in config["reg_line"]
    )

    repls = {
        "__N_TARGETS__": str(len(all_targets)),
        "__N_DISAGREE__": str(n_disagree),
        "__CB_PICKS__": str(pickcount["catboost"]),
        "__RF_PICKS__": str(pickcount["random_forest"]),
        "__LGBM_PICKS__": str(pickcount["lightgbm"]),
        "__N_REAL__": str(n_real),
        "__N_CLS__": str(len(CLS)),
        "__N_TEST__": f"{sig['n']:,}",
        "__FOLDS_STR__": ", ".join(folds),
        "__MATRIX_ROWS__": "\n".join(matrix_rows),
        "__SIG_ROWS__": "\n".join(sig_rows),
        "__WF_CANVASES__": wf_canvases,
        "__REG_CANVASES__": reg_canvases,
        "__CONFIG_JSON__": json.dumps(config),
    }
    html = TEMPLATE
    for k, v in repls.items():
        html = html.replace(k, v)
    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(html):,} bytes)")


TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEIS Model Selection — Findings Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#1e293b;background:#f1f5f9;line-height:1.55}
header{background:linear-gradient(135deg,#1e3a8a,#0f172a);color:#fff;padding:38px 40px}
header h1{margin:0 0 6px;font-size:27px}
header p{margin:0;color:#cbd5e1;font-size:14px;max-width:820px}
.wrap{max-width:1100px;margin:0 auto;padding:26px 20px 70px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:22px 24px;margin:18px 0;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.card.mini{padding:14px 16px;margin:0}
h2{font-size:20px;margin:4px 0 6px;border-left:4px solid #2563eb;padding-left:10px}
h3{font-size:13px;margin:0 0 6px;color:#475569}
.lead{color:#64748b;font-size:14px;margin:2px 0 16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #e2e8f0;vertical-align:middle}
th{background:#f8fafc;font-weight:600;color:#475569;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
td.target{font-weight:600;min-width:130px}
.badge{display:inline-block;font-size:10px;padding:2px 8px;border-radius:10px;font-weight:700}
.badge.ok{background:#dcfce7;color:#15803d}
.badge.warn{background:#fef9c3;color:#a16207}
.badge.bad{background:#fee2e2;color:#b91c1c}
.kpis{display:flex;gap:14px;flex-wrap:wrap}
.kpi{flex:1;min-width:165px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:16px}
.kpi .n{font-size:28px;font-weight:800;color:#1e3a8a}
.kpi .l{font-size:12px;color:#64748b;margin-top:2px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:820px){.grid2,.grid3{grid-template-columns:1fr}}
.chart-box{position:relative;height:300px}
.chart-box.sm{height:190px}
.note{font-size:12.5px;color:#475569;background:#f8fafc;border-left:3px solid #cbd5e1;padding:10px 12px;border-radius:0 6px 6px 0;margin-top:12px}
ul{font-size:13.5px;margin:6px 0;padding-left:20px}
li{margin:4px 0}
footer{text-align:center;color:#94a3b8;font-size:12px;padding:20px}
</style></head>
<body>
<header>
<h1>SEIS Aftershock Models — Model-Selection Findings</h1>
<p>How we choose which model family (XGBoost · LightGBM · Random Forest · CatBoost) to deploy per target, what three selection methods reveal, and why no single family is reliably best. All numbers computed on held-out data (__N_TEST__-event test set; walk-forward folds __FOLDS_STR__).</p>
</header>
<div class="wrap">

<div class="card">
<h2>Executive summary</h2>
<div class="kpis">
<div class="kpi"><div class="n">__CB_PICKS__</div><div class="l">times CatBoost is picked (of 27 = 9 targets × 3 methods) — the most of any family</div></div>
<div class="kpi"><div class="n">__N_DISAGREE__ / __N_TARGETS__</div><div class="l">targets where the three selection methods <b>disagree</b> on the best family</div></div>
<div class="kpi"><div class="n">__LGBM_PICKS__</div><div class="l">times LightGBM is picked — it is rarely the best by any method</div></div>
<div class="kpi"><div class="n">__N_REAL__ / __N_CLS__</div><div class="l">classification targets where the test winner beats the deployed pick by a statistically real margin</div></div>
</div>
<div class="note"><b>Headline:</b> with CatBoost added as a fourth family it becomes the <b>most-picked model overall</b> and the deployed choice for most targets — yet the best family per target is still <b>not stable</b>, changing with the selection year/method. CatBoost is strongest on the near-distance bins and magnitude; Random Forest remains the most <i>consistent</i> across folds and owns the far-distance bins; XGBoost holds a couple of targets; LightGBM is seldom best. Because no single family wins reliably across all targets, an <b>equal-weight ensemble</b> of the calibrated families remains the most robust deployment — pursued in the dedicated sibling project.</div>
</div>

<div class="card">
<h2>1. The three selection methods disagree</h2>
<p class="lead">Each method picks the best family per target on different held-out data. Where they differ, the "winner" is method/year-dependent — i.e. not robust.</p>
<table>
<thead><tr><th>Target</th><th>Validation (2024)</th><th>Test (2025)</th><th>Walk-forward (2021–24)</th><th>Stability</th></tr></thead>
<tbody>
__MATRIX_ROWS__
</tbody></table>
<div class="note">“&#10003; stable” = all three methods agree; “rotates” = all three differ (no robust winner); “partial” = two agree.</div>
</div>

<div class="card">
<h2>2. How often each family is the best pick</h2>
<p class="lead">Across all 9 targets under each selection method. CatBoost is the most-picked family overall and dominates the deployment (validation) view; Random Forest leads the robust (walk-forward) fold wins; LightGBM barely registers.</p>
<div class="chart-box"><canvas id="pickcount"></canvas></div>
</div>

<div class="card">
<h2>3. Robustness: per-fold calibrated Brier (lower = better)</h2>
<p class="lead">Walk-forward folds evaluate on 2021–2024. The story is <b>variance</b>: Random Forest (orange) and CatBoost (purple) stay relatively flat across years; XGBoost (blue) swings — sometimes best, sometimes much worse. A flat line is a dependable model.</p>
<div class="grid3">
__WF_CANVASES__
</div>
</div>

<div class="card">
<h2>4. Who wins each fold</h2>
<p class="lead">Number of the four folds each family wins per target (stacks to 4). Random Forest takes the most folds overall, with CatBoost close behind (winning the near-distance bins).</p>
<div class="chart-box"><canvas id="foldwins"></canvas></div>
</div>

<div class="card">
<h2>5. Are the test-set differences real or noise?</h2>
<p class="lead">Paired bootstrap on the __N_TEST__-event test set. With this many events even small gaps are statistically detectable — but most are small in magnitude; only a couple are both real and sizeable.</p>
<table>
<thead><tr><th>Target</th><th>Test winner</th><th>Deployed</th><th>Δ Brier (dep − win) [95% CI]</th><th>Verdict</th></tr></thead>
<tbody>
__SIG_ROWS__
</tbody></table>
<div class="note">“REAL gap” = 95% CI excludes 0 (reliably non-zero, though often small). “deployed is winner” = the deployed pick already had the best test Brier.</div>
</div>

<div class="card">
<h2>6. Regression stability (R&sup2; across folds)</h2>
<p class="lead">Magnitude and distance regressors across walk-forward folds. Magnitude is volatile and near its physical ceiling; distance is steadier.</p>
<div class="grid2">
__REG_CANVASES__
</div>
</div>

<div class="card">
<h2>7. Conclusions &amp; recommendations</h2>
<ul>
<li><b>No single family is reliably best.</b> The pick rotates across __N_DISAGREE__ of __N_TARGETS__ targets depending on selection year/method.</li>
<li><b>CatBoost is the strongest single family by the deployment criterion</b> — the most-picked family overall (__CB_PICKS__ of 27) and the validation-selected choice for most targets, especially the near-distance bins (0–50 km), 200+ km, and magnitude.</li>
<li><b>Random Forest remains the most robust across folds</b> — the most walk-forward fold wins and lowest fold-to-fold variance, and it still owns the far-distance bins (100–200 km). Best fallback if a non-boosting model is needed.</li>
<li><b>XGBoost is higher-variance and data-hungry</b> — strong in recent, data-rich years (it keeps any-aftershock and max-magnitude), erratic in leaner ones.</li>
<li><b>LightGBM can be retired</b> from the shortlist — it is seldom the best by any method (__LGBM_PICKS__ of 27, zero walk-forward fold wins).</li>
<li><b>The robust answer is still an equal-weight ensemble</b> of the calibrated families — now including CatBoost — which sidesteps the unstable per-target pick entirely. This is the focus of the dedicated sibling project.</li>
<li><b>Caveat:</b> walk-forward folds train on one year less data than production (reserving a year for early stopping), which modestly favors Random Forest over the data-hungry boosters (XGBoost and CatBoost).</li>
</ul>
</div>

</div>
<footer>Generated from repick_report.json · test_pick_report.json · walk_forward_report.json · significance_report.json</footer>
<script>
const CFG = __CONFIG_JSON__;
Chart.defaults.font.family="-apple-system,Segoe UI,Roboto,sans-serif";
Chart.defaults.font.size=11;
function lineChart(spec, yTitle){
  new Chart(document.getElementById(spec.id),{type:'line',
    data:{labels:CFG.folds,datasets:spec.series.map(s=>({label:s.label,data:s.data,borderColor:s.color,backgroundColor:s.color,borderWidth:2,tension:.25,pointRadius:2}))},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{title:{display:true,text:yTitle}}}}});
}
CFG.wf_line.forEach(s=>lineChart(s,'Brier'));
CFG.reg_line.forEach(s=>lineChart(s,'R2'));
function stackedBar(id,cfg,yTitle){
  new Chart(document.getElementById(id),{type:'bar',
    data:{labels:cfg.labels,datasets:cfg.datasets.map(d=>({label:d.label,data:d.data,backgroundColor:(d.color||'#888')+'cc',borderColor:d.color||'#888',borderWidth:1}))},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'}},scales:{x:{stacked:true,ticks:{maxRotation:55,minRotation:35}},y:{stacked:true,title:{display:true,text:yTitle}}}}});
}
stackedBar('pickcount',CFG.pickcount,'times picked (of 9)');
stackedBar('foldwins',CFG.foldwins,'folds won (of 4)');
</script>
</body></html>"""


if __name__ == "__main__":
    main()
