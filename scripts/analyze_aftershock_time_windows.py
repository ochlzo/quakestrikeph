import argparse
from pathlib import Path

import pandas as pd


# INPUT_CSV = "phivolcs_gk_declustered_openquake_style.csv"

INPUT_CSV = "./outputs/clustered_ml_ready_mc_1_0.csv"
PHIVOLCS_TIME_FORMAT = "%d %B %Y - %I:%M %p"


def _role_series(df):
    if "event_role" in df.columns:
        return df["event_role"].astype(str).str.lower()

    if "sequence_label" in df.columns:
        return df["sequence_label"].astype(str).str.lower()

    raise ValueError("CSV must contain event_role or sequence_label for role totals.")


def _aftershock_mask(df):
    if "sequence_label" in df.columns:
        return df["sequence_label"].astype(str).str.lower().eq("aftershock")

    if "event_role" in df.columns:
        return df["event_role"].astype(str).str.lower().eq("aftershock")

    if "flagvector" in df.columns:
        return pd.to_numeric(df["flagvector"], errors="coerce").eq(1)

    raise ValueError("CSV must contain sequence_label, event_role, or flagvector.")


def _time_to_mainshock_days(df):
    if "time_to_mainshock_days" in df.columns:
        return pd.to_numeric(df["time_to_mainshock_days"], errors="coerce")

    if "time_since_mainshock_days" in df.columns:
        return pd.to_numeric(df["time_since_mainshock_days"], errors="coerce")

    if {"event_time", "mainshock_time"}.issubset(df.columns):
        event_time = pd.to_datetime(df["event_time"], errors="coerce")
        mainshock_time = pd.to_datetime(df["mainshock_time"], errors="coerce")
        return (event_time - mainshock_time).dt.total_seconds() / 86400

    if {"origin_time", "mainshock_time"}.issubset(df.columns):
        event_time = pd.to_datetime(
            df["origin_time"],
            format=PHIVOLCS_TIME_FORMAT,
            errors="coerce",
        )
        mainshock_time = pd.to_datetime(
            df["mainshock_time"],
            format=PHIVOLCS_TIME_FORMAT,
            errors="coerce",
        )
        return (event_time - mainshock_time).dt.total_seconds() / 86400

    if {"event_id", "event_time", "sequence_mainshock_event_id"}.issubset(df.columns):
        event_time = pd.to_datetime(df["event_time"], errors="coerce")
        event_ids = pd.to_numeric(df["event_id"], errors="coerce")
        mainshock_ids = pd.to_numeric(df["sequence_mainshock_event_id"], errors="coerce")
        time_by_event_id = pd.Series(event_time.to_numpy(), index=event_ids)
        mainshock_time = mainshock_ids.map(time_by_event_id)
        return (event_time - mainshock_time).dt.total_seconds() / 86400

    raise ValueError(
        "CSV must contain time_to_mainshock_days, time_since_mainshock_days, "
        "both event_time/origin_time and mainshock_time, "
        "or sequence_mainshock_event_id."
    )


def _cluster_id(df):
    if "vcl" in df.columns:
        return pd.to_numeric(df["vcl"], errors="coerce")

    if "sequence_id" in df.columns:
        return pd.to_numeric(df["sequence_id"], errors="coerce")

    if "cluster_id" in df.columns:
        return pd.to_numeric(df["cluster_id"], errors="coerce")

    raise ValueError("CSV must contain vcl, sequence_id, or cluster_id for cluster analysis.")


def _magnitude(df):
    if "magnitude" in df.columns:
        return pd.to_numeric(df["magnitude"], errors="coerce")

    if "Magnitude" in df.columns:
        return pd.to_numeric(df["Magnitude"], errors="coerce")

    raise ValueError("CSV must contain magnitude or Magnitude.")


def _window_result(count, denominator):
    percentage = (count / denominator * 100) if denominator else 0.0
    return {"count": int(count), "percentage": percentage}


def summarize_event_role_totals(df):
    roles = _role_series(df)

    return {
        "mainshocks": int(roles.eq("mainshock").sum()),
        "aftershocks": int(roles.eq("aftershock").sum()),
        "foreshocks": int(roles.eq("foreshock").sum()),
        "singles": int(roles.eq("single").sum()),
    }


def summarize_aftershock_windows(df):
    days_after_mainshock = _time_to_mainshock_days(df)
    aftershocks = df.loc[_aftershock_mask(df)].copy()
    aftershocks["days_after_mainshock"] = days_after_mainshock.loc[aftershocks.index]
    valid = aftershocks.dropna(subset=["days_after_mainshock"])
    valid = valid[valid["days_after_mainshock"] >= 0]

    total_valid = len(valid)
    within_24_hours = valid["days_after_mainshock"].le(1).sum()
    day_2_to_7 = (
        valid["days_after_mainshock"].gt(1)
        & valid["days_after_mainshock"].le(7)
    ).sum()
    after_day_7 = valid["days_after_mainshock"].gt(7).sum()

    return {
        "total_aftershocks": int(len(aftershocks)),
        "valid_aftershocks": int(total_valid),
        "invalid_aftershocks": int(len(aftershocks) - total_valid),
        "within_24_hours": _window_result(within_24_hours, total_valid),
        "day_2_to_7": _window_result(day_2_to_7, total_valid),
        "after_day_7": _window_result(after_day_7, total_valid),
    }


