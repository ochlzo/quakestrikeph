"""
QuakeStrike PH - Zaliapin-Ben-Zion nearest-neighbor declustering (v2)
with practical mainshock-aftershock sequence association labels.

This revision (v2) addresses the methodological flags raised during review of
the previous local-percentile / spatial-K-pool implementation. It now follows
Zaliapin & Ben-Zion (2020) Eq. 7 exactly: alpha_i is computed per-event using
the geometric mean of cross-catalog proximities of event i against M
randomized-reshuffled catalogs.

Reference:
    Zaliapin, I., & Ben-Zion, Y. (2020). Earthquake declustering using the
    nearest-neighbor approach in space-time-magnitude domain.
    Journal of Geophysical Research: Solid Earth, 125, e2018JB017120.
    https://doi.org/10.1029/2018JB017120

Key paper-fidelity items implemented in this version:

1. b = 0 for the declustering/calibration nearest-neighbor layer
   (paper Section 4.2.1).
2. Optional separate b = 1 layer kept only for sequence parent display.
3. eta0 selected from the b = 0 nearest-neighbor proximity histogram
   (paper Section 4.2.2).
4. Step 1: events with eta_i <= eta0 are excluded from the calibration pool
   so that only the non-clustered subset seeds the randomized catalogs
   (paper Eq. 5).
5. Randomized catalogs are built with:
      - spatial locations from the calibration subset (preserved),
      - uniform random times over the catalog time span,
      - magnitudes from the calibration subset (untouched, since with b = 0
        magnitudes do not enter the proximity).
6. Step 3 (corrected): alpha_i is the per-event difference between the real
   log-proximity and the mean log-proximity of the same real event i computed
   *against each randomized catalog* (Eq. 7):

       alpha_i = log10(eta_i) - mean_k[ log10(kappa_{k,i}) ]

   This is the cross-catalog proximity (analog of MATLAB bp_2cat_add_1.m),
   not a spatial-pool average.
7. Step 4: random thinning (Eq. 8 and Eq. 9):

       P_back,i = min(1, alpha_i * A0)             with alpha0 = log10(A0)
       background_i  if  log10(alpha_i) + alpha0 > log10(U_i)

   Implemented in log-space for numerical stability:

       background_i  if  10^(log10_alpha_i + alpha0) > U_i

8. Step 4 uncertainty: the stochastic thinning is repeated for
   N_DECLUSTERING_REALIZATIONS independent realizations (paper uses 10,000;
   we follow that here). The "primary" labels for downstream display use
   realization 0; the per-event background frequency across all realizations
   is also reported.

9. Sequence-labeling layer (Step 4 of this script, Section 5 below) is
   intentionally a project-specific post-process for QuakeStrike PH and is NOT
   part of pure Zaliapin-Ben-Zion declustering.

Items addressed in v2 relative to v1:
- alpha_i is now per-event cross-catalog (was spatial-K pool average).
- D_FRACTAL is 2.5 (paper midrange recommendation for hypocenters).
- N_DECLUSTERING_REALIZATIONS is 10,000 (paper standard).
- N_RANDOM_CATALOGS is 50 (laptop-friendly; paper code description suggests
  ~100 minimum, this is acceptable for a first pass on limited hardware).
- The commented-out Step-1 cluster forcing has been removed.
- Events without a valid alpha_i are flagged (zb_unclassified = True) and
  excluded from background labeling rather than silently called background.
- Magnitude permutation in randomized catalogs is skipped (b = 0 makes it a
  no-op anyway).
- MAX_LOOKBACK_DAYS remains None to match paper convention (lag = Inf).
"""

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from zaliapin_utils import (
    compute_nearest_neighbor_log_eta,
    estimate_log_eta_threshold,
    gardner_knopoff_radius_km,
    haversine_km,
    hypocentral_distance_km,
    parse_phivolcs_datetime,
)


# ============================================================
# CONFIG
# ============================================================

INPUT_CSV = "phivolcs_earthquake_1907_2026_combined.csv"
OUTPUT_CSV = "phivolcs_labeled_zaliapin_ben_zion_sequences.csv"

DATE_COL = "Date-Time"
LAT_COL = "Latitude"
LON_COL = "Longitude"
DEPTH_COL = "Depth"
MAG_COL = "Magnitude"

# Declustering layer (paper Section 4.2.1: w = 0).
DECLUSTER_B_VALUE = 0.0

# Practical sequence-parent layer: magnitude-weighted parent assignment is
# useful for downstream sequence display. Not part of declustering.
SEQUENCE_PARENT_B_VALUE = 1.0

# Effective spatial/fractal dimension of hypocenters (paper midrange = 2.5
# for hypocenters; with USE_DEPTH = True we are in the 3D hypocenter regime).
D_FRACTAL = 2.5

# Avoid log(0) when two records have identical time or location.
# These match the MATLAB bp_add_1.m defaults (tmin = 1 s, dmin = 1 m).
MIN_TIME_DAYS = 1.0 / (24 * 60 * 60)  # 1 second in days
MIN_DISTANCE_KM = 0.001               # 1 meter in km

