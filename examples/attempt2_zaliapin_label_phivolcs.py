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
OUTPUT_CSV = "phivolcs_labeled_zaliapin_sequences.csv"

DATE_COL = "Date-Time"
LAT_COL = "Latitude"
LON_COL = "Longitude"
DEPTH_COL = "Depth"
MAG_COL = "Magnitude"

# Zaliapin/Baiesi-Paczuski style nearest-neighbor parameters.
# b_value is usually near 1.0 for many catalogs, but should ideally
# be estimated from your Philippine catalog after checking magnitude completeness.
B_VALUE = 1.0

# Effective spatial/fractal dimension.
# Many examples use values around 1.5 to 1.6.
D_FRACTAL = 1.6

# Avoid log(0) when two records have identical time or location.
MIN_TIME_DAYS = 1.0 / (24 * 60)   # 1 minute
MIN_DISTANCE_KM = 0.1             # 100 meters

# If True, use 3D hypocentral distance using depth.
# If False, use surface epicentral distance only.
USE_DEPTH = True

# This is NOT a 7-day cutoff.
# It is only a computational safety guard. Set to None to compare
# every event against all previous events.
MAX_LOOKBACK_DAYS = 365

# Status output for long catalog runs.
PROGRESS_INTERVAL = 5000

# Magnitude threshold for public-facing "mainshock candidate" flag.
# Do not use this to ignore smaller events entirely.
MAINSHOCK_DISPLAY_MAG_THRESHOLD = 4.5

# Whether child events must also stay inside the original sequence root radius.
# False is more flexible and allows secondary triggering.
REQUIRE_WITHIN_ROOT_RADIUS = False

# ============================================================
# ZALIAPIN-BEN-ZION-STYLE SPACE-VARYING THRESHOLD CONFIG
# ============================================================

USE_SPACE_VARYING_THRESHOLD = True

# Number of randomized/reshuffled catalogs.
# Higher is more stable but slower. Use 20 for testing, 50-100 for final runs.
N_RANDOM_CATALOGS = 50

# Local neighborhood size for estimating a space-varying threshold.
# This is a practical Python approximation of a local threshold.
LOCAL_K_NEIGHBORS = 300

# Quantile of randomized nearest-neighbor values used as the local threshold.
# Lower value = stricter clustering classification.
# 0.05 means an event must be more clustered than 95% of local randomized-background cases.
LOCAL_THRESHOLD_QUANTILE = 0.05

RANDOM_SEED = 42


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


# ============================================================
# STEP 3: CLASSIFY BACKGROUND VS TRIGGERED
# ZALIAPIN-BEN-ZION-STYLE SPACE-VARYING THRESHOLD
# ============================================================

if USE_SPACE_VARYING_THRESHOLD:
    print("Estimating Zaliapin-Ben-Zion-style space-varying thresholds...")
    rng = np.random.default_rng(RANDOM_SEED)

    real_coords_rad = np.radians(
        np.column_stack([latitudes, longitudes])
    )

    real_tree = BallTree(real_coords_rad, metric="haversine")

    random_log_eta_runs = []
    random_lat_runs = []
    random_lon_runs = []

    for run_idx in range(N_RANDOM_CATALOGS):
        print(f"Randomized catalog {run_idx + 1}/{N_RANDOM_CATALOGS}")

        # ------------------------------------------------------------
        # Randomized/reshuffled catalog idea:
        # - preserve the spatial locations from the original catalog
        # - break real space-time dependence by permuting event times
        # - keep catalog size and magnitude distribution
        #
        # This is a practical Python approximation of the randomized-
        # reshuffled catalogs described by Zaliapin and Ben-Zion.
        # ------------------------------------------------------------

        shuffled_time_positions = rng.permutation(len(df))
        shuffled_mag_positions = rng.permutation(len(df))

        rand_times_ns = event_times_ns[shuffled_time_positions]
        rand_magnitudes = magnitudes[shuffled_mag_positions]

        # Sort randomized catalog by randomized time.
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

    # Combine randomized catalogs into one reference pool.
    random_log_eta_pool = np.concatenate(random_log_eta_runs)
    random_lat_pool = np.concatenate(random_lat_runs)
    random_lon_pool = np.concatenate(random_lon_runs)

    valid_random = np.isfinite(random_log_eta_pool)

    random_log_eta_pool = random_log_eta_pool[valid_random]
    random_lat_pool = random_lat_pool[valid_random]
    random_lon_pool = random_lon_pool[valid_random]

    random_coords_rad = np.radians(
        np.column_stack([random_lat_pool, random_lon_pool])
    )

    random_tree = BallTree(random_coords_rad, metric="haversine")

    local_thresholds = np.full(len(df), np.nan)
    background_probabilities = np.full(len(df), np.nan)

    query_k = min(LOCAL_K_NEIGHBORS, len(random_log_eta_pool))

    for j in range(len(df)):
        if j > 0 and j % PROGRESS_INTERVAL == 0:
            print(f"Estimated local thresholds for {j:,}/{len(df):,} events")

        if not np.isfinite(df.loc[j, "nn_log_eta"]):
            continue

        event_coord_rad = np.radians([[latitudes[j], longitudes[j]]])

        _, neighbor_idx = random_tree.query(event_coord_rad, k=query_k)

        local_random_log_etas = random_log_eta_pool[neighbor_idx[0]]
        local_random_log_etas = local_random_log_etas[
            np.isfinite(local_random_log_etas)
        ]

        if len(local_random_log_etas) < 20:
            continue

        local_threshold = float(
            np.quantile(local_random_log_etas, LOCAL_THRESHOLD_QUANTILE)
        )

        local_thresholds[j] = local_threshold

        # Background probability approximation:
        # If the real event has very low log_eta compared with randomized
        # background cases, it is less likely background and more likely clustered.
        real_log_eta = float(df.loc[j, "nn_log_eta"])
        background_probability = float(
            np.mean(local_random_log_etas <= real_log_eta)
        )

        background_probabilities[j] = background_probability

    df["local_log_eta_threshold"] = local_thresholds
    df["background_probability"] = background_probabilities

    df["zaliapin_triggered"] = (
        df["nn_log_eta"].notna()
        & df["local_log_eta_threshold"].notna()
        & (df["nn_log_eta"] <= df["local_log_eta_threshold"])
    )

    df["threshold_method"] = "zaliapin_ben_zion_style_space_varying"

