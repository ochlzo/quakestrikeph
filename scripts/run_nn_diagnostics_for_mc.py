import argparse
import subprocess
import sys
from pathlib import Path

try:
    from visualize_log10_eta_histograms import generate_all_outputs
except ModuleNotFoundError:
    from scripts.visualize_log10_eta_histograms import generate_all_outputs


DEFAULT_INPUT_CSV = Path("dataset/phivolcs_earthquake_2018_2026.csv")
DEFAULT_OUTPUT_ROOT = Path("outputs")
DEFAULT_EXE = Path("build/nn_diagnostics.exe")
CPP_SOURCES = [
    Path("src/zaliapin-ben-zion-clustering/nn_main.cpp"),
    Path("src/zaliapin-ben-zion-clustering/diagnostics.cpp"),
    Path("src/zaliapin-ben-zion-clustering/nearest_neighbor.cpp"),
    Path("src/zaliapin-ben-zion-clustering/nearest_neighbor_output.cpp"),
]


def format_mc_token(value):
    text = f"{value:.1f}" if float(value).is_integer() else f"{value:.6g}"
    return text.replace(".", "_").replace("-", "neg_")


def output_dir_for_mc(output_root, value):
    return Path(output_root) / f"nn_diagnostics_mc_{format_mc_token(value)}"


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
    print("Compiling nearest-neighbor diagnostic executable...")
    subprocess.run(command, check=True)


def run_diagnostic(executable, input_csv, output_dir, mc, b_value, d_f, hist_bin_width):
    command = [
        str(executable),
        str(input_csv),
        str(output_dir),
        str(mc),
        str(b_value),
        str(d_f),
        str(hist_bin_width),
    ]
    subprocess.run(command, check=True)


def has_required_outputs(output_dir):
    output_dir = Path(output_dir)
    return (
        (output_dir / "nearest_neighbor_diagnostics.csv").exists()
        and (output_dir / "log10_eta_histogram.csv").exists()
    )


def process_mc_value(args, mc):
    output_dir = output_dir_for_mc(args.output_root, mc)
    histogram_csv = output_dir / "log10_eta_histogram.csv"

    if args.skip_existing and has_required_outputs(output_dir):
        print(f"Skipping m_c={mc}; outputs already exist in {output_dir}")
    else:
        print(f"Running nearest-neighbor diagnostics for m_c={mc}")
        run_diagnostic(
            args.exe,
            args.input_csv,
            output_dir,
            mc,
            args.b_value,
            args.d_f,
            args.hist_bin_width,
        )

    if histogram_csv.exists():
        for output_png in generate_all_outputs(histogram_csv):
            print(f"Wrote {output_png}")
    else:
        raise FileNotFoundError(f"Expected histogram was not created: {histogram_csv}")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run nearest-neighbor diagnostics and generated eta0/GMM plots "
            "for one or more m_c values."
        )
    )
    parser.add_argument("mc_values", nargs="+", type=float, help="m_c values to test.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--b-value", type=float, default=1.0)
    parser.add_argument("--d-f", type=float, default=1.6)
    parser.add_argument("--hist-bin-width", type=float, default=0.1)
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Reuse existing nearest-neighbor CSVs and only regenerate plots/GMM CSVs.",
    )
    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="Do not compile the C++ diagnostic executable before running.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.input_csv.exists():
        raise FileNotFoundError(f"Input CSV does not exist: {args.input_csv}")

    if not args.no_compile and _is_stale(args.exe, CPP_SOURCES):
        compile_executable(args.exe)

    if not args.exe.exists():
        raise FileNotFoundError(f"Diagnostic executable does not exist: {args.exe}")

    for mc in args.mc_values:
        process_mc_value(args, mc)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
