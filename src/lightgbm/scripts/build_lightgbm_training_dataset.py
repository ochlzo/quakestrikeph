import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_INPUT_CSV = Path("outputs/clustered_ml_ready_mc_1_0.csv")
DEFAULT_OUTPUT_CSV = Path("src/lightgbm/dataset/lightgbm_training_dataset_mc_1_0.csv")
PHIVOLCS_TIME_FORMAT = "%d %B %Y - %I:%M %p"
FORECAST_HOURS = 24
DISTANCE_BINS_KM = [
    ("0_10", 0.0, 10.0),
    ("10_25", 10.0, 25.0),
    ("25_50", 25.0, 50.0),
    ("50_100", 50.0, 100.0),
    ("100_200", 100.0, 200.0),
    ("200_plus", 200.0, math.inf),
]
LOCAL_RADII_KM = [10.0, 25.0, 50.0, 100.0]
RECENT_WINDOWS_DAYS = [1, 7, 30]
NEAREST_RECENT_WINDOW_DAYS = 30


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Build a leakage-safe LightGBM training dataset from a clustered "
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


def parse_origin_time(series):
    parsed = pd.to_datetime(series, format=PHIVOLCS_TIME_FORMAT, errors="coerce")
    if parsed.isna().any():
        fallback = pd.to_datetime(series, errors="coerce")
        parsed = parsed.fillna(fallback)
    return parsed


def haversine_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0088
    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2.0 * radius_km * np.arcsin(np.sqrt(a))


def id_key(value):
    if pd.isna(value):
        return pd.NA
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text else pd.NA


def add_time_features(df):
    event_time = df["event_time"]
    df["event_year"] = event_time.dt.year
    df["event_month"] = event_time.dt.month
    df["event_dayofyear"] = event_time.dt.dayofyear
    df["event_hour"] = event_time.dt.hour
    df["event_weekday"] = event_time.dt.weekday
    return df


def add_parent_features(df):
    by_event_id = df.set_index("event_id_key")
    parent = df["parent_id_key"].map(by_event_id["event_time"])
    df["parent_time_gap_days"] = (
        df["event_time"] - parent
    ).dt.total_seconds() / 86400.0

    for source_col, output_col in [
        ("magnitude", "parent_magnitude"),
        ("depth_km", "parent_depth_km"),
        ("latitude", "parent_latitude"),
        ("longitude", "parent_longitude"),
    ]:
        df[output_col] = df["parent_id_key"].map(by_event_id[source_col])

    has_parent_location = df[
        ["parent_latitude", "parent_longitude", "latitude", "longitude"]
    ].notna().all(axis=1)
    df["parent_distance_km"] = np.nan
    df.loc[has_parent_location, "parent_distance_km"] = haversine_km(
        df.loc[has_parent_location, "latitude"],
        df.loc[has_parent_location, "longitude"],
        df.loc[has_parent_location, "parent_latitude"],
        df.loc[has_parent_location, "parent_longitude"],
    )
    df["has_parent"] = df["parent_id_key"].notna().astype(int)
    return df


def add_recent_global_features(df):
    time_ns = df["event_time"].astype("int64").to_numpy()
    order = np.arange(len(df))

    for days in RECENT_WINDOWS_DAYS:
        window_ns = int(days * 86400 * 1_000_000_000)
        starts = np.searchsorted(time_ns, time_ns - window_ns, side="left")
        df[f"events_past_{days}d"] = order - starts

    return df


