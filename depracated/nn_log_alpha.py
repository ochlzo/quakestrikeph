import numpy as np
import pandas as pd

from zaliapin_utils import (
    compute_nearest_neighbor_log_eta_2cat,
    parse_phivolcs_datetime,
)

# ---------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------
ETA0 = 1e-6
LOG_ETA0 = np.log10(ETA0)
M = 50                       # number of randomized catalogs
D_FRACTAL = 2.5
B_VALUE = 0.0
USE_DEPTH = True
MIN_TIME_DAYS = 1.0 / (24 * 60 * 60)
MIN_DIST_KM = 0.001
RANDOM_SEED = 42

day_ns = 24 * 60 * 60 * 1_000_000_000

# ---------------------------------------------------------------
# Load catalog and existing b=0 results
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

b0 = pd.read_csv("nn_log_eta_b0_only.csv")
df = df.merge(b0, on="event_id", how="left")

print(f"Catalog: {len(df):,} events")

# ---------------------------------------------------------------
# Step 1: identify the non-clustered subset (spatial template)
# ---------------------------------------------------------------
non_clustered_mask = df["nn_log_eta_b0"].to_numpy() > LOG_ETA0
non_clustered = df.loc[non_clustered_mask].reset_index(drop=True)

print(f"Non-clustered subset (log10 eta > {LOG_ETA0}): {len(non_clustered):,}")
print(f"Removed (clustered): {(~non_clustered_mask).sum():,}")

# ---------------------------------------------------------------
# Pre-extract arrays
# ---------------------------------------------------------------
real_times_ns = df["event_time"].to_numpy(dtype="datetime64[ns]").astype("int64")
real_lats = df["latitude"].to_numpy()
real_lons = df["longitude"].to_numpy()
real_deps = df["depth_km"].to_numpy()

t_min_ns = real_times_ns.min()
t_max_ns = real_times_ns.max()

n_full = len(df)
n_nc = len(non_clustered)

nc_lats = non_clustered["latitude"].to_numpy()
nc_lons = non_clustered["longitude"].to_numpy()
nc_deps = non_clustered["depth_km"].to_numpy()
nc_mags = non_clustered["magnitude"].to_numpy()

# ---------------------------------------------------------------
# Step 2: for each randomized catalog C_k, compute kappa_{k,i}
#         for every real event i
# ---------------------------------------------------------------
rng = np.random.default_rng(RANDOM_SEED)

log_kappa = np.full((n_full, M), np.nan)

for k in range(M):
    print(f"\n--- Randomized catalog {k+1}/{M} ---")

    # Build C_k:
    #   spatial coords sampled (with replacement) from non-clustered subset
    #   times uniform on [t_min, t_max], then sorted
    #   magnitudes: random permutation of non-clustered magnitudes
    spatial_idx = rng.integers(0, n_nc, size=n_nc)
    ck_lats = nc_lats[spatial_idx]
    ck_lons = nc_lons[spatial_idx]
    ck_deps = nc_deps[spatial_idx]

    ck_times_ns = rng.integers(t_min_ns, t_max_ns, size=n_nc, dtype=np.int64)
    sort_order = np.argsort(ck_times_ns, kind="stable")
    ck_times_ns = ck_times_ns[sort_order]
    ck_lats = ck_lats[sort_order]
    ck_lons = ck_lons[sort_order]
    ck_deps = ck_deps[sort_order]

    ck_mags = rng.permutation(nc_mags)
    # magnitudes were permuted independently, no need to sort with times

    # For every real event i, find nearest neighbor in C_k
    _, log_eta_k, _, _ = compute_nearest_neighbor_log_eta_2cat(
        target_times_ns=real_times_ns,
        target_lats=real_lats,
        target_lons=real_lons,
        target_deps=real_deps,
        parent_times_ns=ck_times_ns,
        parent_lats=ck_lats,
        parent_lons=ck_lons,
        parent_deps=ck_deps,
        parent_mags=ck_mags,
        day_ns=day_ns,
        max_lookback_days=None,
        use_depth=USE_DEPTH,
        d_fractal=D_FRACTAL,
        b_value=B_VALUE,
        min_time_days=MIN_TIME_DAYS,
        min_distance_km=MIN_DIST_KM,
        progress_interval=20000,
    )

    log_kappa[:, k] = log_eta_k

    n_filled = np.sum(np.isfinite(log_eta_k))
    print(f"  kappa filled for {n_filled:,}/{n_full:,} real events")

# ---------------------------------------------------------------
# Step 3: compute log_alpha
#   log10(alpha_i) = log10(eta_i) - mean_k[log10(kappa_{k,i})]
# ---------------------------------------------------------------
mean_log_kappa = np.nanmean(log_kappa, axis=1)
log_eta_real = df["nn_log_eta_b0"].to_numpy()
log_alpha = log_eta_real - mean_log_kappa

# Save log_kappa as well in case we want to look at variance later
result = pd.DataFrame({
    "event_id": df["event_id"],
    "nn_log_eta_b0": log_eta_real,
    "mean_log_kappa": mean_log_kappa,
    "log_alpha": log_alpha,
})
result.to_csv("nn_log_alpha.csv", index=False)

# Save the full log_kappa matrix too
np.save("log_kappa_matrix.npy", log_kappa)

print("\n--- Step 2/3 complete ---")
print(f"Saved nn_log_alpha.csv")
print(f"Saved log_kappa_matrix.npy ({log_kappa.shape})")

# Quick summary
print(f"\nlog_alpha summary:")
print(pd.Series(log_alpha).describe())