def _summarize_windows(days):
    total_valid = len(days)
    within_24_hours = days.le(1).sum()
    day_2_to_7 = (days.gt(1) & days.le(7)).sum()
    after_day_7 = days.gt(7).sum()

    return {
        "within_24_hours": _window_result(within_24_hours, total_valid),
        "day_2_to_7": _window_result(day_2_to_7, total_valid),
        "after_day_7": _window_result(after_day_7, total_valid),
    }


def summarize_strongest_aftershock_windows(df):
    days_after_mainshock = _time_to_mainshock_days(df)
    aftershocks = df.loc[_aftershock_mask(df)].copy()
    aftershocks["cluster_id"] = _cluster_id(aftershocks)
    aftershocks["days_after_mainshock"] = days_after_mainshock.loc[aftershocks.index]
    aftershocks["aftershock_magnitude"] = _magnitude(aftershocks)

    valid = aftershocks.dropna(
        subset=["cluster_id", "days_after_mainshock", "aftershock_magnitude"]
    )
    valid = valid[(valid["cluster_id"] > 0) & (valid["days_after_mainshock"] >= 0)]
    valid = valid.sort_values(
        ["cluster_id", "aftershock_magnitude", "days_after_mainshock"],
        ascending=[True, False, True],
    )
    strongest = valid.drop_duplicates(subset=["cluster_id"], keep="first")

    summary = _summarize_windows(strongest["days_after_mainshock"])
    summary["clusters_with_aftershocks"] = int(len(strongest))
    summary["invalid_aftershocks"] = int(len(aftershocks) - len(valid))
    return summary


def _format_window(label, result):
    return f"{label}: {result['count']} ({result['percentage']:.2f}%)"


def _print_window_summary(summary):
    print(_format_window("Within 24 hours after mainshock", summary["within_24_hours"]))
    print(_format_window("Day 2 to day 7 after mainshock", summary["day_2_to_7"]))
    print(_format_window("After day 7", summary["after_day_7"]))


def _print_larger_requested_window(summary):
    first_day = summary["within_24_hours"]
    days_2_to_7 = summary["day_2_to_7"]

    if first_day["count"] > days_2_to_7["count"]:
        print("Larger requested window: within 24 hours after the mainshock")
    elif days_2_to_7["count"] > first_day["count"]:
        print("Larger requested window: day 2 to day 7 after the mainshock")
    else:
        print("Larger requested window: tie between within 24 hours and day 2 to day 7")


def _print_role_totals(role_totals):
    print("Event role totals:")
    print(f"Mainshocks: {role_totals['mainshocks']}")
    print(f"Aftershocks: {role_totals['aftershocks']}")
    print(f"Foreshocks: {role_totals['foreshocks']}")
    print(f"Singles: {role_totals['singles']}")


def print_summary(summary, input_csv, strongest_summary=None, role_totals=None):
    print(f"Input: {input_csv}")
    if role_totals is not None:
        _print_role_totals(role_totals)
        print()

    print(f"Total aftershocks: {summary['total_aftershocks']}")
    print(f"Aftershocks with valid timing: {summary['valid_aftershocks']}")
    if summary["invalid_aftershocks"]:
        print(f"Aftershocks skipped for missing/invalid timing: {summary['invalid_aftershocks']}")

    print()
    print("All aftershocks:")
    _print_window_summary(summary)
    print()
    _print_larger_requested_window(summary)

    if strongest_summary is None:
        return

    print()
    print("Strongest aftershock per cluster:")
    print(f"Clusters with aftershocks: {strongest_summary['clusters_with_aftershocks']}")
    if strongest_summary["invalid_aftershocks"]:
        print(
            "Aftershocks skipped for missing cluster/time/magnitude: "
            f"{strongest_summary['invalid_aftershocks']}"
        )
    _print_window_summary(strongest_summary)
    print()
    _print_larger_requested_window(strongest_summary)


def main():
    parser = argparse.ArgumentParser(
        description="Summarize aftershock timing percentages from a clustered GK CSV."
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        default=INPUT_CSV,
        help=f"Clustered CSV to analyze. Defaults to {INPUT_CSV}.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_csv)
    df = pd.read_csv(input_path, low_memory=False)
    role_totals = summarize_event_role_totals(df)
    summary = summarize_aftershock_windows(df)
    strongest_summary = summarize_strongest_aftershock_windows(df)
    print_summary(summary, input_path, strongest_summary, role_totals)


if __name__ == "__main__":
    main()
