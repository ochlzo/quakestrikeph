import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_LIGHTGBM_SCRIPT = Path("src/lightgbm/predict_aftershock.py")
DEFAULT_RANDOM_FOREST_SCRIPT = Path("src/random_forest/predict_aftershock.py")
DEFAULT_HISTORICAL_CSV = Path("dataset/phivolcs_earthquake_2018_2026.csv")
DEFAULT_SAMPLE_EVENT = {
    "date_time": "26 April 2026 - 03:20 PM",
    "latitude": 10.0,
    "longitude": 125.0,
    "depth": 20.0,
    "magnitude": 4.5,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run LightGBM and Random Forest aftershock predictors with the same "
            "input event and print a prediction/runtime comparison table."
        )
    )
    parser.add_argument("--lightgbm-script", type=Path, default=DEFAULT_LIGHTGBM_SCRIPT)
    parser.add_argument("--random-forest-script", type=Path, default=DEFAULT_RANDOM_FOREST_SCRIPT)
    parser.add_argument("--historical-csv", type=Path, default=DEFAULT_HISTORICAL_CSV)
    parser.add_argument("--event-csv", type=Path, help="CSV containing one raw event row.")
    parser.add_argument(
        "--date-time",
        default=DEFAULT_SAMPLE_EVENT["date_time"],
        help="Event Date-Time, e.g. '26 April 2026 - 03:20 PM'.",
    )
    parser.add_argument("--latitude", type=float, default=DEFAULT_SAMPLE_EVENT["latitude"])
    parser.add_argument("--longitude", type=float, default=DEFAULT_SAMPLE_EVENT["longitude"])
    parser.add_argument("--depth", type=float, default=DEFAULT_SAMPLE_EVENT["depth"])
    parser.add_argument("--magnitude", type=float, default=DEFAULT_SAMPLE_EVENT["magnitude"])
    parser.add_argument("--minimum-magnitude", type=float, default=1.0)
    parser.add_argument("--b-value", type=float, default=1.0)
    parser.add_argument("--fractal-dimension", type=float, default=1.6)
    parser.add_argument("--log10-eta0", type=float, default=-5.468679834899335)
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of timed CLI runs per predictor.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Optional path for full comparison details as JSON.",
    )
    return parser.parse_args()


def validate_args(args):
    if args.runs <= 0:
        raise ValueError("--runs must be greater than 0.")
    if not args.lightgbm_script.exists():
        raise FileNotFoundError(f"LightGBM predictor does not exist: {args.lightgbm_script}")
    if not args.random_forest_script.exists():
        raise FileNotFoundError(
            f"Random Forest predictor does not exist: {args.random_forest_script}"
        )
    if not args.historical_csv.exists():
        raise FileNotFoundError(f"Historical CSV does not exist: {args.historical_csv}")
    if args.event_csv and not args.event_csv.exists():
        raise FileNotFoundError(f"Event CSV does not exist: {args.event_csv}")


def shared_predictor_args(args):
    command_args = [
        "--historical-csv",
        str(args.historical_csv),
        "--minimum-magnitude",
        str(args.minimum_magnitude),
        "--b-value",
        str(args.b_value),
        "--fractal-dimension",
        str(args.fractal_dimension),
        "--log10-eta0",
        str(args.log10_eta0),
    ]
    if args.event_csv:
        return command_args + ["--event-csv", str(args.event_csv)]

    return command_args + [
        "--date-time",
        args.date_time,
        "--latitude",
        str(args.latitude),
        "--longitude",
        str(args.longitude),
        "--depth",
        str(args.depth),
        "--magnitude",
        str(args.magnitude),
    ]


def run_predictor(label, script_path, predictor_args, runs):
    command = [sys.executable, str(script_path), *predictor_args]
    durations = []
    latest_output = None

    for _ in range(runs):
        started_at = time.perf_counter()
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        duration = time.perf_counter() - started_at
        if completed.returncode != 0:
            raise RuntimeError(
                f"{label} predictor failed with exit code {completed.returncode}.\n"
                f"Command: {' '.join(command)}\n"
                f"STDERR:\n{completed.stderr.strip()}"
            )
        try:
            latest_output = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"{label} predictor did not write valid JSON to stdout.\n"
                f"STDOUT:\n{completed.stdout[:1000]}"
            ) from error
        durations.append(duration)

    return {
        "model": label,
        "command": command,
        "runs": runs,
        "durations_seconds": durations,
        "average_seconds": statistics.mean(durations),
        "min_seconds": min(durations),
        "max_seconds": max(durations),
        "output": latest_output,
    }


def prediction_summary(result):
    output = result["output"]
    predictions = output["predictions"]
    bins = predictions["distance_bin_probabilities_24h"]
    return {
        "model": result["model"],
        "runs": result["runs"],
        "avg_s": result["average_seconds"],
        "min_s": result["min_seconds"],
        "max_s": result["max_seconds"],
        "aftershock_24h": predictions["aftershock_24h_probability"],
        "max_mag_24h": predictions["estimated_max_aftershock_magnitude_if_aftershock_24h"],
        "highest_bin": max(bins, key=bins.get),
        "highest_bin_probability": max(bins.values()),
        "feature_count": len(output["features"]),
        "history_rows_used": output["history_rows_used"],
    }


def format_value(value):
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def print_table(rows):
    headers = [
        "model",
        "runs",
        "avg_s",
        "min_s",
        "max_s",
        "aftershock_24h",
        "max_mag_24h",
        "highest_bin",
        "bin_prob",
        "features",
        "history_rows",
    ]
    table_rows = []
    for row in rows:
        table_rows.append(
            [
                row["model"],
                row["runs"],
                row["avg_s"],
                row["min_s"],
                row["max_s"],
                row["aftershock_24h"],
                row["max_mag_24h"],
                row["highest_bin"],
                row["highest_bin_probability"],
                row["feature_count"],
                row["history_rows_used"],
            ]
        )

    widths = [
        max(len(header), *(len(format_value(row[index])) for row in table_rows))
        for index, header in enumerate(headers)
    ]
    header_line = " | ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    divider = "-+-".join("-" * width for width in widths)
    print(header_line)
    print(divider)
    for row in table_rows:
        print(
            " | ".join(
                format_value(value).ljust(widths[index])
                for index, value in enumerate(row)
            )
        )


def build_report(args, results):
    return {
        "input": {
            "historical_csv": str(args.historical_csv),
            "event_csv": None if args.event_csv is None else str(args.event_csv),
            "date_time": args.date_time,
            "latitude": args.latitude,
            "longitude": args.longitude,
            "depth": args.depth,
            "magnitude": args.magnitude,
            "minimum_magnitude": args.minimum_magnitude,
            "b_value": args.b_value,
            "fractal_dimension": args.fractal_dimension,
            "log10_eta0": args.log10_eta0,
        },
        "results": results,
        "summary": [prediction_summary(result) for result in results],
    }


def main():
    args = parse_args()
    validate_args(args)
    predictor_args = shared_predictor_args(args)
    results = [
        run_predictor("LightGBM", args.lightgbm_script, predictor_args, args.runs),
        run_predictor("Random Forest", args.random_forest_script, predictor_args, args.runs),
    ]
    summary = [prediction_summary(result) for result in results]
    print_table(summary)

    if args.json_output:
        report = build_report(args, results)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_output}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
