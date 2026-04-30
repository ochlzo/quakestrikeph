# import pandas as pd, numpy as np
# b0_full = pd.read_csv("nn_log_eta_b0_only.csv")
# # you'll need to also save parent_distances etc. — re-run with a fuller output
# # then:
# clustered = b0_full[b0_full["nn_log_eta_b0"] < -7]
# print(clustered.describe())

# import pandas as pd
# from zaliapin_utils import estimate_log_eta_threshold

# b0 = pd.read_csv("nn_log_eta_b0_only.csv")["nn_log_eta_b0"].dropna()

# log_eta_0, info = estimate_log_eta_threshold(b0)
# print(f"GMM-selected log10(eta0) = {log_eta_0:.3f}")
# print(f"eta0 = {10**log_eta_0:.3e}")
# print(info)

import numpy as np
import pandas as pd

from zaliapin_utils import (
    compute_nearest_neighbor_log_eta,
    parse_phivolcs_datetime,
)

# ---------------------------------------------------------------
# Load and clean catalog (same as before)
# ---------------------------------------------------------------
df = pd.read_csv("phivolcs_earthquake_1907_2026_combined.csv", low_memory=False)

df["event_time"] = df["Date-Time"].apply(parse_phivolcs_datetime)
df["latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
df["longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
df["depth_km"] = pd.to_numeric(df["Depth"], errors="coerce")
df["magnitude"] = pd.to_numeric(df["Magnitude"], errors="coerce")

valid = df[
    ["event_time", "latitude", "longitude", "depth_km", "magnitude"]
].notna().all(axis=1)

df = df.loc[valid].sort_values("event_time").reset_index(drop=True)
df["event_id"] = np.arange(len(df))

day_ns = 24 * 60 * 60 * 1_000_000_000

# ---------------------------------------------------------------
# Compute nearest-neighbor with FULL output (b=0)
# ---------------------------------------------------------------
parent_ids, log_eta_b0, parent_distances, parent_dt_days = (
    compute_nearest_neighbor_log_eta(
        event_times_ns=df["event_time"].to_numpy(dtype="datetime64[ns]").astype("int64"),
        latitudes=df["latitude"].to_numpy(),
        longitudes=df["longitude"].to_numpy(),
        depths=df["depth_km"].to_numpy(),
        magnitudes=df["magnitude"].to_numpy(),
        event_ids=df["event_id"].to_numpy(),
        day_ns=day_ns,
        max_lookback_days=None,
        use_depth=True,
        d_fractal=2.5,
        b_value=0.0,
        min_time_days=1.0 / (24 * 60 * 60),
        min_distance_km=0.001,
        progress_interval=5000,
    )
)

full = pd.DataFrame({
    "event_id": df["event_id"],
    "event_time": df["event_time"],
    "latitude": df["latitude"],
    "longitude": df["longitude"],
    "depth_km": df["depth_km"],
    "magnitude": df["magnitude"],
    "nn_log_eta_b0": log_eta_b0,
    "parent_id": parent_ids,
    "parent_distance_km": parent_distances,
    "parent_dt_days": parent_dt_days,
})

full.to_csv("nn_full_b0.csv", index=False)
print(f"Saved nn_full_b0.csv with {len(full):,} rows")

# ---------------------------------------------------------------
# Inspect the clustered (left) mode
# ---------------------------------------------------------------
LEFT_MODE_CUTOFF = -7.0   # everything left of the trough
DISTANCE_FLOOR_KM = 0.001
FLOOR_TOLERANCE = 1e-4    # treat anything within 0.0001 km of floor as "at floor"

clustered = full[full["nn_log_eta_b0"] < LEFT_MODE_CUTOFF].copy()

print(f"\n{'='*60}")
print(f"Events in clustered mode (log10 eta < {LEFT_MODE_CUTOFF}): {len(clustered):,}")
print(f"({100*len(clustered)/len(full):.2f}% of catalog)")
print(f"{'='*60}\n")

print("Distribution of parent distance (km):")
print(clustered["parent_distance_km"].describe())

print("\nDistribution of parent dt (days):")
print(clustered["parent_dt_days"].describe())

# Floor counts
at_dist_floor = (
    clustered["parent_distance_km"] <= DISTANCE_FLOOR_KM + FLOOR_TOLERANCE
).sum()
print(
    f"\nAt distance floor ({DISTANCE_FLOOR_KM} km): "
    f"{at_dist_floor:,} of {len(clustered):,} "
    f"({100*at_dist_floor/max(len(clustered),1):.1f}%)"
)

# How many parent-child pairs share identical lat/lon/depth (post-floor)
# This requires looking up the parent row
parent_lookup = full.set_index("event_id")[
    ["latitude", "longitude", "depth_km"]
].rename(columns={
    "latitude": "parent_lat",
    "longitude": "parent_lon",
    "depth_km": "parent_depth",
})

clustered_with_parent = clustered.merge(
    parent_lookup, left_on="parent_id", right_index=True, how="left"
)

identical_coords = (
    (clustered_with_parent["latitude"] == clustered_with_parent["parent_lat"])
    & (clustered_with_parent["longitude"] == clustered_with_parent["parent_lon"])
    & (clustered_with_parent["depth_km"] == clustered_with_parent["parent_depth"])
).sum()

print(
    f"Identical (lat, lon, depth) to parent: "
    f"{identical_coords:,} of {len(clustered):,} "
    f"({100*identical_coords/max(len(clustered),1):.1f}%)"
)

# ---------------------------------------------------------------
# Show a few of the most extreme clustered events for eyeballing
# ---------------------------------------------------------------
print("\n10 most clustered events (smallest log10 eta):")
cols = [
    "event_time", "latitude", "longitude", "depth_km", "magnitude",
    "nn_log_eta_b0", "parent_id", "parent_distance_km", "parent_dt_days",
]
print(clustered.nsmallest(10, "nn_log_eta_b0")[cols].to_string(index=False))

# Save the clustered-mode subset for closer inspection
clustered_with_parent.to_csv("clustered_mode_b0.csv", index=False)
print("\nSaved clustered_mode_b0.csv for further inspection")