# 3D hypocentral distance using depth.
USE_DEPTH = True

# Paper convention: lag = Inf (no lookback restriction).
MAX_LOOKBACK_DAYS = None

# Status output for long catalog runs.
PROGRESS_INTERVAL = 5000

# Magnitude threshold for public-facing "mainshock candidate" flag.
MAINSHOCK_DISPLAY_MAG_THRESHOLD = 4.5

# Whether child events must also stay inside the original sequence root radius.
REQUIRE_WITHIN_ROOT_RADIUS = False


# ============================================================
# ZALIAPIN-BEN-ZION RANDOM-THINNING CONFIG
# ============================================================

# Number of randomized catalogs M used in Step 2 / cross-catalog proximities.
# Paper code description suggests Nboot = 100 as a reasonable minimum. Here
# we use 50 to fit a laptop budget; this is the parameter most worth raising
# later if compute allows.
N_RANDOM_CATALOGS = 50

# Minimum required count of valid cross-catalog proximities per event before
# alpha_i is considered well-estimated. Events failing this floor are flagged
# zb_unclassified and held out of the background/triggered decision.
MIN_CROSS_CAT_SAMPLES = max(5, N_RANDOM_CATALOGS // 4)

# Zaliapin-Ben-Zion alpha0 cluster threshold (paper Section 4.2.3 recommends
# searching alpha0 in roughly [-1, 1], starting near zero).
ALPHA0 = 0.0

# eta0 selected manually from the b = 0 nearest-neighbor proximity histogram.
# 0.5 is the user-selected value from the plotted histogram for this catalog.
MANUAL_ETA0 = 0.5

# Fallback only. Manual histogram-based selection is preferred.
AUTO_ESTIMATE_ETA0_WITH_GMM = False

# Number of independent stochastic thinning realizations used to summarize
# uncertainty in the per-event background label. The paper uses 10,000.
N_DECLUSTERING_REALIZATIONS = 10_000

RANDOM_SEED = 42

# Chunk size for batched BallTree queries (used in the cross-catalog NN search).
BALLTREE_QUERY_CHUNK = 5000

# Number of spatial candidates pulled per real event when searching a
# randomized catalog for the cross-catalog nearest neighbor. This is a
# computational shortlist, not a parameter of the algorithm. Larger values
# approach an exhaustive search; very small values risk missing the true
# minimum. 200 is comfortably more than enough for typical regional catalogs.
CROSS_CAT_SPATIAL_CANDIDATES = 200


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def _finite_array(values):
    """Return a float numpy array containing only finite values."""
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def _haversine_km_vectorized(lat1, lon1, lat2, lon2):
    """Vectorized great-circle distance in kilometers."""
    lat1_rad = np.radians(float(lat1))
    lon1_rad = np.radians(float(lon1))
    lat2_rad = np.radians(np.asarray(lat2, dtype=float))
    lon2_rad = np.radians(np.asarray(lon2, dtype=float))

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(a)))

    return 6371.0088 * c


def _distance_km_vectorized(
    lat1,
    lon1,
    depth1,
    lat2,
    lon2,
    depth2,
    use_depth,
):
    """Vectorized epicentral or hypocentral distance in kilometers."""
    surface_km = _haversine_km_vectorized(lat1, lon1, lat2, lon2)

    if not use_depth:
        return surface_km

    dz = np.asarray(depth2, dtype=float) - float(depth1)
    return np.sqrt(surface_km ** 2 + dz ** 2)