else:
    threshold, threshold_info = estimate_log_eta_threshold(df["nn_log_eta"].dropna())

    df["nn_log_eta_threshold"] = threshold
    df["zaliapin_triggered"] = df["nn_log_eta"] <= threshold
    df["threshold_method"] = "global_gmm"

    print(f"Estimated global nn_log_eta threshold: {threshold:.4f}")
    print(f"GMM info: {threshold_info}")

# First event and events without parents are always independent.
df.loc[df["nn_parent_event_id"].isna(), "zaliapin_triggered"] = False


# ============================================================
# STEP 4: ASSIGN MAINSHOCK-AFTERSHOCK SEQUENCES
# ============================================================

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

for j in range(len(df)):
    event = df.iloc[j]
    event_id = int(event["event_id"])
    mag = float(event["magnitude"])

    is_triggered = bool(event["zaliapin_triggered"])
    nn_parent = event["nn_parent_event_id"]

    if not is_triggered or pd.isna(nn_parent):
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

    nn_parent = int(nn_parent)

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

    parent_row = df.loc[df["event_id"] == nn_parent].iloc[0]
    parent_mag = float(parent_row["magnitude"])

    parent_radius_km = gardner_knopoff_radius_km(parent_mag)
    child_parent_distance = float(event["nn_distance_km"])
    spatial_ok = child_parent_distance <= parent_radius_km

    parent_sequence = sequence_id[nn_parent]
    root_event_id = sequence_root_event_id[parent_sequence]
    root_mag = sequence_root_magnitude[parent_sequence]

    if REQUIRE_WITHIN_ROOT_RADIUS:
        root_row = df.loc[df["event_id"] == root_event_id].iloc[0]
        root_radius_km = gardner_knopoff_radius_km(float(root_row["magnitude"]))

        if USE_DEPTH:
            distance_to_root = hypocentral_distance_km(
                root_row["latitude"],
                root_row["longitude"],
                root_row["depth_km"],
                event["latitude"],
                event["longitude"],
                event["depth_km"],
            )
        else:
            distance_to_root = haversine_km(
                root_row["latitude"],
                root_row["longitude"],
                event["latitude"],
                event["longitude"],
            )

        spatial_ok = spatial_ok and (distance_to_root <= root_radius_km)

    # Your magnitude rule:
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

    parent_generation = generation_numbers[nn_parent] if nn_parent < len(generation_numbers) else 0
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

df.to_csv(OUTPUT_CSV, index=False)

print(f"Saved labeled dataset to: {OUTPUT_CSV}")
if USE_SPACE_VARYING_THRESHOLD:
    print("Used Zaliapin-Ben-Zion-style space-varying thresholds")
    print("Local threshold summary:")
    print(df["local_log_eta_threshold"].describe())
    print("Background probability summary:")
    print(df["background_probability"].describe())
else:
    print(f"Estimated global nn_log_eta threshold: {threshold:.4f}")
    print(f"GMM info: {threshold_info}")

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
        "nn_distance_km",
        "within_parent_spatial_influence",
    ]
].head(20))
