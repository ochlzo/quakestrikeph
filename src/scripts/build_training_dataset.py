import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from feature_engineering import (  # noqa: E402
    LOCAL_RADII_KM,
    NEAREST_RECENT_WINDOW_DAYS,
    RECENT_WINDOWS_DAYS,
    add_parent_features,
    add_recent_global_features,
    add_recent_local_features,
    add_time_features,
    haversine_km,
    id_key,
    parse_origin_time,
)


DEFAULT_INPUT_CSV = Path("src/outputs/clustered_ml_ready_mc_1_0.csv")
DEFAULT_OUTPUT_CSV = Path("src/training_set/training_dataset_mc_1_0.csv")
FORECAST_HOURS = 24
# Cumulative containment radii (km). Each yields a monotone "is there >=1
# aftershock within R km?" target -- nested, not disjoint donut bins -- so that
# P(within 10) <= P(within 25) <= ... <= P(aftershock). These replace the old
# disjoint distance bins, which were harder to learn and could not be made
# monotone. See the distance-target redesign (B + C).
# Local-history radii / windows (LOCAL_RADII_KM, RECENT_WINDOWS_DAYS,
# NEAREST_RECENT_WINDOW_DAYS) are imported from feature_engineering above so the
# batch feature builders and select_training_columns agree on the column names.
CUMULATIVE_RADII_KM = [10.0, 25.0, 50.0]



def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Build a leakage-safe model training dataset from a clustered "
            "Zaliapin-style earthquake CSV."
        )
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--forecast-hours", type=float, default=FORECAST_HOURS)
    parser.add_argument(
        "--include-local-history",
        dest="include_local_history",
        action="store_true",
        default=True,
        help=(
            "Compute local seismic-history features across 10, 25, 50, and "
            "100 km radius bands. This is enabled by default."
        ),
    )
    parser.add_argument(
        "--skip-local-history",
        dest="include_local_history",
        action="store_false",
        help="Build the faster reduced dataset with global recent-event counts only.",
    )
    return parser.parse_args()


def add_forecast_targets(df, forecast_hours):
    forecast_days = forecast_hours / 24.0
    target_aftershock = np.zeros(len(df), dtype=np.int8)
    target_nearest_distance = np.full(len(df), np.nan)
    target_median_distance = np.full(len(df), np.nan)
    target_p90_distance = np.full(len(df), np.nan)
    target_max_magnitude = np.full(len(df), np.nan)
    within_targets = {
        radius: np.zeros(len(df), dtype=np.int8)
        for radius in CUMULATIVE_RADII_KM
    }

    aftershock_clusters = set(
        df.loc[
            df["event_role"].astype(str).str.lower().eq("aftershock"),
            "cluster_id",
        ]
    )
    candidate_df = df[df["cluster_id"].isin(aftershock_clusters)]

    for _, group in candidate_df.groupby("cluster_id", sort=False):
        group = group.sort_values("event_time")
        group_indices = group.index.to_numpy()
        times = group["event_time"].to_numpy(dtype="datetime64[ns]")
        latitudes = group["latitude"].to_numpy(dtype=float)
        longitudes = group["longitude"].to_numpy(dtype=float)
        magnitudes = group["magnitude"].to_numpy(dtype=float)
        is_aftershock = group["event_role"].astype(str).str.lower().eq("aftershock").to_numpy()

        aftershock_positions = np.flatnonzero(is_aftershock)
        if len(aftershock_positions) == 0:
            continue

        for position, original_index in enumerate(group_indices):
            start = np.searchsorted(times, times[position], side="right")
            end = np.searchsorted(
                times,
                times[position] + np.timedelta64(int(forecast_days * 86400), "s"),
                side="right",
            )
            if start >= end:
                continue

            future_positions = aftershock_positions[
                (aftershock_positions >= start) & (aftershock_positions < end)
            ]
            if len(future_positions) == 0:
                continue

            distances = haversine_km(
                latitudes[position],
                longitudes[position],
                latitudes[future_positions],
                longitudes[future_positions],
            )
            target_aftershock[original_index] = 1
            # Robust statistics of the aftershock distance cloud (B). The median
            # and p90 are stable; the old max was almost pure tail (p95 ~ 500 km)
            # and not learnable. Reported back as a range at inference.
            target_nearest_distance[original_index] = float(np.nanmin(distances))
            target_median_distance[original_index] = float(np.nanmedian(distances))
            target_p90_distance[original_index] = float(np.nanpercentile(distances, 90))
            target_max_magnitude[original_index] = float(np.nanmax(magnitudes[future_positions]))

            # Cumulative containment (C): >=1 aftershock within R km. Nested and
            # monotone across radii by construction.
            for radius in CUMULATIVE_RADII_KM:
                within_targets[radius][original_index] = int((distances <= radius).any())

    # Define multi-class spatial target: 0 = none, 1 = within 10km, 2 = 10-25km, 3 = 25-50km, 4 = >50km
    target_spatial_zone = np.zeros(len(df), dtype=np.int8)
    has_aftershock = target_aftershock == 1
    nearest = target_nearest_distance
    
    target_spatial_zone[has_aftershock & (nearest <= 10.0)] = 1
    target_spatial_zone[has_aftershock & (nearest > 10.0) & (nearest <= 25.0)] = 2
    target_spatial_zone[has_aftershock & (nearest > 25.0) & (nearest <= 50.0)] = 3
    target_spatial_zone[has_aftershock & (nearest > 50.0)] = 4

    df["aftershock_spatial_zone_24h"] = target_spatial_zone
    df["aftershock_24h"] = target_aftershock
    for radius, values in within_targets.items():
        df[f"aftershock_within_{int(radius)}km_24h"] = values
    df["aftershock_beyond_50km_24h"] = (target_spatial_zone == 4).astype(np.int8)
    df["nearest_aftershock_distance_km_24h"] = target_nearest_distance
    df["median_aftershock_distance_km_24h"] = target_median_distance
    df["p90_aftershock_distance_km_24h"] = target_p90_distance
    df["max_aftershock_mag_24h"] = target_max_magnitude
    return df



