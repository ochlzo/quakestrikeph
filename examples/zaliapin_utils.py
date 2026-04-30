import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture


def parse_phivolcs_datetime(value):
    return pd.to_datetime(value, format="%d %B %Y - %I:%M %p", errors="coerce")


def haversine_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0088

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        np.sin(dlat / 2.0) ** 2
        + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    )

    return 2.0 * earth_radius_km * np.arcsin(np.sqrt(a))


def hypocentral_distance_km(lat1, lon1, depth1, lat2, lon2, depth2):
    surface = haversine_km(lat1, lon1, lat2, lon2)
    dz = depth2 - depth1
    return np.sqrt(surface ** 2 + dz ** 2)


def gardner_knopoff_radius_km(magnitude):
    return 10 ** (0.1238 * magnitude + 0.983)


def estimate_log_eta_threshold(log_eta_values):
    values = np.asarray(log_eta_values, dtype=float)
    values = values[np.isfinite(values)]

    if len(values) < 20:
        raise ValueError("Not enough valid log_eta values to estimate threshold.")

    x = values.reshape(-1, 1)
    gmm = GaussianMixture(n_components=2, random_state=42)
    gmm.fit(x)

    means = gmm.means_.flatten()
    triggered_component = int(np.argmin(means))
    background_component = int(np.argmax(means))

    grid = np.linspace(values.min(), values.max(), 2000).reshape(-1, 1)
    probs = gmm.predict_proba(grid)
    diff = np.abs(probs[:, triggered_component] - probs[:, background_component])

    return float(grid[np.argmin(diff)][0]), {
        "means": means.tolist(),
        "triggered_component": triggered_component,
        "background_component": background_component,
    }

def compute_nearest_neighbor_log_eta(
    event_times_ns,
    latitudes,
    longitudes,
    depths,
    magnitudes,
    event_ids,
    day_ns,
    max_lookback_days,
    use_depth,
    d_fractal,
    b_value,
    min_time_days,
    min_distance_km,
    progress_interval=None,
):
    """
    Computes nearest previous neighbor and log_eta for a catalog.

    This is the same nearest-neighbor core used in the main script, but
    packaged as a reusable function so it can be applied to real and
    randomized/reshuffled catalogs.

    Returns:
        parent_ids, parent_log_etas, parent_distances, parent_dt_days
    """

    parent_ids = []
    parent_log_etas = []
    parent_distances = []
    parent_dt_days = []

    lookback_ns = None
    if max_lookback_days is not None:
        lookback_ns = int(max_lookback_days * day_ns)

    n = len(event_times_ns)

    for j in range(n):
        if (
            progress_interval is not None
            and j > 0
            and j % progress_interval == 0
        ):
            print(f"Processed nearest neighbors for {j:,}/{n:,} events")

        if j == 0:
            parent_ids.append(np.nan)
            parent_log_etas.append(np.nan)
            parent_distances.append(np.nan)
            parent_dt_days.append(np.nan)
            continue

        start_idx = 0
        if lookback_ns is not None:
            cutoff_ns = event_times_ns[j] - lookback_ns
            start_idx = int(np.searchsorted(event_times_ns, cutoff_ns, side="left"))

        candidate_positions = np.arange(start_idx, j)

        if len(candidate_positions) == 0:
            parent_ids.append(np.nan)
            parent_log_etas.append(np.nan)
            parent_distances.append(np.nan)
            parent_dt_days.append(np.nan)
            continue

        dt_days = (
            (event_times_ns[j] - event_times_ns[candidate_positions])
            / day_ns
        )

        valid = dt_days > 0

        if not np.any(valid):
            parent_ids.append(np.nan)
            parent_log_etas.append(np.nan)
            parent_distances.append(np.nan)
            parent_dt_days.append(np.nan)
            continue

        prev_valid_positions = candidate_positions[valid]
        dt_valid = dt_days[valid]

        if use_depth:
            distances = hypocentral_distance_km(
                latitudes[prev_valid_positions],
                longitudes[prev_valid_positions],
                depths[prev_valid_positions],
                latitudes[j],
                longitudes[j],
                depths[j],
            )
        else:
            distances = haversine_km(
                latitudes[prev_valid_positions],
                longitudes[prev_valid_positions],
                latitudes[j],
                longitudes[j],
            )

        dt_years = np.maximum(dt_valid, min_time_days) / 365.25

        log_etas = (
            np.log10(dt_years)
            + d_fractal * np.log10(np.maximum(distances, min_distance_km))
            - b_value * magnitudes[prev_valid_positions]
        )

        best_pos = int(np.argmin(log_etas))
        best_parent_pos = int(prev_valid_positions[best_pos])

        parent_ids.append(int(event_ids[best_parent_pos]))
        parent_log_etas.append(float(log_etas[best_pos]))
        parent_distances.append(float(distances[best_pos]))
        parent_dt_days.append(float(dt_valid[best_pos]))

    return parent_ids, parent_log_etas, parent_distances, parent_dt_days

