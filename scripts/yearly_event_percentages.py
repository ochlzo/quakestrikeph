import argparse
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path("phivolcs_earthquake_1907_2026_combined.csv")


def summarize_yearly_percentages(input_csv):
    df = pd.read_csv(input_csv, usecols=["Year"], low_memory=False)
    years = pd.to_numeric(df["Year"], errors="coerce")

    invalid_years = years.isna().sum()
    year_counts = (
        years.dropna()
        .astype(int)
        .value_counts()
        .sort_index()
        .rename_axis("year")
        .reset_index(name="event_count")
    )

    total_events = int(year_counts["event_count"].sum())
    year_counts["percentage_of_total"] = (
        year_counts["event_count"] / total_events * 100
    )

    return year_counts, total_events, int(invalid_years)


def print_summary(summary, total_events, invalid_years):
    printable = summary.copy()
    printable["percentage_of_total"] = printable["percentage_of_total"].map(
        lambda value: f"{value:.4f}%"
    )

    print(f"Overall total events: {total_events:,}")
    if invalid_years:
        print(f"Rows skipped due to missing/invalid Year: {invalid_years:,}")
    print()
    print(printable.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Show each year's earthquake event count as a percentage of "
            "the overall catalog total."
        )
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        default=DEFAULT_INPUT,
        type=Path,
        help=f"Input PHIVOLCS CSV path. Default: {DEFAULT_INPUT}",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to save the yearly summary as CSV.",
    )
    args = parser.parse_args()

    summary, total_events, invalid_years = summarize_yearly_percentages(
        args.input_csv
    )
    print_summary(summary, total_events, invalid_years)

    if args.output:
        summary.to_csv(args.output, index=False)
        print(f"\nSaved summary to {args.output}")


if __name__ == "__main__":
    main()