def add_recent_local_features(df):
    time_ns = df["event_time"].astype("int64").to_numpy()
    lat = df["latitude"].to_numpy(dtype=float)
    lon = df["longitude"].to_numpy(dtype=float)
    magnitude = df["magnitude"].to_numpy(dtype=float)
    windows_ns = {
        days: int(days * 86400 * 1_000_000_000)
        for days in RECENT_WINDOWS_DAYS
    }
    nearest_window_ns = int(NEAREST_RECENT_WINDOW_DAYS * 86400 * 1_000_000_000)

    feature_data = {}
    for radius in LOCAL_RADII_KM:
        radius_token = int(radius)
        for days in RECENT_WINDOWS_DAYS:
            feature_data[f"local_events_{radius_token}km_past_{days}d"] = np.zeros(
                len(df),
                dtype=np.int32,
            )
            feature_data[f"local_max_mag_{radius_token}km_past_{days}d"] = np.full(
                len(df),
                np.nan,
            )
            feature_data[f"local_log10_energy_{radius_token}km_past_{days}d"] = np.full(
                len(df),
                np.nan,
            )

    nearest_distance = np.full(len(df), np.nan)
    nearest_magnitude = np.full(len(df), np.nan)
    nearest_age_days = np.full(len(df), np.nan)
    max_window_ns = windows_ns[max(RECENT_WINDOWS_DAYS)]
    max_radius_km = max(LOCAL_RADII_KM)
    max_window_starts = np.searchsorted(time_ns, time_ns - max_window_ns, side="left")
    lat_delta_degrees = max_radius_km / 111.32

    for row_index in range(len(df)):
        max_start = max_window_starts[row_index]
        if max_start == row_index:
            continue

        candidate_lat = lat[max_start:row_index]
        candidate_lon = lon[max_start:row_index]
        lon_scale = max(math.cos(math.radians(lat[row_index])), 0.1)
        lon_delta_degrees = max_radius_km / (111.32 * lon_scale)
        bounding_box_mask = (
            (np.abs(candidate_lat - lat[row_index]) <= lat_delta_degrees)
            & (np.abs(candidate_lon - lon[row_index]) <= lon_delta_degrees)
        )
        if not bounding_box_mask.any():
            continue

        candidates = max_start + np.flatnonzero(bounding_box_mask)
        candidate_times = time_ns[candidates]
        candidate_magnitudes = magnitude[candidates]
        distances = haversine_km(
            lat[row_index],
            lon[row_index],
            lat[candidates],
            lon[candidates],
        )
        radius_mask = distances <= max_radius_km
        if not radius_mask.any():
            continue

        candidates = candidates[radius_mask]
        candidate_times = candidate_times[radius_mask]
        candidate_magnitudes = candidate_magnitudes[radius_mask]
        distances = distances[radius_mask]

        nearest_window_mask = candidate_times >= time_ns[row_index] - nearest_window_ns
        if nearest_window_mask.any():
            nearest_positions = np.flatnonzero(nearest_window_mask)
            nearest_position = nearest_positions[
                int(np.nanargmin(distances[nearest_window_mask]))
            ]
            nearest_distance[row_index] = float(distances[nearest_position])
            nearest_magnitude[row_index] = float(candidate_magnitudes[nearest_position])
            nearest_age_days[row_index] = float(
                (time_ns[row_index] - candidate_times[nearest_position])
                / (86400 * 1_000_000_000)
            )

        for days in RECENT_WINDOWS_DAYS:
            window_mask = candidate_times >= time_ns[row_index] - windows_ns[days]
            if not window_mask.any():
                continue

            window_distances = distances[window_mask]
            window_magnitudes = candidate_magnitudes[window_mask]
            for radius in LOCAL_RADII_KM:
                radius_token = int(radius)
                local_mask = window_distances <= radius
                local_count = int(local_mask.sum())
                if not local_count:
                    continue

                local_magnitudes = window_magnitudes[local_mask]
                feature_data[f"local_events_{radius_token}km_past_{days}d"][
                    row_index
                ] = local_count
                feature_data[f"local_max_mag_{radius_token}km_past_{days}d"][
                    row_index
                ] = float(np.nanmax(local_magnitudes))
                feature_data[f"local_log10_energy_{radius_token}km_past_{days}d"][
                    row_index
                ] = float(np.log10(np.nansum(10.0 ** (1.5 * local_magnitudes))))

    for feature_name, values in feature_data.items():
        df[feature_name] = values
    df[f"nearest_recent_event_distance_km_past_{NEAREST_RECENT_WINDOW_DAYS}d"] = nearest_distance
    df[f"nearest_recent_event_magnitude_past_{NEAREST_RECENT_WINDOW_DAYS}d"] = nearest_magnitude
    df[f"nearest_recent_event_age_days_past_{NEAREST_RECENT_WINDOW_DAYS}d"] = nearest_age_days

    return df


def add_forecast_targets(df, forecast_hours):
    forecast_days = forecast_hours / 24.0
    target_aftershock = np.zeros(len(df), dtype=np.int8)
    target_nearest_distance = np.full(len(df), np.nan)
    target_max_distance = np.full(len(df), np.nan)
    target_max_magnitude = np.full(len(df), np.nan)
    distance_targets = {
        name: np.zeros(len(df), dtype=np.int8)
        for name, _, _ in DISTANCE_BINS_KM
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
            target_nearest_distance[original_index] = float(np.nanmin(distances))
            target_max_distance[original_index] = float(np.nanmax(distances))
            target_max_magnitude[original_index] = float(np.nanmax(magnitudes[future_positions]))

            for name, low, high in DISTANCE_BINS_KM:
                if math.isinf(high):
                    in_bin = distances >= low
                else:
                    in_bin = (distances >= low) & (distances < high)
                distance_targets[name][original_index] = int(in_bin.any())

    df["aftershock_24h"] = target_aftershock
    for name, values in distance_targets.items():
        df[f"aftershock_dist_{name}km_24h"] = values
    df["nearest_aftershock_distance_km_24h"] = target_nearest_distance
    df["max_aftershock_distance_km_24h"] = target_max_distance
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
        "aftershock_24h",
        *[f"aftershock_dist_{name}km_24h" for name, _, _ in DISTANCE_BINS_KM],
        "nearest_aftershock_distance_km_24h",
        "max_aftershock_distance_km_24h",
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
