"""
QuakeStrike PH - Zaliapin-Ben-Zion nearest-neighbor declustering
with practical mainshock-aftershock sequence association labels.

This script replaces a deterministic local-quantile cutoff with a closer
Zaliapin and Ben-Zion (2020) style stochastic random-thinning workflow:

1. Compute nearest previous neighbors in space-time-magnitude domain.
2. Compute a b=0 nearest-neighbor proximity used for the strong-cluster
   pre-removal / calibration step.
3. Build randomized-reshuffled catalogs to estimate a local background
   reference distribution.
4. Convert each real event into a normalized proximity alpha_i by comparing
   its log_eta to the local randomized-background distribution.
5. Apply random thinning using p_background = min(1, 10^(alpha_i + alpha0)).
6. Keep the original practical post-processing section that assigns
   public-facing mainshock / aftershock / secondary-aftershock labels using
   Gardner-Knopoff spatial influence and magnitude hierarchy rules.

Important note:
- The declustering part is intended to follow the Zaliapin-Ben-Zion random
  thinning logic more closely than a deterministic quantile cutoff.
- The sequence-labeling part is intentionally a practical capstone layer and
  should be described separately from the pure declustering algorithm.

PERFORMANCE OPTIMIZATIONS APPLIED (algorithm unchanged):
- Step 4 sequence-labeling loop now uses positional NumPy access instead of
  `df.loc[df["event_id"] == nn_parent].iloc[0]` and `df.iloc[j]`. Because
  event_id == row position after sort+reset_index, integer indexing is exact.
- BallTree queries in compute_local_alpha_from_randomized_background are
  batched in chunks instead of one event at a time.
- Repeated `df["nn_parent_event_id"].isna()` mask computed once and reused.
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

# Zaliapin/Baiesi-Paczuski nearest-neighbor parameters.
# b_value should ideally be estimated from the Philippine catalog after
# checking magnitude completeness. b=1.0 is a common working default.
B_VALUE = 1.0

# Effective spatial/fractal dimension of hypocenters/epicenters.
# If using epicenters only, the original documentation says depths may be set
# to zero; here USE_DEPTH controls whether hypocentral distance is used.
D_FRACTAL = 1.6

# Avoid log(0) when two records have identical time or location.
MIN_TIME_DAYS = 1.0 / (24 * 60)   # 1 minute
MIN_DISTANCE_KM = 0.1             # 100 meters

# If True, use 3D hypocentral distance using depth.
# If False, use surface epicentral distance only.
USE_DEPTH = True

# For closest agreement with the original nearest-neighbor search, use None.
# A finite value is only a computational safety guard and should be tested
# with sensitivity analysis.
MAX_LOOKBACK_DAYS = None

# Status output for long catalog runs.
PROGRESS_INTERVAL = 5000

# Magnitude threshold for public-facing "mainshock candidate" flag.
# Do not use this to ignore smaller events entirely.
MAINSHOCK_DISPLAY_MAG_THRESHOLD = 4.5

# Whether child events must also stay inside the original sequence root radius.
# False allows secondary triggering and is more compatible with earthquake
# cascade behavior.
REQUIRE_WITHIN_ROOT_RADIUS = False


# ============================================================
# ZALIAPIN-BEN-ZION RANDOM-THINNING CONFIG
# ============================================================

# Number of randomized/reshuffled catalogs. The original documentation notes
# that Nboot=100 is reasonable. Use smaller values only for testing speed.
N_RANDOM_CATALOGS = 100

# Local neighborhood size used to estimate the space-varying background
# reference distribution from randomized catalogs.
LOCAL_K_NEIGHBORS = 300

# Minimum number of local randomized samples required before assigning alpha_i.
MIN_LOCAL_RANDOM_SAMPLES = 20

# Zaliapin-Ben-Zion alpha0 cluster threshold. The original documentation says
# useful values are usually within [-1, 1]. Larger alpha0 keeps more events as
# background; smaller alpha0 removes more events as clustered.
ALPHA0 = 0.0

# Step-1 strong-cluster threshold eta0 is estimated using b=0 nearest-neighbor
# values unless MANUAL_ETA0 is provided. The original documentation describes
# eta0 as the threshold for removing heavily clustered events and suggests
# choosing it from the histogram of nearest-neighbor proximity with b=0.
MANUAL_ETA0 = -3.0

# If True and MANUAL_ETA0 is None, estimate eta0 with the existing GMM helper.
# Inspect the histogram manually for final research runs.
AUTO_ESTIMATE_ETA0_WITH_GMM = False

# Use one stochastic thinning realization for final labels. If you want to
# quantify uncertainty, increase this and summarize background frequency.
N_DECLUSTERING_REALIZATIONS = 1

RANDOM_SEED = 42

# Chunk size for batched BallTree queries in the local-alpha calibration.
# Larger values are faster but use more memory. 5000 is a safe default.
BALLTREE_QUERY_CHUNK = 5000


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def _finite_array(values):
    """Return a float numpy array containing only finite values."""
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]



def compute_local_alpha_from_randomized_background(
    real_log_eta,
    real_latitudes,
    real_longitudes,
    random_log_eta_pool,
    random_lat_pool,
    random_lon_pool,
    local_k_neighbors,
    min_samples,
    progress_interval=None,
    query_chunk=BALLTREE_QUERY_CHUNK,
):
    """
    Estimate normalized proximity alpha_i for each event.

    For each real event, we find nearby randomized-background events in space,
    compare the real nearest-neighbor log_eta to that local randomized
    distribution, and convert its local empirical CDF percentile to
    alpha_i = log10(percentile).

    Low log_eta values are unusually clustered relative to randomized
    background cases, so they receive small percentiles and very negative
    alpha_i values. The thinning probability then follows:

        p_background = min(1, 10^(alpha_i + alpha0))

    This implements the random-thinning behavior used by the Zaliapin-Ben-Zion
    algorithm, while retaining a transparent Python implementation.

    OPTIMIZATION: BallTree.query is called on chunks of points instead of one
    point at a time. The per-event filtering and percentile computation are
    unchanged.
    """
    valid_random = np.isfinite(random_log_eta_pool)
    random_log_eta_pool = np.asarray(random_log_eta_pool, dtype=float)[valid_random]
    random_lat_pool = np.asarray(random_lat_pool, dtype=float)[valid_random]
    random_lon_pool = np.asarray(random_lon_pool, dtype=float)[valid_random]

    if len(random_log_eta_pool) == 0:
        raise ValueError("No valid randomized nearest-neighbor values were produced.")

    random_coords_rad = np.radians(np.column_stack([random_lat_pool, random_lon_pool]))
    random_tree = BallTree(random_coords_rad, metric="haversine")

    n_events = len(real_log_eta)
    alpha_i = np.full(n_events, np.nan)
    local_percentile = np.full(n_events, np.nan)
    local_median_log_eta = np.full(n_events, np.nan)
    local_sample_count = np.zeros(n_events, dtype=int)

    query_k = min(local_k_neighbors, len(random_log_eta_pool))
    eps = 1.0 / (len(random_log_eta_pool) + 1.0)

    real_log_eta = np.asarray(real_log_eta, dtype=float)
    real_latitudes = np.asarray(real_latitudes, dtype=float)
    real_longitudes = np.asarray(real_longitudes, dtype=float)

    # Process events in chunks so BallTree.query is called on a batch.
    for chunk_start in range(0, n_events, query_chunk):
        chunk_end = min(chunk_start + query_chunk, n_events)

        if progress_interval and chunk_start > 0 and chunk_start % progress_interval == 0:
            print(f"Estimated alpha_i for {chunk_start:,}/{n_events:,} events")

        chunk_coords_rad = np.radians(
            np.column_stack(
                [real_latitudes[chunk_start:chunk_end],
                 real_longitudes[chunk_start:chunk_end]]
            )
        )
        _, neighbor_idx_chunk = random_tree.query(chunk_coords_rad, k=query_k)

        for offset in range(chunk_end - chunk_start):
            j = chunk_start + offset
            current_eta = real_log_eta[j]
            if not np.isfinite(current_eta):
                continue

            local_random_log_etas = random_log_eta_pool[neighbor_idx_chunk[offset]]
            local_random_log_etas = _finite_array(local_random_log_etas)

            if len(local_random_log_etas) < min_samples:
                continue

            # Empirical local CDF under randomized-background catalogs.
            # Very clustered events have low CDF values.
            percentile = float(np.mean(local_random_log_etas <= current_eta))
            percentile = max(percentile, eps)

            local_percentile[j] = percentile
            alpha_i[j] = float(np.log10(percentile))
            local_median_log_eta[j] = float(np.median(local_random_log_etas))
            local_sample_count[j] = len(local_random_log_etas)

    return alpha_i, local_percentile, local_median_log_eta, local_sample_count



def apply_zaliapin_ben_zion_random_thinning(alpha_i, alpha0, rng):
    """
    Apply Zaliapin-Ben-Zion style random thinning.

    In the original code description, alternative declustering realizations are
    generated using:

        p = 10.^(ad0 + alpha0)
        I = p > rand(size(p))

    where I marks background events. Here alpha_i corresponds to ad0.
    """
    background_probability = np.full(len(alpha_i), np.nan)
    is_background = np.zeros(len(alpha_i), dtype=bool)

    valid = np.isfinite(alpha_i)
    background_probability[valid] = np.minimum(1.0, np.power(10.0, alpha_i[valid] + alpha0))
    background_probability[valid] = np.maximum(0.0, background_probability[valid])

    random_draws = rng.random(len(alpha_i))
    is_background[valid] = background_probability[valid] > random_draws[valid]

    # Events without a valid parent/alpha cannot be clustered by nearest-neighbor
    # thinning, so they remain background by default.
    is_background[~valid] = True

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
print(f"ALPHA0: {ALPHA0}")


# ============================================================
# STEP 2: FIND ZALIAPIN NEAREST PREVIOUS NEIGHBOR
# ============================================================


event_times_ns = df["event_time"].to_numpy(dtype="datetime64[ns]").astype("int64")
latitudes = df["latitude"].to_numpy()
longitudes = df["longitude"].to_numpy()
depths = df["depth_km"].to_numpy()
magnitudes = df["magnitude"].to_numpy()
event_ids = df["event_id"].to_numpy()

day_ns = 24 * 60 * 60 * 1_000_000_000

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
    b_value=B_VALUE,
    min_time_days=MIN_TIME_DAYS,
    min_distance_km=MIN_DISTANCE_KM,
    progress_interval=PROGRESS_INTERVAL,
)

df["nn_parent_event_id"] = parent_ids
df["nn_log_eta"] = parent_log_etas
df["nn_distance_km"] = parent_distances
df["nn_dt_days"] = parent_dt_days

# b=0 nearest-neighbor proximity for eta0 / strong-cluster handling.
(
    _parent_ids_b0,
    parent_log_etas_b0,
    _parent_distances_b0,
    _parent_dt_days_b0,
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
    b_value=0.0,
    min_time_days=MIN_TIME_DAYS,
    min_distance_km=MIN_DISTANCE_KM,
    progress_interval=PROGRESS_INTERVAL,
)

df["nn_log_eta_b0"] = parent_log_etas_b0


# ============================================================
# STEP 3: ZALIAPIN-BEN-ZION RANDOMIZED BACKGROUND CALIBRATION
# ============================================================


print("Running Zaliapin-Ben-Zion randomized-background calibration...")
rng = np.random.default_rng(RANDOM_SEED)

if MANUAL_ETA0 is not None:
    eta0 = float(MANUAL_ETA0)
    eta0_info = {"method": "manual"}
elif AUTO_ESTIMATE_ETA0_WITH_GMM:
    eta0, eta0_info = estimate_log_eta_threshold(df["nn_log_eta_b0"].dropna())
    eta0 = float(eta0)
    eta0_info["method"] = "auto_gmm_on_b0_log_eta"
else:
    eta0 = np.nan
    eta0_info = {"method": "not_used"}

print(f"eta0: {eta0}")
print(f"eta0 info: {eta0_info}")

# Strongly clustered events under b=0 are treated as clustered before local
# thinning. This follows the intent of Step 1 in the original documentation.
if np.isfinite(eta0):
    strongly_clustered_b0 = (
        df["nn_log_eta_b0"].notna()
        & (df["nn_log_eta_b0"] <= eta0)
    ).to_numpy()
else:
    strongly_clustered_b0 = np.zeros(len(df), dtype=bool)

df["zb_strong_clustered_b0"] = strongly_clustered_b0

random_log_eta_runs = []
random_lat_runs = []
random_lon_runs = []

for run_idx in range(N_RANDOM_CATALOGS):
    print(f"Randomized catalog {run_idx + 1}/{N_RANDOM_CATALOGS}")

    # Randomized/reshuffled catalog:
    # - preserve original spatial locations
    # - permute times to break real space-time dependence
    # - permute magnitudes to preserve the magnitude distribution while breaking
    #   event-specific triggering dependence
    shuffled_time_positions = rng.permutation(len(df))
    shuffled_mag_positions = rng.permutation(len(df))

    rand_times_ns = event_times_ns[shuffled_time_positions]
    rand_magnitudes = magnitudes[shuffled_mag_positions]

    sort_idx = np.argsort(rand_times_ns)

    rand_times_ns_sorted = rand_times_ns[sort_idx]
    rand_lat_sorted = latitudes[sort_idx]
    rand_lon_sorted = longitudes[sort_idx]
    rand_depth_sorted = depths[sort_idx]
    rand_mag_sorted = rand_magnitudes[sort_idx]
    rand_event_ids_sorted = np.arange(len(df))

    (
        _rand_parent_ids,
        rand_log_etas,
        _rand_distances,
        _rand_dt_days,
    ) = compute_nearest_neighbor_log_eta(
        event_times_ns=rand_times_ns_sorted,
        latitudes=rand_lat_sorted,
        longitudes=rand_lon_sorted,
        depths=rand_depth_sorted,
        magnitudes=rand_mag_sorted,
        event_ids=rand_event_ids_sorted,
        day_ns=day_ns,
        max_lookback_days=MAX_LOOKBACK_DAYS,
        use_depth=USE_DEPTH,
        d_fractal=D_FRACTAL,
        b_value=B_VALUE,
        min_time_days=MIN_TIME_DAYS,
        min_distance_km=MIN_DISTANCE_KM,
        progress_interval=None,
    )

    random_log_eta_runs.append(np.asarray(rand_log_etas, dtype=float))
    random_lat_runs.append(rand_lat_sorted)
    random_lon_runs.append(rand_lon_sorted)

random_log_eta_pool = np.concatenate(random_log_eta_runs)
random_lat_pool = np.concatenate(random_lat_runs)
random_lon_pool = np.concatenate(random_lon_runs)

(
    alpha_i,
    local_random_percentile,
    local_random_median_log_eta,
    local_random_sample_count,
) = compute_local_alpha_from_randomized_background(
    real_log_eta=df["nn_log_eta"].to_numpy(dtype=float),
    real_latitudes=latitudes,
    real_longitudes=longitudes,
    random_log_eta_pool=random_log_eta_pool,
    random_lat_pool=random_lat_pool,
    random_lon_pool=random_lon_pool,
    local_k_neighbors=LOCAL_K_NEIGHBORS,
    min_samples=MIN_LOCAL_RANDOM_SAMPLES,
    progress_interval=PROGRESS_INTERVAL,
    query_chunk=BALLTREE_QUERY_CHUNK,
)

df["zb_alpha_i"] = alpha_i
df["zb_local_random_percentile"] = local_random_percentile
df["zb_local_random_median_log_eta"] = local_random_median_log_eta
df["zb_local_random_sample_count"] = local_random_sample_count

# Compute the no-parent mask once and reuse it.
no_parent_mask = df["nn_parent_event_id"].isna().to_numpy()

# Primary stochastic realization used for practical labels.
background_realizations = []
background_probability_realizations = []

for realization_idx in range(N_DECLUSTERING_REALIZATIONS):
    realization_rng = np.random.default_rng(RANDOM_SEED + 10_000 + realization_idx)
    is_background, background_probability = apply_zaliapin_ben_zion_random_thinning(
        alpha_i=alpha_i,
        alpha0=ALPHA0,
        rng=realization_rng,
    )

    # Step-1 strongly clustered events are not background in every realization.
    is_background[strongly_clustered_b0] = False

    # First event and events without parents are independent/background.
    is_background[no_parent_mask] = True

    background_realizations.append(is_background)
    background_probability_realizations.append(background_probability)

background_realizations = np.vstack(background_realizations)
background_probability_realizations = np.vstack(background_probability_realizations)

# Use the first realization for downstream sequence association.
primary_background = background_realizations[0]
primary_background_probability = background_probability_realizations[0]

# If more than one realization is used, this field summarizes how often each
# event remains background across stochastic declustering runs.
df["zb_background_frequency"] = background_realizations.mean(axis=0)
df["zb_background_probability"] = primary_background_probability
df["zb_background_realization"] = primary_background

df["zaliapin_triggered"] = ~df["zb_background_realization"]
# Reuse the precomputed no-parent mask instead of re-evaluating .isna().
df.loc[no_parent_mask, "zaliapin_triggered"] = False

df["threshold_method"] = "zaliapin_ben_zion_2020_random_thinning"
df["zb_eta0"] = eta0
df["zb_alpha0"] = ALPHA0


# ============================================================
# STEP 4: ASSIGN PRACTICAL MAINSHOCK-AFTERSHOCK SEQUENCES
# ============================================================

# This section is intentionally retained as a practical association layer.
# It is NOT part of the pure Zaliapin-Ben-Zion declustering method.
# It converts the declustered/triggered labels into capstone-friendly
# mainshock-aftershock sequence labels.
#
# OPTIMIZATION: Pre-extract every column the loop needs into NumPy arrays so
# we never call df.iloc[j] or df.loc[df["event_id"] == ...] inside the loop.
# Because event_id == row position (we set it via np.arange after sort+reset),
# integer indexing into these arrays is identical to the original lookup.

event_id_arr = df["event_id"].to_numpy()
mag_arr = df["magnitude"].to_numpy()
lat_arr = df["latitude"].to_numpy()
lon_arr = df["longitude"].to_numpy()
depth_arr = df["depth_km"].to_numpy()
triggered_arr = df["zaliapin_triggered"].to_numpy()
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

    is_triggered = bool(triggered_arr[j])
    nn_parent_raw = nn_parent_arr[j]
    # nn_parent_arr is float because of NaNs; check finiteness instead of pd.isna.
    nn_parent_is_nan = not np.isfinite(nn_parent_raw)

    if not is_triggered or nn_parent_is_nan:
        # Independent/background event.
        sequence_id[event_id] = event_id
        sequence_root_event_id[event_id] = event_id
        sequence_root_magnitude[event_id] = mag

        label = "mainshock_candidate"
        if mag < MAINSHOCK_DISPLAY_MAG_THRESHOLD:
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

    # If the nearest parent was not assigned for any reason,
    # treat current event as independent.
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

    # event_id == row position, so indexing by nn_parent gives the parent row.
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

    # Practical magnitude hierarchy rule:
    # If a later event is equal/larger than the current sequence mainshock,
    # it becomes a new mainshock sequence.
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

    # Otherwise, assign to parent's sequence.
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

# Helpful sequence summary fields.
sequence_sizes = df.groupby("sequence_id")["event_id"].transform("count")
df["sequence_event_count"] = sequence_sizes
df["sequence_aftershock_count"] = df["sequence_event_count"] - 1


# ============================================================
# STEP 5: SAVE AND PRINT SUMMARY
# ============================================================


df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved labeled dataset to: {OUTPUT_CSV}")
print("Used Zaliapin-Ben-Zion 2020-style random thinning")
print("alpha_i summary:")
print(df["zb_alpha_i"].describe())
print("Background probability summary:")
print(df["zb_background_probability"].describe())
print("Background realization counts:")
print(df["zb_background_realization"].value_counts(dropna=False))
print("Triggered counts:")
print(df["zaliapin_triggered"].value_counts(dropna=False))

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
        "zb_alpha_i",
        "zb_background_probability",
        "zaliapin_triggered",
        "nn_distance_km",
        "within_parent_spatial_influence",
    ]
].head(20))