def cross_catalog_log_eta(
    real_times_ns,
    real_latitudes,
    real_longitudes,
    real_depths,
    rand_times_ns,
    rand_latitudes,
    rand_longitudes,
    rand_depths,
    rand_magnitudes,
    day_ns,
    d_fractal,
    b_value,
    use_depth,
    min_time_days,
    min_distance_km,
    spatial_candidates=None,
    query_chunk=None,
):
    """
    Cross-catalog nearest-neighbor log-proximity.

    This is the Python analog of MATLAB bp_2cat_add_1.m:
    for each real event i, find the nearest previous event from the randomized
    catalog only.

    The proximity is computed as:

        log10(dt_years) + d * log10(distance_km) - b * parent_magnitude

    Time is converted to years to match bp_add_1.m / bp_2cat_add_1.m.
    """
    real_times_ns = np.asarray(real_times_ns, dtype=np.int64)
    rand_times_ns = np.asarray(rand_times_ns, dtype=np.int64)

    real_lat = np.asarray(real_latitudes, dtype=float)
    real_lon = np.asarray(real_longitudes, dtype=float)
    real_dep = np.asarray(real_depths, dtype=float)

    rand_lat = np.asarray(rand_latitudes, dtype=float)
    rand_lon = np.asarray(rand_longitudes, dtype=float)
    rand_dep = np.asarray(rand_depths, dtype=float)
    rand_mag = np.asarray(rand_magnitudes, dtype=float)

    n_real = len(real_times_ns)
    n_rand = len(rand_times_ns)

    log_eta_cross = np.full(n_real, np.nan)

    if n_real == 0 or n_rand == 0:
        return log_eta_cross

    days_per_year = 365.25
    presearch_count = 50
    q = 3.36

    lon_scale = float(np.cos(np.radians(np.nanmean(rand_lat))))
    if (not np.isfinite(lon_scale)) or abs(lon_scale) < 1e-9:
        lon_scale = 1e-9

    for i in range(n_real):
        t_real_ns = int(real_times_ns[i])

        # ind = max(find(time0 < time(i))) in bp_2cat_add_1.m
        ind_exclusive = int(np.searchsorted(rand_times_ns, t_real_ns, side="left"))

        if ind_exclusive <= 0:
            continue

        ind_last = ind_exclusive - 1

        # K = max(1, ind-50):ind in MATLAB, converted to zero-based Python.
        k_start = max(0, ind_last - presearch_count)
        k = np.arange(k_start, ind_last + 1, dtype=int)

        # Remove exact same hypocentral location, as in MATLAB:
        # ~(Lon0 == Lon & Lat0 == Lat & depth0 == depth)
        same_k = (
            (rand_lon[k] == real_lon[i])
            & (rand_lat[k] == real_lat[i])
            & (rand_dep[k] == real_dep[i])
        )
        k = k[~same_k]

        if k.size == 0:
            continue

        d_km = _distance_km_vectorized(
            real_lat[i],
            real_lon[i],
            real_dep[i],
            rand_lat[k],
            rand_lon[k],
            rand_dep[k],
            use_depth,
        )
        d_km = np.maximum(d_km, min_distance_km)

        dt_days = (t_real_ns - rand_times_ns[k]) / day_ns
        dt_days = np.maximum(dt_days, min_time_days)
        dt_years = dt_days / days_per_year

        eta_k = (
            np.log10(dt_years)
            + d_fractal * np.log10(d_km)
            - b_value * rand_mag[k]
        )

        finite_k = np.isfinite(eta_k)
        if not np.any(finite_k):
            continue

        nc0 = float(np.nanmin(eta_k[finite_k]))

        # Same window logic as bp_2cat_add_1.m:
        # dt0 = 10.^((nc0-q)/2)
        # d0  = 10.^((nc0+q)/2/df)
        dt0_years = 10.0 ** ((nc0 - q) / 2.0)
        d0_km = 10.0 ** ((nc0 + q) / (2.0 * d_fractal))

        all_idx = np.arange(0, ind_last + 1, dtype=int)

        dt_years_all = ((t_real_ns - rand_times_ns[all_idx]) / day_ns) / days_per_year
        time_window = dt_years_all <= dt0_years

        if use_depth:
            spatial_window = (
                (
                    np.abs(rand_lon[all_idx] - real_lon[i])
                    <= 2.0 * d0_km / 111.0 / abs(lon_scale)
                )
                & (
                    np.abs(rand_lat[all_idx] - real_lat[i])
                    <= 2.0 * d0_km / 111.0
                )
                & (
                    np.abs(rand_dep[all_idx] - real_dep[i])
                    <= 2.0 * d0_km
                )
            )
        else:
            spatial_window = (
                (
                    np.abs(rand_lon[all_idx] - real_lon[i])
                    <= 2.0 * d0_km / 111.0 / abs(lon_scale)
                )
                & (
                    np.abs(rand_lat[all_idx] - real_lat[i])
                    <= 2.0 * d0_km / 111.0
                )
            )

        same_all = (
            (rand_lon[all_idx] == real_lon[i])
            & (rand_lat[all_idx] == real_lat[i])
            & (rand_dep[all_idx] == real_dep[i])
        )

        candidate_idx = all_idx[(time_window | spatial_window) & ~same_all]

        if candidate_idx.size == 0:
            candidate_idx = k

        d_candidates = _distance_km_vectorized(
            real_lat[i],
            real_lon[i],
            real_dep[i],
            rand_lat[candidate_idx],
            rand_lon[candidate_idx],
            rand_dep[candidate_idx],
            use_depth,
        )
        d_candidates = np.maximum(d_candidates, min_distance_km)

        dt_days_candidates = (t_real_ns - rand_times_ns[candidate_idx]) / day_ns
        dt_days_candidates = np.maximum(dt_days_candidates, min_time_days)
        dt_years_candidates = dt_days_candidates / days_per_year

        eta_candidates = (
            np.log10(dt_years_candidates)
            + d_fractal * np.log10(d_candidates)
            - b_value * rand_mag[candidate_idx]
        )

        finite_candidates = np.isfinite(eta_candidates)
        if not np.any(finite_candidates):
            continue

        log_eta_cross[i] = float(np.nanmin(eta_candidates[finite_candidates]))

    return log_eta_cross


