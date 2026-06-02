import argparse
import csv
import subprocess
import sys
from pathlib import Path

try:
    from run_nn_diagnostics_for_mc import format_mc_token, output_dir_for_mc
except ModuleNotFoundError:
    from scripts.run_nn_diagnostics_for_mc import format_mc_token, output_dir_for_mc


DEFAULT_INPUT_CSV = Path("dataset/phivolcs_earthquake_2018_2026.csv")
DEFAULT_OUTPUT_ROOT = Path("src/outputs")
DEFAULT_EXE = Path("build/cluster_dataset.exe")
DEFAULT_MC = 1.0
DEFAULT_B_VALUE = 1.0
DEFAULT_D_F = 1.6
CPP_SOURCES = [
    Path("src/zaliapin-ben-zion-clustering/cluster_main.cpp"),
    Path("src/zaliapin-ben-zion-clustering/diagnostics.cpp"),
    Path("src/zaliapin-ben-zion-clustering/nearest_neighbor.cpp"),
    Path("src/zaliapin-ben-zion-clustering/clustering.cpp"),
    Path("src/zaliapin-ben-zion-clustering/clustering_output.cpp"),
]


def _is_stale(executable, sources):
    if not executable.exists():
        return True

    exe_time = executable.stat().st_mtime
    return any(source.stat().st_mtime > exe_time for source in sources)


def compile_executable(executable):
    executable = Path(executable)
    executable.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "g++",
        "-std=c++17",
        "-O2",
        "-I",
        "src/zaliapin-ben-zion-clustering",
        *[str(source) for source in CPP_SOURCES],
        "-o",
        str(executable),
    ]
    print("Compiling Zaliapin clustering executable...")
    subprocess.run(command, check=True)


def run_diagnostics(args):
    command = [
        sys.executable,
        "scripts/run_nn_diagnostics_for_mc.py",
        str(args.mc),
        "--input-csv",
        str(args.input_csv),
        "--output-root",
        str(args.output_root),
        "--b-value",
        str(args.b_value),
        "--d-f",
        str(args.d_f),
        "--hist-bin-width",
        str(args.hist_bin_width),
    ]
    if args.no_compile:
        command.append("--no-compile")
    subprocess.run(command, check=True)


def default_output_csv(output_root, mc):
    return Path(output_root) / f"clustered_ml_ready_mc_{format_mc_token(mc)}.csv"


def default_eta0_csv(output_root, mc):
    return output_dir_for_mc(output_root, mc) / "eta0_gmm_crossover.csv"


def read_eta0(eta0_csv):
    with Path(eta0_csv).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError(f"No eta0 rows found in {eta0_csv}")

    raw_value = rows[0].get("recommended_eta0_gmm_crossover")
    if raw_value is None or raw_value == "":
        raise ValueError(
            f"{eta0_csv} is missing recommended_eta0_gmm_crossover"
        )
    return float(raw_value)


def run_clustering(args, eta0, output_csv):
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(args.exe),
        str(args.input_csv),
        str(output_csv),
        str(args.mc),
        str(args.b_value),
        str(args.d_f),
        str(eta0),
    ]
    subprocess.run(command, check=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Zaliapin nearest-neighbor diagnostics and write the "
            "ML-ready clustered dataset."
        )
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--mc", type=float, default=DEFAULT_MC)
    parser.add_argument("--b-value", type=float, default=DEFAULT_B_VALUE)
    parser.add_argument("--d-f", type=float, default=DEFAULT_D_F)
    parser.add_argument("--hist-bin-width", type=float, default=0.1)
    parser.add_argument(
        "--eta0",
        type=float,
        help=(
            "Use an explicit eta_0 value instead of reading the refreshed "
            "GMM crossover diagnostics."
        ),
    )
    parser.add_argument(
        "--eta0-csv",
        type=Path,
        help="Read eta_0 from this eta0_gmm_crossover.csv file.",
    )
    parser.add_argument(
        "--skip-diagnostics",
        action="store_true",
        help="Do not rerun nearest-neighbor diagnostics before clustering.",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Do not compile the C++ executables before running.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.input_csv.exists():
        raise FileNotFoundError(f"Input CSV does not exist: {args.input_csv}")

    output_csv = args.output_csv or default_output_csv(args.output_root, args.mc)

    if not args.skip_diagnostics:
        run_diagnostics(args)

    eta0_csv = args.eta0_csv or default_eta0_csv(args.output_root, args.mc)
    eta0 = args.eta0 if args.eta0 is not None else read_eta0(eta0_csv)

    if not args.no_compile and _is_stale(args.exe, CPP_SOURCES):
        compile_executable(args.exe)

    if not args.exe.exists():
        raise FileNotFoundError(f"Clustering executable does not exist: {args.exe}")

    run_clustering(args, eta0, output_csv)
    print(f"Wrote clustered dataset: {output_csv}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
