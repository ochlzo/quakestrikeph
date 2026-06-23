import argparse
import shutil
import sys
from pathlib import Path

# Identify paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUTS_DIR = PROJECT_ROOT / "src" / "outputs"
BACKUP_DIR = PROJECT_ROOT / "backup" / "metrics"

FAMILIES = ["catboost", "lightgbm", "random-forest", "xgboost"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Backup SEIS model training and backtesting metrics to the /backup directory."
    )
    parser.add_argument(
        "--tag",
        type=str,
        default="v2_pre_improvement",
        help="A unique folder name/tag for this backup (default: 'v2_pre_improvement').",
    )
    return parser.parse_args()


def backup_file(src_path, dest_path):
    if not src_path.exists():
        print(f"Warning: Source file not found: {src_path.relative_to(PROJECT_ROOT)}")
        return False
    
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dest_path)
    print(f"Copied: {src_path.relative_to(PROJECT_ROOT)} -> {dest_path.relative_to(PROJECT_ROOT)}")
    return True


def main():
    args = parse_args()
    dest_root = BACKUP_DIR / args.tag

    print(f"Starting backup to: {dest_root.relative_to(PROJECT_ROOT)}")
    copied_count = 0

    # 1. Backup family-level metrics
    for family in FAMILIES:
        # Training metrics
        train_metrics = OUTPUTS_DIR / family / "models_mc_1_0" / "metrics.json"
        dest_train = dest_root / family / "models_mc_1_0" / "metrics.json"
        if backup_file(train_metrics, dest_train):
            copied_count += 1

        # Backtest metrics
        backtest_metrics = OUTPUTS_DIR / family / "backtests_mc_1_0" / "backtest_metrics.json"
        dest_backtest = dest_root / family / "backtests_mc_1_0" / "backtest_metrics.json"
        if backup_file(backtest_metrics, dest_backtest):
            copied_count += 1

    # 2. Backup ensemble/seis-level metrics
    seis_backtest_metrics = OUTPUTS_DIR / "seis" / "backtests_mc_1_0" / "backtest_metrics.json"
    dest_seis_backtest = dest_root / "seis" / "backtests_mc_1_0" / "backtest_metrics.json"
    if backup_file(seis_backtest_metrics, dest_seis_backtest):
        copied_count += 1

    seis_pick_report = OUTPUTS_DIR / "seis" / "backtest_pick_report.json"
    dest_seis_pick = dest_root / "seis" / "backtest_pick_report.json"
    if backup_file(seis_pick_report, dest_seis_pick):
        copied_count += 1

    print(f"\nBackup complete. Successfully backed up {copied_count} files to '{dest_root.relative_to(PROJECT_ROOT)}'.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