def apply_zaliapin_ben_zion_random_thinning(alpha_i, alpha0, valid_mask, rng):
    """
    Apply Zaliapin-Ben-Zion random thinning (paper Eq. 8 and Eq. 9).

    For each event i with a valid alpha_i:

        P_back,i = min(1, 10^(alpha_i + alpha0))
        is_background_i  iff  10^(alpha_i + alpha0) > U_i,  U_i ~ Uniform[0,1]

    Events outside `valid_mask` are returned with NaN background_probability
    and False is_background; the caller is responsible for flagging them
    (they are NOT silently called background here).

    Parameters
    ----------
    alpha_i : np.ndarray
        Per-event log10(alpha_i) values (i.e., the quantity that the paper
        calls log10(alpha_i); see Eq. 7).
    alpha0 : float
        Logarithmic cluster threshold = log10(A0). Paper Section 4.2.3.
    valid_mask : np.ndarray of bool
        True for events that have a well-estimated alpha_i.
    rng : np.random.Generator

    Returns
    -------
    is_background : np.ndarray of bool
    background_probability : np.ndarray of float (NaN for invalid events)
    """
    n = len(alpha_i)
    is_background = np.zeros(n, dtype=bool)
    background_probability = np.full(n, np.nan)

    if not np.any(valid_mask):
        return is_background, background_probability

    log_p_unclipped = alpha_i[valid_mask] + alpha0
    p_back = np.minimum(1.0, np.power(10.0, log_p_unclipped))
    p_back = np.maximum(0.0, p_back)
    background_probability[valid_mask] = p_back

    u = rng.random(int(valid_mask.sum()))
    is_background[valid_mask] = p_back > u

    return is_background, background_probability


# ============================================================
# STEP 1: LOAD AND CLEAN
# ============================================================


df = pd.read_csv(INPUT_CSV, low_memory=False)
raw_row_count = len(df)

required_cols = [DATE_COL, LAT_COL, LON_COL, DEPTH_COL, MAG_COL]
missing = [col for col in required_cols if col not in df.columns]

if missing:
    raise ValueError(f"Missing required columns: {missing}")

df["event_time"] = df[DATE_COL].apply(parse_phivolcs_datetime)
df["latitude"] = pd.to_numeric(df[LAT_COL], errors="coerce")
df["longitude"] = pd.to_numeric(df[LON_COL], errors="coerce")
df["depth_km"] = pd.to_numeric(df[DEPTH_COL], errors="coerce")
df["magnitude"] = pd.to_numeric(df[MAG_COL], errors="coerce")

valid_input = df[
    ["event_time", "latitude", "longitude", "depth_km", "magnitude"]
].notna().all(axis=1)
dropped_row_count = int((~valid_input).sum())

df = df.loc[valid_input].copy()
df = df.sort_values("event_time").reset_index(drop=True)
df["event_id"] = np.arange(len(df))

print(f"Loaded {raw_row_count:,} rows from {INPUT_CSV}")
print(f"Using {len(df):,} valid rows; dropped {dropped_row_count:,}")
print(f"MAX_LOOKBACK_DAYS: {MAX_LOOKBACK_DAYS}")
print(f"N_RANDOM_CATALOGS: {N_RANDOM_CATALOGS}")
print(f"N_DECLUSTERING_REALIZATIONS: {N_DECLUSTERING_REALIZATIONS}")
print(f"DECLUSTER_B_VALUE: {DECLUSTER_B_VALUE}")
print(f"SEQUENCE_PARENT_B_VALUE: {SEQUENCE_PARENT_B_VALUE}")
print(f"D_FRACTAL: {D_FRACTAL}")
print(f"ALPHA0: {ALPHA0}")
print(f"MANUAL_ETA0: {MANUAL_ETA0}")


# ============================================================
# STEP 2: COMPUTE NEAREST-NEIGHBOR VALUES (REAL CATALOG)
# ============================================================


event_times_ns = df["event_time"].to_numpy(dtype="datetime64[ns]").astype("int64")
latitudes = df["latitude"].to_numpy()
longitudes = df["longitude"].to_numpy()
depths = df["depth_km"].to_numpy()
magnitudes = df["magnitude"].to_numpy()
event_ids = df["event_id"].to_numpy()

day_ns = 24 * 60 * 60 * 1_000_000_000

# Practical sequence-parent nearest-neighbor link (b = 1, magnitude-weighted).
# Used only for sequence association display, NOT for declustering.
(
    parent_ids,
    parent_log_etas,
    parent_distances,
    parent_dt_days,
) = compute_nearest_neighbor_log_eta(
    event_times_ns=event_times_ns,
    latitudes=latitudes,
    longitudes=longitudes,
    depths=depths,
    magnitudes=magnitudes,
    event_ids=event_ids,
    day_ns=day_ns,
    max_lookback_days=MAX_LOOKBACK_DAYS,
    use_depth=USE_DEPTH,
    d_fractal=D_FRACTAL,
    b_value=SEQUENCE_PARENT_B_VALUE,
    min_time_days=MIN_TIME_DAYS,
    min_distance_km=MIN_DISTANCE_KM,
    progress_interval=PROGRESS_INTERVAL,
)