def compute_nearest_neighbor_log_eta_2cat(
    target_times_ns,
    target_lats,
    target_lons,
    target_deps,
    parent_times_ns,
    parent_lats,
    parent_lons,
    parent_deps,
    parent_mags,
    day_ns,
    max_lookback_days,
    use_depth,
    d_fractal,
    b_value,
    min_time_days,
    min_distance_km,
    progress_interval=None,
):
    """
    Two-catalog nearest-neighbor proximity.

    For each event in the TARGET catalog, find its nearest-neighbor proximity
    among prior events in the PARENT catalog. Mirrors bp_2cat_add_1.m.

    Both catalogs must be sorted by time (ascending).

    Returns:
        parent_positions  : index into parent arrays (or -1 if no candidate)
        log_etas          : log10 of nearest-neighbor proximity (NaN if none)
        distances_km      : distance to nearest parent (NaN if none)
        dt_days           : time gap to nearest parent (NaN if none)
    """
    import numpy as np

    n_target = len(target_times_ns)
    n_parent = len(parent_times_ns)

    parent_positions = np.full(n_target, -1, dtype=np.int64)
    log_etas = np.full(n_target, np.nan)
    distances_km = np.full(n_target, np.nan)
    dt_days = np.full(n_target, np.nan)

    lookback_ns = None
    if max_lookback_days is not None:
        lookback_ns = int(max_lookback_days * day_ns)

    for j in range(n_target):
        if (
            progress_interval is not None
            and j > 0
            and j % progress_interval == 0
        ):
            print(f"  2cat: processed {j:,}/{n_target:,} target events")

        t_j = target_times_ns[j]

        # candidate parents: parent_times < t_j (and within lookback if set)
        upper = int(np.searchsorted(parent_times_ns, t_j, side="left"))
        if upper == 0:
            continue

        if lookback_ns is None:
            lower = 0
        else:
            cutoff = t_j - lookback_ns
            lower = int(np.searchsorted(parent_times_ns, cutoff, side="left"))

        if lower >= upper:
            continue

        cand = np.arange(lower, upper)
        dt = (t_j - parent_times_ns[cand]) / day_ns

        valid = dt > 0
        if not np.any(valid):
            continue

        cand = cand[valid]
        dt = dt[valid]

        # surface distance via haversine
        lat1 = np.radians(parent_lats[cand])
        lon1 = np.radians(parent_lons[cand])
        lat2 = np.radians(target_lats[j])
        lon2 = np.radians(target_lons[j])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        d_surf = 2.0 * 6371.0088 * np.arcsin(np.sqrt(a))

        if use_depth:
            dz = target_deps[j] - parent_deps[cand]
            d = np.sqrt(d_surf ** 2 + dz ** 2)
        else:
            d = d_surf

        dt_years = np.maximum(dt, min_time_days) / 365.25
        d_km = np.maximum(d, min_distance_km)

        log_eta = (
            np.log10(dt_years)
            + d_fractal * np.log10(d_km)
            - b_value * parent_mags[cand]
        )

        best = int(np.argmin(log_eta))
        parent_positions[j] = cand[best]
        log_etas[j] = float(log_eta[best])
        distances_km[j] = float(d[best])
        dt_days[j] = float(dt[best])

    return parent_positions, log_etas, distances_km, dt_days