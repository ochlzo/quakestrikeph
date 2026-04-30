# import numpy as np
# import pandas as pd
# from zaliapin_utils import (
#     compute_nearest_neighbor_log_eta,
#     parse_phivolcs_datetime,
# )

# df = pd.read_csv("phivolcs_earthquake_1907_2026_combined.csv", low_memory=False)
# df["event_time"] = df["Date-Time"].apply(parse_phivolcs_datetime)
# df["latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
# df["longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
# df["depth_km"] = pd.to_numeric(df["Depth"], errors="coerce")
# df["magnitude"] = pd.to_numeric(df["Magnitude"], errors="coerce")

# valid = df[["event_time","latitude","longitude","depth_km","magnitude"]].notna().all(axis=1)
# df = df.loc[valid].sort_values("event_time").reset_index(drop=True)
# df["event_id"] = np.arange(len(df))

# day_ns = 24 * 60 * 60 * 1_000_000_000

# _, log_eta_b0, _, _ = compute_nearest_neighbor_log_eta(
#     event_times_ns=df["event_time"].to_numpy(dtype="datetime64[ns]").astype("int64"),
#     latitudes=df["latitude"].to_numpy(),
#     longitudes=df["longitude"].to_numpy(),
#     depths=df["depth_km"].to_numpy(),
#     magnitudes=df["magnitude"].to_numpy(),
#     event_ids=df["event_id"].to_numpy(),
#     day_ns=day_ns,
#     max_lookback_days=None,   # match the more accurate script
#     use_depth=True,
#     d_fractal=1.6,
#     b_value=0.0,              # the key bit
#     min_time_days=1.0/(24*60),
#     min_distance_km=0.1,
#     progress_interval=5000,
# )

# pd.DataFrame({"event_id": df["event_id"], "nn_log_eta_b0": log_eta_b0}) \
#     .to_csv("nn_log_eta_b0_only.csv", index=False)

import numpy as np
import pandas as pd

from zaliapin_utils import (
    compute_nearest_neighbor_log_eta,
    parse_phivolcs_datetime,
)

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

_, log_eta_b0, _, _ = compute_nearest_neighbor_log_eta(
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

pd.DataFrame({
    "event_id": df["event_id"],
    "nn_log_eta_b0": log_eta_b0,
}).to_csv("nn_log_eta_b0_only.csv", index=False)