df["nn_parent_event_id"] = parent_ids
df["nn_log_eta"] = parent_log_etas
df["nn_distance_km"] = parent_distances
df["nn_dt_days"] = parent_dt_days

# Declustering nearest-neighbor values (b = 0). This is the eta_i used
# throughout the Zaliapin-Ben-Zion algorithm.
(
    decluster_parent_ids,
    decluster_log_etas,
    decluster_distances,
    decluster_dt_days,
) = compute_nearest_neighbor_log_eta(
    event_times_ns=event_times_ns,
    latitudes=latitudes,
    longitudes=longitudes,
    depths=depths,
    magnitudes=magnitudes,
    event_ids=event_ids,
    day_ns=day_ns,
    max_lookback_days=MAX_LOOKBACK_DAYS,
    use_depth=USE_DEPTH,
    d_fractal=D_FRACTAL,
    b_value=DECLUSTER_B_VALUE,
    min_time_days=MIN_TIME_DAYS,
    min_distance_km=MIN_DISTANCE_KM,
    progress_interval=PROGRESS_INTERVAL,
)

df["decluster_parent_event_id"] = decluster_parent_ids
df["decluster_log_eta"] = decluster_log_etas
df["decluster_distance_km"] = decluster_distances
df["decluster_dt_days"] = decluster_dt_days

# Backward-compatible name for the b = 0 proximity used in eta0 selection.
df["nn_log_eta_b0"] = df["decluster_log_eta"]

# Diagnostic only: agreement between b = 1 and b = 0 nearest-neighbor parents.
df["parent_layers_agree"] = (
    df["nn_parent_event_id"] == df["decluster_parent_event_id"]
)
both_missing = df["nn_parent_event_id"].isna() & df["decluster_parent_event_id"].isna()
df.loc[both_missing, "parent_layers_agree"] = True

agreement_rate = df["parent_layers_agree"].mean()
print(f"Parent layer agreement rate (b=1 vs b=0): {agreement_rate:.1%}")


# ============================================================
# STEP 3: ZALIAPIN-BEN-ZION RANDOMIZED-BACKGROUND CALIBRATION
# Cross-catalog per-event alpha_i (paper Eq. 7).
# ============================================================


print("Running Zaliapin-Ben-Zion randomized-background calibration...")
rng = np.random.default_rng(RANDOM_SEED)

# eta0 selection.
if MANUAL_ETA0 is not None:
    eta0 = float(MANUAL_ETA0)
    eta0_info = {"method": "manual_from_b0_histogram"}
elif AUTO_ESTIMATE_ETA0_WITH_GMM:
    eta0, eta0_info = estimate_log_eta_threshold(df["nn_log_eta_b0"].dropna())
    eta0 = float(eta0)
    eta0_info["method"] = "auto_gmm_on_b0_log_eta"
else:
    raise ValueError(
        "No eta0 selection method enabled. Set MANUAL_ETA0 or "
        "AUTO_ESTIMATE_ETA0_WITH_GMM = True."
    )

print(f"eta0: {eta0}")
print(f"eta0 info: {eta0_info}")

# Step 1 of the paper: identify the most clustered events by eta_i <= eta0.
# These are excluded from the calibration pool that seeds randomized catalogs.
decluster_log_eta_arr = df["decluster_log_eta"].to_numpy(dtype=float)

strongly_clustered_b0 = (
    np.isfinite(decluster_log_eta_arr) & (decluster_log_eta_arr <= eta0)
)
df["zb_strong_clustered_b0"] = strongly_clustered_b0

# Calibration pool: events with eta_i > eta0.
calibration_mask = (
    np.isfinite(decluster_log_eta_arr) & (decluster_log_eta_arr > eta0)
)

calib_times_ns = event_times_ns[calibration_mask]
calib_latitudes = latitudes[calibration_mask]
calib_longitudes = longitudes[calibration_mask]
calib_depths = depths[calibration_mask]
calib_magnitudes = magnitudes[calibration_mask]

n_calib = len(calib_times_ns)
if n_calib < 2:
    raise ValueError(
        "Not enough calibration events after eta0 strong-cluster removal. "
        "Check MANUAL_ETA0."
    )

print(f"Calibration events used for randomized background: {n_calib:,}/{len(df):,}")

catalog_start_ns = int(event_times_ns.min())
catalog_end_ns = int(event_times_ns.max())
if catalog_end_ns <= catalog_start_ns:
    raise ValueError("Catalog time span is invalid; cannot generate randomized times.")

# Real catalog log_eta (b = 0) per event.
real_log_eta_b0 = df["decluster_log_eta"].to_numpy(dtype=float)

# Per-event accumulators for cross-catalog log-proximities.
# Following bp_thinning_fast.m: Lb (sum of log_eta), Nboot_actual (count).
n_events = len(df)
sum_log_kappa = np.zeros(n_events, dtype=float)
count_log_kappa = np.zeros(n_events, dtype=int)