def select_training_columns(df, include_local_history):
    feature_columns = [
        "magnitude",
        "depth_km",
        "latitude",
        "longitude",
        "eta",
        "log10_eta",
        "log10_rescaled_time",
        "log10_rescaled_distance",
        "is_strong_link",
        "has_parent",
        "parent_time_gap_days",
        "parent_distance_km",
        "parent_magnitude",
        "parent_depth_km",
        "event_year",
        "event_month",
        "event_dayofyear",
        "event_hour",
        "event_weekday",
    ]

    for days in RECENT_WINDOWS_DAYS:
        feature_columns.append(f"events_past_{days}d")
        if include_local_history:
            for radius in LOCAL_RADII_KM:
                radius_token = int(radius)
                feature_columns.extend(
                    [
                        f"local_events_{radius_token}km_past_{days}d",
                        f"local_max_mag_{radius_token}km_past_{days}d",
                        f"local_log10_energy_{radius_token}km_past_{days}d",
                    ]
                )

    if include_local_history:
        feature_columns.extend(
            [
                f"nearest_recent_event_distance_km_past_{NEAREST_RECENT_WINDOW_DAYS}d",
                f"nearest_recent_event_magnitude_past_{NEAREST_RECENT_WINDOW_DAYS}d",
                f"nearest_recent_event_age_days_past_{NEAREST_RECENT_WINDOW_DAYS}d",
            ]
        )

    target_columns = [
        "aftershock_spatial_zone_24h",
        "aftershock_24h",
        *[f"aftershock_within_{int(radius)}km_24h" for radius in CUMULATIVE_RADII_KM],
        "aftershock_beyond_50km_24h",
        "nearest_aftershock_distance_km_24h",
        "median_aftershock_distance_km_24h",
        "p90_aftershock_distance_km_24h",
        "max_aftershock_mag_24h",
    ]
    metadata_columns = [
        "event_id",
        "origin_time",
        "event_time",
        "year",
        "month",
    ]

    selected = df[metadata_columns + feature_columns + target_columns].copy()
    selected["is_strong_link"] = selected["is_strong_link"].astype(str).str.lower().eq("true").astype(int)
    return selected, feature_columns, target_columns


def main():
    args = parse_args()
    if not args.input_csv.exists():
        raise FileNotFoundError(f"Input CSV does not exist: {args.input_csv}")

    df = pd.read_csv(args.input_csv, low_memory=False)
    required_columns = {
        "event_id",
        "origin_time",
        "latitude",
        "longitude",
        "depth_km",
        "magnitude",
        "parent_id",
        "eta",
        "log10_eta",
        "is_strong_link",
        "cluster_id",
        "event_role",
    }
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        raise ValueError(f"Input CSV is missing required columns: {missing_columns}")

    df["event_time"] = parse_origin_time(df["origin_time"])
    if df["event_time"].isna().any():
        bad_count = int(df["event_time"].isna().sum())
        raise ValueError(f"Could not parse origin_time for {bad_count} rows.")

    df["event_id_key"] = df["event_id"].map(id_key)
    df["parent_id_key"] = df["parent_id"].map(id_key)
    df = df.sort_values(["event_time", "event_id"], kind="mergesort").reset_index(drop=True)

    df = add_time_features(df)
    df = add_parent_features(df)
    df = add_recent_global_features(df)
    if args.include_local_history:
        df = add_recent_local_features(df)
    df = add_forecast_targets(df, args.forecast_hours)

    training_df, feature_columns, target_columns = select_training_columns(
        df,
        args.include_local_history,
    )
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    training_df.to_csv(args.output_csv, index=False)

    feature_path = args.output_csv.with_suffix(".features.txt")
    target_path = args.output_csv.with_suffix(".targets.txt")
    feature_path.write_text("\n".join(feature_columns) + "\n", encoding="utf-8")
    target_path.write_text("\n".join(target_columns) + "\n", encoding="utf-8")

    positives = int(training_df["aftershock_24h"].sum())
    print(f"Wrote {args.output_csv}")
    print(f"Rows: {len(training_df)}")
    print(f"aftershock_24h positives: {positives} ({positives / len(training_df) * 100:.2f}%)")
    print(f"Feature columns: {feature_path}")
    print(f"Target columns: {target_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
