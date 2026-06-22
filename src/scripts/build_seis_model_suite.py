"""Package the deployed SEIS hybrid model suite into a single, self-contained zip.

The SEIS predictor (``src/seis/predict.py``) is a per-target ensemble: for each
of the ten aftershock targets it serves exactly one model, chosen from the
xgboost / lightgbm / catboost families (Random Forest wins no target, so it is
excluded). This script gathers everything that predictor needs at runtime -- the
serving code, the shared feature module, the chosen-family model artifacts, the
historical catalog, and the per-family requirements -- preserving the
repo-relative layout so ``predict.py`` runs unchanged from the extracted root:

    python src/seis/predict.py --date-time "26 April 2026 - 03:20 PM" \
        --latitude 14.6 --longitude 121.0 --depth 10 --magnitude 5.2

What is included (decided with the maintainer):
  * Runtime serving code only -- no training/backtest/report scripts.
  * Model artifacts for the three served families only (xgboost, lightgbm,
    catboost), each as ``.joblib`` + native fallback (``.json`` / ``.txt`` /
    ``.cbm``) + ``feature_columns.txt``. Per-target ``*_feature_importances.csv``
    and ``metrics.json`` are omitted (not used for serving).
  * The 13 MB historical catalog (feature engineering reads it for every event).
  * requirements for the three served families.
"""

import argparse
import sys
import zipfile
from pathlib import Path

# root/src/scripts/this_file -> parents[2] == repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUTPUT = Path("build/seis_model_suite.zip")

# Families the ensemble actually serves, with their native model extension.
SERVED_FAMILIES = {
    "xgboost": ".json",
    "lightgbm": ".txt",
    "catboost": ".cbm",
}

# Per-family model-dir entries we never ship (regenerable, serving-irrelevant).
MODEL_DIR_EXCLUDE_SUFFIXES = ("_feature_importances.csv",)
MODEL_DIR_EXCLUDE_NAMES = {"metrics.json"}

# Runtime serving code. predict.py is self-contained (serving helpers inlined),
# so it depends only on the shared feature module; predict.py resolves it via an
# __file__-relative path (src/scripts), so the repo-relative layout is preserved.
CODE_FILES = [
    "src/seis/predict.py",
    "src/scripts/feature_engineering.py",
]

# Historical catalog (default --historical-csv) + per-family requirements.
DATA_FILES = ["dataset/phivolcs_earthquake_2018_2026.csv"]
REQUIREMENT_FILES = [f"requirements-{family}.txt" for family in SERVED_FAMILIES]


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Zip path, relative to repo root (default: {DEFAULT_OUTPUT}).",
    )
    return parser.parse_args()


def model_dir_files(family):
    """Serving artifacts for one family's models dir: joblib + native + the
    feature manifest, minus importances/metrics."""
    models_dir = REPO_ROOT / "src" / "outputs" / family / "models_mc_1_0"
    if not models_dir.is_dir():
        raise FileNotFoundError(f"Missing models directory: {models_dir}")
    selected = []
    for path in sorted(models_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in MODEL_DIR_EXCLUDE_NAMES:
            continue
        if path.name.endswith(MODEL_DIR_EXCLUDE_SUFFIXES):
            continue
        selected.append(path)
    return selected


def collect_files():
    """Return the full list of absolute paths to bundle, verifying each exists."""
    rel_files = CODE_FILES + DATA_FILES + REQUIREMENT_FILES
    paths = []
    missing = []
    for rel in rel_files:
        path = REPO_ROOT / rel
        (paths if path.is_file() else missing).append(path)
    for family in SERVED_FAMILIES:
        paths.extend(model_dir_files(family))
    if missing:
        listing = "\n".join(f"  - {p}" for p in missing)
        raise FileNotFoundError(f"Missing required files:\n{listing}")
    return paths


def main():
    args = parse_args()
    output_path = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)

    paths = collect_files()

    total_bytes = 0
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in paths:
            arcname = path.relative_to(REPO_ROOT).as_posix()
            zf.write(path, arcname)
            total_bytes += path.stat().st_size

    zipped_bytes = output_path.stat().st_size
    print(f"Wrote {output_path.relative_to(REPO_ROOT).as_posix()}")
    print(f"  files:       {len(paths)}")
    print(f"  uncompressed: {total_bytes / 1e6:.1f} MB")
    print(f"  zip size:     {zipped_bytes / 1e6:.1f} MB")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - surface a clean CLI error
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