for run_idx in range(N_RANDOM_CATALOGS):
    print(f"Randomized catalog {run_idx + 1}/{N_RANDOM_CATALOGS}")

    # Build randomized catalog C_k from the calibration subset:
    #   - spatial locations preserved from calibration events
    #   - times drawn uniformly across the catalog time span
    #   - magnitudes preserved (with b = 0 they don't enter the proximity;
    #     no permutation is applied since it would be a no-op)
    rand_times_ns = rng.integers(
        low=catalog_start_ns,
        high=catalog_end_ns,
        size=n_calib,
        endpoint=False,
    )

    # Original bp_thinning_fast.m logic:
    # - timeb is sorted uniform time
    # - locations are independently permuted from the calibration subset
    # - magnitudes are independently permuted
    rand_times_ns_sorted = np.sort(rand_times_ns)

    location_perm = rng.permutation(n_calib)
    magnitude_perm = rng.permutation(n_calib)

    rand_lat_sorted = calib_latitudes[location_perm]
    rand_lon_sorted = calib_longitudes[location_perm]
    rand_depth_sorted = calib_depths[location_perm]
    rand_mag_sorted = calib_magnitudes[magnitude_perm]

    # Cross-catalog proximities: each real event i against this randomized C_k.
    log_kappa_k = cross_catalog_log_eta(
        real_times_ns=event_times_ns,
        real_latitudes=latitudes,
        real_longitudes=longitudes,
        real_depths=depths,
        rand_times_ns=rand_times_ns_sorted,
        rand_latitudes=rand_lat_sorted,
        rand_longitudes=rand_lon_sorted,
        rand_depths=rand_depth_sorted,
        rand_magnitudes=rand_mag_sorted,
        day_ns=day_ns,
        d_fractal=D_FRACTAL,
        b_value=DECLUSTER_B_VALUE,
        use_depth=USE_DEPTH,
        min_time_days=MIN_TIME_DAYS,
        min_distance_km=MIN_DISTANCE_KM,
        spatial_candidates=CROSS_CAT_SPATIAL_CANDIDATES,
        query_chunk=BALLTREE_QUERY_CHUNK,
    )

    finite_mask = np.isfinite(log_kappa_k)
    sum_log_kappa[finite_mask] += log_kappa_k[finite_mask]
    count_log_kappa[finite_mask] += 1

# Per-event mean cross-catalog log-proximity (the mean[log10(k_i)] in Eq. 7).
mean_log_kappa = np.full(n_events, np.nan)
have_samples = count_log_kappa > 0
mean_log_kappa[have_samples] = sum_log_kappa[have_samples] / count_log_kappa[have_samples]

# Paper Eq. 7: alpha_i in log10 form is log10(eta_i) - mean_k log10(kappa_{k,i}).
# real_log_eta_b0 already IS log10(eta_i) (the bp_add_1 output is log-proximity).
log_alpha_i = real_log_eta_b0 - mean_log_kappa

# Validity: alpha_i must come from a sufficient number of randomized realizations
# AND the real event must itself have a finite real log-proximity.
valid_alpha_mask = (
    np.isfinite(real_log_eta_b0)
    & np.isfinite(mean_log_kappa)
    & (count_log_kappa >= MIN_CROSS_CAT_SAMPLES)
)

# Diagnostic counts.
n_valid_alpha = int(valid_alpha_mask.sum())
n_invalid_alpha = int(n_events - n_valid_alpha)
print(
    f"alpha_i estimated for {n_valid_alpha:,}/{n_events:,} events "
    f"(min cross-catalog samples required: {MIN_CROSS_CAT_SAMPLES})"
)

df["zb_alpha_i"] = log_alpha_i
df["zb_cross_cat_samples"] = count_log_kappa
df["zb_mean_log_kappa"] = mean_log_kappa
df["zb_alpha_valid"] = valid_alpha_mask


# ============================================================
# STEP 4 (paper): RANDOM THINNING WITH N_DECLUSTERING_REALIZATIONS
# ============================================================


# Events with no declustering parent (typically the first event in the catalog,
# or events for which no earlier event exists within the search domain) cannot
# be classified by nearest-neighbor thinning. They are flagged unclassified
# rather than silently labeled background.
decluster_no_parent_mask = df["decluster_parent_event_id"].isna().to_numpy()

# Master "unclassified" mask: alpha_i not estimable, OR no declustering parent.
zb_unclassified = (~valid_alpha_mask) | decluster_no_parent_mask
n_unclassified = int(zb_unclassified.sum())
print(
    f"Unclassified events (excluded from background labeling): "
    f"{n_unclassified:,}/{n_events:,}"
)

# Effective valid mask used by the thinning step.
thinning_valid_mask = valid_alpha_mask & ~decluster_no_parent_mask

# Realizations.
background_realization_count = np.zeros(n_events, dtype=np.int64)
primary_background = None
primary_background_probability = None

