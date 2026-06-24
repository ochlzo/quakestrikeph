"""Compare pre-improvement backtest metrics against updated metrics.

Reads pre-improvement family and ensemble metrics from a backup directory
(e.g., backup/metrics/v2_pre_improvement/) and compares them to the active
runs under src/outputs/. Computes deltas for Brier, ECE, ROC-AUC, AP, MAE,
RMSE, and R² across all targets.

Outputs a Markdown report and a JSON data file in src/outputs/model_comparison/.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Target lists
CLASSIFICATION_TARGETS = [
    "aftershock_24h",
    "aftershock_within_10km_24h",
    "aftershock_within_25km_24h",
    "aftershock_within_50km_24h",
    "aftershock_beyond_50km_24h",
]

REGRESSION_TARGETS = [
    "max_aftershock_mag_24h",
    "nearest_aftershock_distance_km_24h",
    "median_aftershock_distance_km_24h",
    "p90_aftershock_distance_km_24h",
]

METRIC_LABELS = {
    "brier": "Brier",
    "ece": "ECE",
    "roc_auc": "ROC-AUC",
    "average_precision": "AP",
    "rmse": "RMSE",
    "mae": "MAE",
    "r2": "R²",
}

# Metrics where a lower value is better
LOWER_IS_BETTER = {"brier", "ece", "rmse", "mae"}


def parse_args():
    parser = argparse.ArgumentParser(description="Compare backup metrics to updated metrics.")
    parser.add_argument(
        "--backup-tag",
        default="v2_pre_improvement",
        help="Backup folder name under backup/metrics/ (default: v2_pre_improvement)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("src/outputs/model_comparison"),
        help="Directory to write comparison report and JSON data",
    )
    return parser.parse_args()


def load_json(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}")
        return None


def format_delta(delta, metric):
    if delta is None:
        return ""
    
    # Check if delta is an improvement
    is_lower_better = metric in LOWER_IS_BETTER
    is_improvement = (delta < 0 if is_lower_better else delta > 0)
    
    # We round float deltas for display
    sign = "+" if delta > 0 else ""
    color = "green" if is_improvement else "red"
    
    if abs(delta) < 1e-6:
        return "0.0000"
    
    return f"<span style='color:{color}'>{sign}{delta:.4f}</span>"


def build_comparison_data(backup_dir, updated_dir):
    families = ["xgboost", "lightgbm", "random-forest", "catboost"]
    data = {"families": {}, "seis": {}}

    # 1. Family Comparisons
    for family in families:
        backup_path = backup_dir / family / "backtests_mc_1_0" / "backtest_metrics.json"
        updated_path = updated_dir / family / "backtests_mc_1_0" / "backtest_metrics.json"

        backup_json = load_json(backup_path)
        updated_json = load_json(updated_path)

        if not backup_json or not updated_json:
            print(f"Skipping family '{family}' due to missing file.")
            continue

        family_data = {"classification": {}, "regression": {}}
        
        # Classification metrics
        backup_cls = backup_json.get("metrics", {}).get("classification", {})
        updated_cls = updated_json.get("metrics", {}).get("classification", {})

        for target in CLASSIFICATION_TARGETS:
            b_target = backup_cls.get(target, {})
            u_target = updated_cls.get(target, {})
            family_data["classification"][target] = {}
            for metric in ["brier", "ece", "roc_auc", "average_precision"]:
                b_val = b_target.get(metric)
                u_val = u_target.get(metric)
                delta = (u_val - b_val) if (b_val is not None and u_val is not None) else None
                family_data["classification"][target][metric] = {
                    "backup": b_val,
                    "updated": u_val,
                    "delta": delta,
                }

        # Regression metrics
        backup_reg = backup_json.get("metrics", {}).get("regression", {})
        updated_reg = updated_json.get("metrics", {}).get("regression", {})

        for target in REGRESSION_TARGETS:
            b_target = backup_reg.get(target, {})
            u_target = updated_reg.get(target, {})
            family_data["regression"][target] = {}
            for metric in ["rmse", "mae", "r2"]:
                b_val = b_target.get(metric)
                u_val = u_target.get(metric)
                delta = (u_val - b_val) if (b_val is not None and u_val is not None) else None
                family_data["regression"][target][metric] = {
                    "backup": b_val,
                    "updated": u_val,
                    "delta": delta,
                }
        
        data["families"][family] = family_data

    # 2. Ensemble (SEIS) Comparisons
    backup_seis_path = backup_dir / "seis" / "backtests_mc_1_0" / "backtest_metrics.json"
    updated_seis_path = updated_dir / "seis" / "backtests_mc_1_0" / "backtest_metrics.json"

    backup_seis = load_json(backup_seis_path)
    updated_seis = load_json(updated_seis_path)

    if updated_seis:
        # Load backup family json data to reconstruct backup ensemble metrics
        backup_fam_jsons = {}
        for fam in ["xgboost", "lightgbm", "random-forest", "catboost"]:
            path = backup_dir / fam / "backtests_mc_1_0" / "backtest_metrics.json"
            f_json = load_json(path)
            if f_json:
                backup_fam_jsons[fam] = f_json

        # Get pre-improvement model selection mapping for 2025
        model_selection = {}
        if backup_seis and "2025" in backup_seis:
            model_selection = backup_seis["2025"].get("config", {}).get("model_selection", {})
        if not model_selection:
            # Fallback to the known pre-improvement mapping
            model_selection = {
                "aftershock_spatial_zone_24h": "catboost",
                "max_aftershock_mag_24h": "catboost",
                "nearest_aftershock_distance_km_24h": "lightgbm",
                "median_aftershock_distance_km_24h": "xgboost",
                "p90_aftershock_distance_km_24h": "lightgbm",
            }

        for year in sorted(updated_seis.keys()):
            u_year = updated_seis.get(year, {})
            if "metrics" not in u_year:
                continue

            year_data = {"classification": {}, "regression": {}}

            # Reconstruct or fetch backup metrics for this year
            b_cls = {}
            b_reg = {}

            if year == "2025":
                # Reconstruct backup metrics from the backup of the chosen families
                # Classification targets (all mapped to aftershock_spatial_zone_24h family)
                cls_family = model_selection.get("aftershock_spatial_zone_24h", "catboost")
                cls_fam_json = backup_fam_jsons.get(cls_family, {})
                b_cls = cls_fam_json.get("metrics", {}).get("classification", {})

                # Regression targets
                for target in REGRESSION_TARGETS:
                    reg_family = model_selection.get(target)
                    reg_fam_json = backup_fam_jsons.get(reg_family, {})
                    target_metrics = reg_fam_json.get("metrics", {}).get("regression", {}).get(target)
                    if target_metrics:
                        b_reg[target] = target_metrics

            # Classification Comparison
            u_cls = u_year["metrics"].get("classification", {})
            for target in CLASSIFICATION_TARGETS:
                b_target = b_cls.get(target, {})
                u_target = u_cls.get(target, {})
                year_data["classification"][target] = {}
                for metric in ["brier", "ece", "roc_auc", "average_precision"]:
                    b_val = b_target.get(metric)
                    u_val = u_target.get(metric)
                    delta = (u_val - b_val) if (b_val is not None and u_val is not None) else None
                    year_data["classification"][target][metric] = {
                        "backup": b_val,
                        "updated": u_val,
                        "delta": delta,
                    }

            # Regression Comparison
            u_reg = u_year["metrics"].get("regression", {})
            for target in REGRESSION_TARGETS:
                b_target = b_reg.get(target, {})
                u_target = u_reg.get(target, {})
                year_data["regression"][target] = {}
                for metric in ["rmse", "mae", "r2"]:
                    b_val = b_target.get(metric)
                    u_val = u_target.get(metric)
                    delta = (u_val - b_val) if (b_val is not None and u_val is not None) else None
                    year_data["regression"][target][metric] = {
                        "backup": b_val,
                        "updated": u_val,
                        "delta": delta,
                    }

            data["seis"][year] = year_data

    return data


def generate_markdown_report(data, backup_tag):
    lines = []
    lines.append(f"# SEIS Model Feature Engineering Improvement Report")
    lines.append(f"Comparing backup version `{backup_tag}` against active/updated models.\n")
    lines.append("> [!NOTE]")
    lines.append("> Lower is better for **Brier**, **ECE**, **RMSE**, and **MAE**.")
    lines.append("> Higher is better for **ROC-AUC**, **AP**, and **R²**.")
    lines.append("> Deltas are formatted as **<span style='color:green'>green</span>** for improvement and **<span style='color:red'>red</span>** for regression.\n")

    # 1. Ensemble section
    if data.get("seis"):
        lines.append("## Ensemble Model (SEIS) Comparison")
        for year, year_data in sorted(data["seis"].items()):
            if year == "2026":
                continue  # Skip 2026 as it has no backup comparison data
            lines.append(f"### Year: {year}")
            
            # Classification Table
            lines.append("#### Classification Performance")
            lines.append("| Target | Metric | Backup | Updated | Delta |")
            lines.append("| :--- | :--- | :---: | :---: | :---: |")
            for target in CLASSIFICATION_TARGETS:
                tgt_metrics = year_data["classification"].get(target, {})
                first_row = True
                for metric in ["brier", "ece", "roc_auc", "average_precision"]:
                    m_data = tgt_metrics.get(metric, {})
                    label = METRIC_LABELS[metric]
                    b_str = f"{m_data['backup']:.4f}" if m_data.get('backup') is not None else "N/A"
                    u_str = f"{m_data['updated']:.4f}" if m_data.get('updated') is not None else "N/A"
                    d_str = format_delta(m_data.get('delta'), metric)
                    tgt_lbl = target if first_row else ""
                    lines.append(f"| {tgt_lbl} | {label} | {b_str} | {u_str} | {d_str} |")
                    first_row = False
            lines.append("")

            # Regression Table
            lines.append("#### Regression Performance")
            lines.append("| Target | Metric | Backup | Updated | Delta |")
            lines.append("| :--- | :--- | :---: | :---: | :---: |")
            for target in REGRESSION_TARGETS:
                tgt_metrics = year_data["regression"].get(target, {})
                first_row = True
                for metric in ["rmse", "mae", "r2"]:
                    m_data = tgt_metrics.get(metric, {})
                    label = METRIC_LABELS[metric]
                    b_str = f"{m_data['backup']:.4f}" if m_data.get('backup') is not None else "N/A"
                    u_str = f"{m_data['updated']:.4f}" if m_data.get('updated') is not None else "N/A"
                    d_str = format_delta(m_data.get('delta'), metric)
                    tgt_lbl = target if first_row else ""
                    lines.append(f"| {tgt_lbl} | {label} | {b_str} | {u_str} | {d_str} |")
                    first_row = False
            lines.append("")

    # 2. Individual Family Section
    lines.append("## Individual Family Model Comparisons")
    for family, fam_data in sorted(data["families"].items()):
        lines.append(f"### Family: {family.upper()}")
        
        # Classification
        lines.append(f"#### {family.upper()} Classification Performance")
        lines.append("| Target | Metric | Backup | Updated | Delta |")
        lines.append("| :--- | :--- | :---: | :---: | :---: |")
        for target in CLASSIFICATION_TARGETS:
            tgt_metrics = fam_data["classification"].get(target, {})
            first_row = True
            for metric in ["brier", "ece", "roc_auc", "average_precision"]:
                m_data = tgt_metrics.get(metric, {})
                label = METRIC_LABELS[metric]
                b_str = f"{m_data['backup']:.4f}" if m_data.get('backup') is not None else "N/A"
                u_str = f"{m_data['updated']:.4f}" if m_data.get('updated') is not None else "N/A"
                d_str = format_delta(m_data.get('delta'), metric)
                tgt_lbl = target if first_row else ""
                lines.append(f"| {tgt_lbl} | {label} | {b_str} | {u_str} | {d_str} |")
                first_row = False
        lines.append("")

        # Regression
        lines.append(f"#### {family.upper()} Regression Performance")
        lines.append("| Target | Metric | Backup | Updated | Delta |")
        lines.append("| :--- | :--- | :---: | :---: | :---: |")
        for target in REGRESSION_TARGETS:
            tgt_metrics = fam_data["regression"].get(target, {})
            first_row = True
            for metric in ["rmse", "mae", "r2"]:
                m_data = tgt_metrics.get(metric, {})
                label = METRIC_LABELS[metric]
                b_str = f"{m_data['backup']:.4f}" if m_data.get('backup') is not None else "N/A"
                u_str = f"{m_data['updated']:.4f}" if m_data.get('updated') is not None else "N/A"
                d_str = format_delta(m_data.get('delta'), metric)
                tgt_lbl = target if first_row else ""
                lines.append(f"| {tgt_lbl} | {label} | {b_str} | {u_str} | {d_str} |")
                first_row = False
        lines.append("")

    return "\n".join(lines)


def main():
    args = parse_args()
    
    # Set directories
    repo_root = Path(__file__).resolve().parents[2]
    backup_dir = repo_root / "backup" / "metrics" / args.backup_tag
    updated_dir = repo_root / "src" / "outputs"

    if not backup_dir.is_dir():
        print(f"Error: Backup directory not found at {backup_dir}")
        sys.exit(1)

    print(f"Comparing backup tag '{args.backup_tag}' against active runs in '{updated_dir}'...")

    # Load and process comparison data
    comparison_data = build_comparison_data(backup_dir, updated_dir)

    # Ensure output directory exists
    output_dir = args.output_dir if args.output_dir.is_absolute() else repo_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write JSON data
    json_path = output_dir / "comparison_data.json"
    json_path.write_text(json.dumps(comparison_data, indent=2), encoding="utf-8")
    print(f"Wrote JSON comparison data to {json_path}")

    # Generate and write Markdown report
    markdown_report = generate_markdown_report(comparison_data, args.backup_tag)
    report_path = output_dir / "comparison_report.md"
    report_path.write_text(markdown_report, encoding="utf-8")
    print(f"Wrote Markdown comparison report to {report_path}")


if __name__ == "__main__":
    main()