# Memory note: storing all 10,000 realizations as a (10_000, n_events) bool
# matrix is fine for n_events up to a few hundred thousand (e.g., 200k events
# x 10_000 reals x 1 byte = ~2 GB). For very large catalogs, the running
# count below avoids the full matrix.

print(f"Running {N_DECLUSTERING_REALIZATIONS:,} thinning realizations...")
for realization_idx in range(N_DECLUSTERING_REALIZATIONS):
    realization_rng = np.random.default_rng(RANDOM_SEED + 10_000 + realization_idx)

    is_background, background_probability = apply_zaliapin_ben_zion_random_thinning(
        alpha_i=log_alpha_i,
        alpha0=ALPHA0,
        valid_mask=thinning_valid_mask,
        rng=realization_rng,
    )

    background_realization_count += is_background.astype(np.int64)

    if realization_idx == 0:
        primary_background = is_background.copy()
        primary_background_probability = background_probability.copy()

    if (
        N_DECLUSTERING_REALIZATIONS >= 100
        and (realization_idx + 1) % max(1, N_DECLUSTERING_REALIZATIONS // 10) == 0
    ):
        done = realization_idx + 1
        pct = 100.0 * done / N_DECLUSTERING_REALIZATIONS
        print(f"  thinning realizations: {done:,}/{N_DECLUSTERING_REALIZATIONS:,} ({pct:.0f}%)")

# Per-event background frequency across all realizations.
background_frequency = np.full(n_events, np.nan)
background_frequency[thinning_valid_mask] = (
    background_realization_count[thinning_valid_mask] / N_DECLUSTERING_REALIZATIONS
)

df["zb_background_frequency"] = background_frequency
df["zb_background_probability"] = primary_background_probability
df["zb_background_realization"] = primary_background
df["zb_unclassified"] = zb_unclassified

# zaliapin_triggered: True only if classified (i.e., had a usable alpha_i and a
# declustering parent) AND the primary thinning realization marked it as
# clustered. Unclassified events are NOT silently labeled triggered or
# background; downstream code should branch on zb_unclassified.
df["zaliapin_triggered"] = (~zb_unclassified) & (~primary_background)

df["threshold_method"] = "zaliapin_ben_zion_random_thinning_per_event_alpha"
df["zb_eta0"] = eta0
df["zb_alpha0"] = ALPHA0


# ============================================================
# STEP 5 (project-specific): PRACTICAL MAINSHOCK-AFTERSHOCK SEQUENCES
# This is NOT part of pure Zaliapin-Ben-Zion declustering; it is a
# downstream sequence-association layer for QuakeStrike PH usability.
# ============================================================


event_id_arr = df["event_id"].to_numpy()
mag_arr = df["magnitude"].to_numpy()
lat_arr = df["latitude"].to_numpy()
lon_arr = df["longitude"].to_numpy()
depth_arr = df["depth_km"].to_numpy()
triggered_arr = df["zaliapin_triggered"].to_numpy()
unclassified_arr = df["zb_unclassified"].to_numpy()
nn_parent_arr = df["nn_parent_event_id"].to_numpy()
nn_distance_arr = df["nn_distance_km"].to_numpy()

sequence_id = {}
sequence_root_event_id = {}
sequence_root_magnitude = {}

labels = []
final_parent_ids = []
sequence_ids = []
root_ids = []
generation_numbers = []
spatial_ok_values = []
radius_values = []
secondary_trigger_values = []

n_rows = len(df)

for j in range(n_rows):
    event_id = int(event_id_arr[j])
    mag = float(mag_arr[j])

    is_unclassified = bool(unclassified_arr[j])
    is_triggered = bool(triggered_arr[j])
    nn_parent_raw = nn_parent_arr[j]
    nn_parent_is_nan = not np.isfinite(nn_parent_raw)

    # Unclassified or untriggered events start their own sequence.
    if is_unclassified or (not is_triggered) or nn_parent_is_nan:
        sequence_id[event_id] = event_id
        sequence_root_event_id[event_id] = event_id
        sequence_root_magnitude[event_id] = mag

        if is_unclassified:
            label = "unclassified"
        elif mag >= MAINSHOCK_DISPLAY_MAG_THRESHOLD:
            label = "mainshock_candidate"
        else:
            label = "background_event"

        labels.append(label)
        final_parent_ids.append(np.nan)
        sequence_ids.append(event_id)
        root_ids.append(event_id)
        generation_numbers.append(0)
        spatial_ok_values.append(True)
        radius_values.append(np.nan)
        secondary_trigger_values.append(False)
        continue

    nn_parent = int(nn_parent_raw)

    if nn_parent not in sequence_id:
        sequence_id[event_id] = event_id
        sequence_root_event_id[event_id] = event_id
        sequence_root_magnitude[event_id] = mag

        labels.append("background_event")
        final_parent_ids.append(np.nan)
        sequence_ids.append(event_id)
        root_ids.append(event_id)
        generation_numbers.append(0)
        spatial_ok_values.append(False)
        radius_values.append(np.nan)
        secondary_trigger_values.append(False)
        continue

    parent_mag = float(mag_arr[nn_parent])
    parent_radius_km = gardner_knopoff_radius_km(parent_mag)
    child_parent_distance = float(nn_distance_arr[j])
    spatial_ok = child_parent_distance <= parent_radius_km

    parent_sequence = sequence_id[nn_parent]
    root_event_id = sequence_root_event_id[parent_sequence]
    root_mag = sequence_root_magnitude[parent_sequence]

    if REQUIRE_WITHIN_ROOT_RADIUS:
        root_radius_km = gardner_knopoff_radius_km(float(mag_arr[root_event_id]))

        if USE_DEPTH:
            distance_to_root = hypocentral_distance_km(
                lat_arr[root_event_id],
                lon_arr[root_event_id],
                depth_arr[root_event_id],
                lat_arr[j],
                lon_arr[j],
                depth_arr[j],
            )
        else:
            distance_to_root = haversine_km(
                lat_arr[root_event_id],
                lon_arr[root_event_id],
                lat_arr[j],
                lon_arr[j],
            )

        spatial_ok = spatial_ok and (distance_to_root <= root_radius_km)

    # Practical magnitude hierarchy: a later equal-or-larger event becomes a
    # new mainshock root for display purposes.
    if (not spatial_ok) or (mag >= root_mag):
        sequence_id[event_id] = event_id
        sequence_root_event_id[event_id] = event_id
        sequence_root_magnitude[event_id] = mag

        label = "new_larger_mainshock" if mag >= root_mag else "background_event"

        labels.append(label)
        final_parent_ids.append(np.nan)
        sequence_ids.append(event_id)
        root_ids.append(event_id)
        generation_numbers.append(0)
        spatial_ok_values.append(spatial_ok)
        radius_values.append(parent_radius_km)
        secondary_trigger_values.append(False)
        continue

    sequence_id[event_id] = parent_sequence
    sequence_root_event_id[parent_sequence] = root_event_id
    sequence_root_magnitude[parent_sequence] = root_mag

    parent_generation = (
        generation_numbers[nn_parent]
        if nn_parent < len(generation_numbers)
        else 0
    )
    generation = int(parent_generation) + 1

    is_secondary = nn_parent != root_event_id

    labels.append("secondary_aftershock" if is_secondary else "aftershock")
    final_parent_ids.append(nn_parent)
    sequence_ids.append(parent_sequence)
    root_ids.append(root_event_id)
    generation_numbers.append(generation)
    spatial_ok_values.append(spatial_ok)
    radius_values.append(parent_radius_km)
    secondary_trigger_values.append(is_secondary)


df["sequence_label"] = labels
df["assigned_parent_event_id"] = final_parent_ids
df["sequence_id"] = sequence_ids
df["sequence_mainshock_event_id"] = root_ids
df["sequence_generation"] = generation_numbers
df["within_parent_spatial_influence"] = spatial_ok_values
df["parent_influence_radius_km"] = radius_values
df["is_secondary_triggered"] = secondary_trigger_values

df["is_mainshock_sequence_root"] = df["event_id"] == df["sequence_mainshock_event_id"]
df["display_mainshock_candidate"] = (
    df["is_mainshock_sequence_root"]
    & (df["magnitude"] >= MAINSHOCK_DISPLAY_MAG_THRESHOLD)
)

sequence_sizes = df.groupby("sequence_id")["event_id"].transform("count")
df["sequence_event_count"] = sequence_sizes
df["sequence_aftershock_count"] = df["sequence_event_count"] - 1


# ============================================================
# STEP 6: SAVE AND PRINT SUMMARY
# ============================================================


df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved labeled dataset to: {OUTPUT_CSV}")
print(
    "Method: Zaliapin-Ben-Zion 2020 random thinning with per-event "
    "cross-catalog alpha_i (paper Eq. 7)."
)
print("alpha_i summary:")
print(df["zb_alpha_i"].describe())
print("Background probability summary:")
print(df["zb_background_probability"].describe())
print("Background realization counts (primary realization):")
print(df["zb_background_realization"].value_counts(dropna=False))
print("Triggered counts:")
print(df["zaliapin_triggered"].value_counts(dropna=False))
print("Unclassified counts:")
print(df["zb_unclassified"].value_counts(dropna=False))

print("\nLabel counts:")
print(df["sequence_label"].value_counts())

print("\nSample output:")
print(df[
    [
        "event_id",
        "event_time",
        "magnitude",
        "sequence_label",
        "nn_parent_event_id",
        "assigned_parent_event_id",
        "sequence_mainshock_event_id",
        "sequence_generation",
        "nn_log_eta",
        "decluster_log_eta",
        "zb_alpha_i",
        "zb_background_probability",
        "zb_background_frequency",
        "zaliapin_triggered",
        "zb_unclassified",
        "nn_distance_km",
        "within_parent_spatial_influence",
    ]
].head(20))

print(f"Parent layer agreement rate: {df['parent_layers_agree'].mean():.1%}")
