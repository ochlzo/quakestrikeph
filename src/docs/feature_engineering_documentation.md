# Training Document: How Feature Engineering Works for the SEIS Model

> **Who this is for:** Junior developers on the QuakestrikePH team. No seismology
> or machine learning background assumed. Python experience is helpful but the
> code is explained line by line where it matters.
>
> **What you will understand after reading this:** Why we need features at all,
> where each feature comes from, how the code computes it, and — most importantly
> — why none of the features leak information about the future.

---

## How to Read This Document

This document builds one idea at a time. Read it in order:

1. **The problem** — why raw earthquake data isn't enough for a model
2. **The single source of truth** — one module, no drift
3. **The data leakage rule** — the most important design rule in the whole pipeline
4. **Group 1: Event basics** — magnitude, depth, location
5. **Group 2: Parent / eta features** — the clustering geometry
6. **Group 3: Time features** — calendar signals
7. **Group 4: Recent global activity** — catalog-wide seismic traffic
8. **Group 5: Recent local activity** — neighborhood seismicity grid
9. **Group 6: Physics-derived features** — rupture mechanics and Bath's Law
10. **Quick-reference table** — all 65 features at a glance

---

## Part 1: The Problem We're Solving

When the C++ Zaliapin–Ben-Zion clustering step finishes, we have a CSV with
roughly 100,000 earthquakes. Each row says things like:

```
origin_time: "15 October 2022 - 01:03 AM"
latitude: 17.4321
longitude: 120.6890
depth_km: 17.0
magnitude: 7.0
event_role: mainshock
```

A machine learning model cannot learn from raw values like this directly — at
least, not well. Numbers like latitude and longitude on their own don't tell the
model anything meaningful. The model needs to be asked **the right questions**
in a form it can understand.

Feature engineering is the act of turning the raw record into an answer-ready
form. Instead of just telling the model where an earthquake happened, we tell it:

- *How big was the rupture, and how shallow?* (`rupture_depth_attenuation`)
- *How many earthquakes hit this area in the past 30 days?* (`local_events_50km_past_30d`)
- *Was the region seismically quieter than average or busier?* (`seis_traffic_ratio_30d`)
- *How closely related is this event to its nearest predecessor?* (`eta`)

Each of these is a **feature** — one column in the model's input matrix. The
SEIS model uses 65 of them for every earthquake it evaluates.

---

## Part 2: The Single Source of Truth

> **The key constraint:** The features computed for a row in the training set
> must be **bit-for-bit identical** to the features computed for that same
> earthquake when the model is deployed and making real predictions.

This is not a nice-to-have. If the training definition and the serving definition
drift — even slightly — the model silently operates on a different distribution
at serving time than it learned from. This is called **train/serve skew** and it
is notoriously hard to debug.

Our solution: every feature in the SEIS pipeline is defined **once and only once**
in [`feature_engineering.py`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/feature_engineering.py).

```python
# feature_engineering.py — the module docstring says it plainly:
\"\"\"Single source of truth for SEIS aftershock feature engineering.

Both the training-dataset builder and every inference path compute their model
features from this module, so there is exactly one definition of each feature and
no risk of the train/serve drift that historically caused skew.
\"\"\"
```

The module exposes two styles of builder that share the same constants and formulas:

| Builder style | Functions | Used by |
|---|---|---|
| **Batch builders** | `add_*` functions | `build_training_dataset.py` — processes the whole sorted catalog at once, vectorized |
| **Per-event builders** | `compute_*` / `build_prediction_features` | Live inference — computes one event's features against all prior history |

The batch builders are fast (vectorized NumPy). The per-event builders are correct
(explicit loops over prior history). Both use the same formulas because they both
call the same shared constants and helper functions defined at the top of the file.

```python
# Shared constants — both paths read these:
LOCAL_RADII_KM       = [10.0, 25.0, 50.0, 100.0]
RECENT_WINDOWS_DAYS  = [1, 7, 30]
DEFAULT_B_VALUE      = 1.0
DEFAULT_FRACTAL_DIMENSION = 1.6
DEFAULT_LOG10_ETA0   = -5.468679834899335
DEFAULT_RESCALE_Q    = 0.5
```

Change a constant here and it changes for both training and serving simultaneously.
That is the point.

---

## Part 3: The Data Leakage Rule

> [!IMPORTANT]
> This section describes the most important safety property of the entire pipeline.
> Internalize it before touching any feature code.

### What is data leakage?

A model is supposed to predict the **future** from the **past**. Data leakage
happens when a feature is computed using information that would not exist at the
moment the model makes its prediction — for example, information about events
that happen **after** the earthquake being evaluated.

A model trained on leaked features looks artificially accurate during evaluation.
When deployed, it fails — because the future information it secretly relied on
no longer exists.

### The leakage safety rule

Every feature in the SEIS pipeline obeys one strict rule:

> **For any earthquake at time T, a feature may only use information from
> events that occurred strictly before T.**

This is enforced in code by the way history is filtered before any computation.
In the batch path (training), every `add_*` function receives the full sorted
catalog but only examines events at index `i < j` (i.e., earlier than row j).
In the serving path, the filter is explicit:

```python
# feature_engineering.py — filter_history_for_prediction()
def filter_history_for_prediction(history, event_time, minimum_magnitude):
    history = history[
        (history["event_time"] < event_time)      # strictly BEFORE the event
        & (history["magnitude"] >= minimum_magnitude)
    ].copy()
    return history.sort_values("event_time", kind="mergesort").reset_index(drop=True)
```

The `< event_time` condition (not `<=`) ensures same-timestamp events are also
excluded. The history that gets passed to every `compute_*` function has already
been filtered this way.

### Why each feature family is safe

| Feature group | Why it's safe |
|---|---|
| **Event basics** (magnitude, depth, lat, lon) | These are intrinsic properties of the earthquake itself — they exist the instant the event occurs. No future information. |
| **Parent / eta features** | The parent is always an *earlier* event (sorted catalog, `j > i`). The η formula only uses the time gap and distance to events that happened before. |
| **Time features** | Derived from the event's own timestamp. No future information. |
| **Recent global / local activity** | Computed as counts or statistics of events in the N days *before* the event's timestamp. The window is `[event_time - N days, event_time)` — the right bracket is open (exclusive). |
| **Physics-derived features** | Functions of the event's own magnitude and depth only. No catalog lookup at all. |

### The target is computed separately — and that's intentional

The forecast targets (e.g., `aftershock_24h`, `nearest_aftershock_distance_km_24h`)
are computed in [`build_training_dataset.py`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/build_training_dataset.py)
in a separate function called `add_forecast_targets()`. That function **does**
look forward in time — it has to, because the target is the answer to "did an
aftershock happen in the next 24 hours?" But that function is completely separate
from the feature builders, and the features are finalized before the targets are
attached. This physical separation in the code is deliberate: it makes leakage
structurally impossible, not just a matter of programmer discipline.

The targets are covered in their own training document.

---

## Part 4: Group 1 — Event Basics

**Source:** The raw PHIVOLCS catalog, carried through unchanged.

These are the simplest features — they describe the earthquake itself, with no
computation needed beyond reading the record.

| Feature | Type | What it is |
|---|---|---|
| `magnitude` | float | Richter magnitude of the event |
| `depth_km` | float | Depth below the Earth's surface, in kilometers |
| `latitude` | float | Latitude of the epicenter (degrees north) |
| `longitude` | float | Longitude of the epicenter (degrees east) |

**Why they're in the feature set:** Magnitude and depth are the most direct
proxies for how much energy an earthquake releases and where that energy goes.
Shallow earthquakes cause more surface damage and are more likely to trigger
nearby aftershocks than deep ones at the same magnitude. Latitude and longitude
give the model a geographic anchor — seismicity patterns in the Luzon arc are
different from those in the Visayas and Mindanao.

These four appear first in
[`select_training_columns()`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/build_training_dataset.py#L163-L237)
and are passed through from the clustered CSV without modification.

---

## Part 5: Group 2 — Parent / Eta Features

**Source:** C++ Zaliapin–Ben-Zion clustering output (training) and
[`compute_parent_features()`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/feature_engineering.py#L160-L233)
(serving).

This is the richest and most novel group. To understand it, you need to recall
the η (eta) concept from the clustering step.

> **Quick recap:** For every earthquake `j`, the algorithm finds the single
> earlier earthquake `i` that minimizes the **nearest-neighbor distance**:
>
> ```
> η_ij = t_ij × (r_ij)^d_f × 10^(−b × m_i)
> ```
>
> where `t_ij` is the time gap in years, `r_ij` is the surface distance in km,
> `d_f = 1.6`, `b = 1.0`, and `m_i` is the parent's magnitude. That minimizing
> event `i` is called `j`'s **parent**.

Every event in the catalog (except the very first) has a parent. These features
expose the geometry of that parent-child relationship.

### The training / serving split — and why it's safe

At **training time**, parent features come directly from the authoritative C++
clustering output. The columns `eta`, `log10_eta`, and `is_strong_link` are
already in the clustered CSV and are read by
[`add_parent_features()`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/feature_engineering.py#L450-L497).

At **serving time**, the Python function `compute_parent_features()` re-derives
the parent from scratch using the same formula — it scans all prior events and
finds the one with the minimum η. Both paths use the same constants (`b = 1.0`,
`d_f = 1.6`, `η₀ = 10^−5.469`), so the two are verified to agree with
correlation 1.000 on the same data. The regression guard for this is
`investigate_feature_skew.py`.

```python
# feature_engineering.py — compute_parent_features() (serving path)
log_eta = (
    np.log10(years)
    + fractal_dimension * np.log10(distances)
    - b_value * candidates["magnitude"].to_numpy(dtype=float)
)
best_position = int(np.nanargmin(log_eta))
```

This is the same formula as the C++ code, translated to Python.

### The features, one by one

#### `eta`

The raw nearest-neighbor distance between this event and its parent. Small η
means the event is tightly coupled to its parent in time and space (accounting
for parent magnitude). Large η means the link is weak — the event is more likely
a background earthquake that happened to have a geometrically nearest neighbor.

```
η = t_years × dist_km^1.6 × 10^(−1.0 × m_parent)
```

The value is stored as a raw float. In practice this number spans many orders of
magnitude (from 10⁻¹⁰ for tightly clustered aftershocks to 10³ for isolated
background events), which is why we also keep:

#### `log10_eta`

```
log10_eta = log₁₀(η)
```

The base-10 logarithm of η. Because η spans such an enormous range, its
logarithm is far more useful as a model feature — it compresses the range into
something like `[-10, 3]` rather than `[0.0000000001, 1000]`.

#### `is_strong_link`

A binary flag: `1` if `log10_eta < −5.469` (the η₀ threshold), `0` otherwise.
If this is 1, the parent link survived the clustering threshold cut — meaning the
algorithm considers this event genuinely part of its parent's sequence.
If this is 0, the link is coincidental and the event is a background event.

```python
# In compute_parent_features():
"is_strong_link": int(best_log_eta < log10_eta0),
```

#### `has_parent`

A binary flag: `1` for every event except the very first in the catalog. All
events have a nearest-neighbor parent by construction; this flag simply signals
whether the parent lookup succeeded. (The first event in the sorted catalog has
no predecessors, so `has_parent = 0`.)

#### `parent_time_gap_days`

The number of days between this event and its parent. A small gap (minutes to
hours) strongly suggests an aftershock relationship. A large gap (weeks to months)
could still be a sequence member if the parent was very large, but the evidence
is weaker.

```python
# add_parent_features() — batch path
df["parent_time_gap_days"] = (
    df["event_time"] - parent
).dt.total_seconds() / 86400.0
```

#### `parent_distance_km`

The surface distance (Haversine, in km) between the epicenter of this event and
its parent's epicenter. Computed using the same `haversine_km()` helper used
everywhere else in the module.

#### `parent_magnitude`

The Richter magnitude of the parent event. A parent magnitude of 7.0 gives the
model a very different context than a parent magnitude of 2.5 — large parents
can trigger aftershocks at far greater distances and over longer time windows.

#### `parent_depth_km`

The depth of the parent's hypocenter. Deep parents tend to produce fewer and
shallower aftershocks at the surface. This pairs with `parent_magnitude` to give
the model a richer picture of the parent event's rupture characteristics.

---

### `log10_rescaled_time` and `log10_rescaled_distance`

These two features deserve special attention because they emerge from a more
subtle insight about η.

**The problem with η alone:** η is a product of time and distance information.
When you give the model only `log10_eta`, it cannot tell *why* η is small. Was
it because the event happened very soon after the parent (close in time but far
in space)? Or very close to the parent (close in space but delayed in time)?
Those are physically different situations that can lead to different aftershock
behaviors, but they produce the same η.

**The solution:** Decompose `log10_eta` into its two components, weighted by
the parameter `q = 0.5`:

```
log10(T) = log10(years)           - q       × b × m_parent
log10(R) = d_f × log10(dist_km)  - (1 - q) × b × m_parent
```

By construction, `log10(T) + log10(R) = log10(η)`. So we are not adding new
information — we are re-expressing the same information in a more discriminative
form. Background events and clustered events separate along *different axes* in
the (log T, log R) plane, giving tree-based models and gradient boosters a much
cleaner split boundary than the product `eta` alone can provide.

The parameter `q = 0.5` weights temporal and spatial contributions equally. This
is the value from the Zaliapin–Ben-Zion paper.

```python
# feature_engineering.py — rescaled_time_distance()
def rescaled_time_distance(years, distance_km, parent_magnitude, b_value,
                           fractal_dimension, q):
    log10_time = np.log10(years) - q * b_value * parent_magnitude
    log10_distance = (
        fractal_dimension * np.log10(distance_km)
        - (1.0 - q) * b_value * parent_magnitude
    )
    return log10_time, log10_distance
```

**Leakage check:** Both components are computed from `parent_time_gap_days`,
`parent_distance_km`, and `parent_magnitude` — all of which come from an earlier
event. No future information is involved.

---

### Summary table for Group 2

| Feature | What it measures |
|---|---|
| `eta` | Raw nearest-neighbor distance (smaller = more related) |
| `log10_eta` | log₁₀(η) — compressed scale, far better for models |
| `log10_rescaled_time` | Magnitude-weighted temporal component of log₁₀η |
| `log10_rescaled_distance` | Magnitude-weighted spatial component of log₁₀η |
| `is_strong_link` | 1 if parent link survived the η₀ threshold, 0 otherwise |
| `has_parent` | 1 for all events except the catalog's first event |
| `parent_time_gap_days` | Days elapsed since the parent event |
| `parent_distance_km` | Surface distance to the parent's epicenter (km) |
| `parent_magnitude` | Richter magnitude of the parent event |
| `parent_depth_km` | Depth of the parent's hypocenter (km) |

---

## Part 6: Group 3 — Time Features

**Source:** The event's own timestamp.

These five features extract the temporal position of the earthquake on the
calendar. The code is straightforward:

```python
# feature_engineering.py — add_time_features()
def add_time_features(df):
    event_time = df["event_time"]
    df["event_year"]      = event_time.dt.year
    df["event_month"]     = event_time.dt.month
    df["event_dayofyear"] = event_time.dt.dayofyear
    df["event_hour"]      = event_time.dt.hour
    df["event_weekday"]   = event_time.dt.weekday
    return df
```

| Feature | Range | What it captures |
|---|---|---|
| `event_year` | 2018–2026 | Long-term trends in the catalog (completeness changes, network improvements) |
| `event_month` | 1–12 | Seasonal patterns in recorded seismicity |
| `event_dayofyear` | 1–366 | Finer seasonal resolution than month alone |
| `event_hour` | 0–23 | Time-of-day effects (also correlates with network detection thresholds) |
| `event_weekday` | 0–6 (Mon–Sun) | Day-of-week patterns in network operation and reporting |

**Why include calendar features?** Seismicity is not uniformly distributed across
time. There are seasonal patterns in some regions. Network detection thresholds
also vary with time (noise levels at night are different from daytime, and
station coverage improved significantly between 2018 and 2026). These features
let the model pick up on those patterns without the engineer having to manually
encode them.

**Leakage check:** Every feature here is derived entirely from the event's own
timestamp. No catalog lookup required.

---

## Part 7: Group 4 — Recent Global Activity

**Source:** Catalog-wide count of events in N-day windows before this event.

### The event count features

Before looking at the neighborhood, we ask: *how busy was the entire Philippine
catalog in the recent past?* These features answer that question.

| Feature | What it counts |
|---|---|
| `events_past_1d` | Events anywhere in the catalog in the 24 hours before this event |
| `events_past_7d` | Events anywhere in the catalog in the 7 days before this event |
| `events_past_30d` | Events anywhere in the catalog in the 30 days before this event |

In the batch path, these are computed with a binary search (`np.searchsorted`)
against the sorted timestamp array — no inner loop over individual events needed.

```python
# feature_engineering.py — add_recent_global_features() (simplified)
time_ns = df["event_time"].astype("datetime64[ns]").astype("int64").to_numpy()
order   = np.arange(len(df))

for days in RECENT_WINDOWS_DAYS:          # [1, 7, 30]
    window_ns = int(days * 86400 * 1_000_000_000)
    starts = np.searchsorted(time_ns, time_ns - window_ns, side="left")
    df[f"events_past_{days}d"] = order - starts
```

`order - starts` gives, for each row, how many rows fall in the window. Because
the catalog is sorted by time, this is exact.

### `seis_traffic_ratio_30d`

This is the most interesting feature in Group 4. A raw count like
`events_past_30d = 500` doesn't mean much on its own — is 500 a lot for the
Philippines, or normal? The ratio contextualizes it.

**Definition:**

```
seis_traffic_ratio_30d = events_past_30d / average_monthly_count_over_5y
```

The denominator is the average number of events per month, computed over the
5-year window ending at this event's timestamp. A ratio greater than 1 means the
catalog is currently more active than its historical baseline. A ratio less than
1 means it is quieter than usual.

**Why this matters:** A major earthquake sequence dramatically elevates catalog
activity for weeks. This ratio captures whether the model is operating in a
"hot" environment (recent large mainshock, ongoing aftershock sequence) or a
"quiet" environment. It is a global seismic temperature gauge.

```python
# feature_engineering.py — add_recent_global_features()
window_5y_ns = int(5 * 365.25 * 86400 * 1_000_000_000)
starts_5y    = np.searchsorted(time_ns, time_ns - window_5y_ns, side="left")
events_past_5y = order - starts_5y

t_avail_days   = (time_ns - time_ns[0]) / (86400 * 1_000_000_000)
t_avail_days   = np.maximum(t_avail_days, 1.0 / 24.0)   # at least 1 hour
t_avail_days   = np.minimum(5 * 365.25, t_avail_days)   # at most 5 years
t_avail_months = t_avail_days / 30.4375

avg_monthly_count = events_past_5y / t_avail_months
ratio = df["events_past_30d"] / np.maximum(avg_monthly_count, 1e-5)

# Edge case: if fewer than 30 days of history exist, default ratio to 1.0
df["seis_traffic_ratio_30d"] = np.where(t_avail_days < 30.0, 1.0, ratio)
```

The `np.maximum(..., 1e-5)` guard prevents division by zero for the very first
events in the catalog. The `< 30.0` early-history guard ensures we don't compute
a noisy ratio from only a few days of data.

**Leakage check:** Both `events_past_30d` and the 5-year count use only events
strictly before the current row's timestamp. Safe.

---

## Part 8: Group 5 — Recent Local Activity

**Source:** Spatial neighborhood of the event, across 4 radii × 3 windows.

This is the largest and most computationally expensive feature group. It answers
the question: *what has been happening in this specific patch of the crust,
recently?*

### How the neighborhood is defined

The pipeline computes local features at four radii and three time windows:

```python
LOCAL_RADII_KM      = [10.0, 25.0, 50.0, 100.0]   # spatial rings
RECENT_WINDOWS_DAYS = [1, 7, 30]                    # time windows
```

Every (radius, window) combination gives three features, yielding 4 × 3 × 3 = 36
features from the grid. Beyond the grid, there are 3 nearest-event features and
1 b-value feature, for 40 local features total.

### The bounding box pre-filter

Computing the exact Haversine distance from one event to every prior event in a
100-km, 30-day window would be expensive if applied naively. Before doing the
precise distance calculation, the code first applies a **rectangular lat/lon
bounding box** to quickly discard candidates that are obviously too far away:

```python
# feature_engineering.py — add_recent_local_features()
lat_delta_degrees = max_radius_km / 111.32          # 1 degree latitude ≈ 111.32 km
lon_scale = max(math.cos(math.radians(lat[row_index])), 0.1)
lon_delta_degrees = max_radius_km / (111.32 * lon_scale)

bounding_box_mask = (
    (np.abs(candidate_lat - lat[row_index]) <= lat_delta_degrees)
    & (np.abs(candidate_lon - lon[row_index]) <= lon_delta_degrees)
)
```

The longitude correction (`lon_scale`) accounts for the fact that degrees of
longitude represent shorter distances at higher latitudes (the Philippines spans
roughly 5°N to 21°N, so this matters). After the box filter, the Haversine
formula runs only on the remaining candidates — a fraction of the original set.
This is a performance optimization only; it does not change the results.

### The per-cell features

For every (radius, window) cell, three features are computed:

| Feature pattern | What it is |
|---|---|
| `local_events_Xkm_past_Yd` | Count of events within X km in the past Y days |
| `local_max_mag_Xkm_past_Yd` | Maximum magnitude among those events |
| `local_log10_energy_Xkm_past_Yd` | log₁₀ of total seismic energy released |

The event count and maximum magnitude are straightforward. The energy feature
deserves explanation.

**Seismic energy formula:**

```python
# feature_engineering.py — inside add_recent_local_features()
feature_data[f"local_log10_energy_{radius_token}km_past_{days}d"][row_index] = float(
    np.log10(np.nansum(10.0 ** (1.5 * local_magnitudes)))
)
```

Written out explicitly:

```
local_log10_energy = log₁₀( sum( 10^(1.5 × m_i) ) )
```

**Why this formula?** The relationship between seismic magnitude and physical
energy is logarithmic: each unit of magnitude corresponds to about a 31-fold
increase in energy. Summing magnitudes directly would be wrong — two M3 events
do not equal one M4. The formula `10^(1.5 × m)` converts magnitude back to a
proportional energy scale (the standard Richter-to-energy proxy), sums the
energies linearly, then takes log₁₀ of the total to compress the result back
into a manageable range.

In plain terms: `local_log10_energy_50km_past_7d = 5.0` means a total equivalent
energy in the neighborhood 10 times larger than `4.0`. It is sensitive to
whether the recent activity was many small events or one large one.

### Nearest recent event features

These three features look at the single event, within 100 km and within the past
30 days, that is **closest in space** to the current event:

| Feature | What it is |
|---|---|
| `nearest_recent_event_distance_km_past_30d` | How far away (km) that nearest event is |
| `nearest_recent_event_magnitude_past_30d` | What magnitude it was |
| `nearest_recent_event_age_days_past_30d` | How many days ago it occurred |

Together, these three describe the "most immediate seismic neighbor" — which is
often the most informative single data point about the local stress state.

### `local_b_value_50km_3y`

This is the most physics-rich feature in the local group.

**What is the b-value?** In seismology, the Gutenberg-Richter relation says that
earthquake frequencies follow a power law: for every magnitude M event, there
are about 10 times as many events at magnitude M−1. The b-value is the slope of
this relationship. A **higher b-value** means more small events relative to large
ones (typical of regions under tensile stress or with heterogeneous material). A
**lower b-value** means more large events relative to small ones (often seen in
regions approaching a stress release).

The global b-value for the whole catalog is set to `b = 1.0` (used in the η
formula). But the **local** b-value, estimated from the recent seismicity in a
50-km radius over the past 3 years, varies from place to place and over time —
and that variation is predictive.

**The Aki (1965) maximum likelihood estimator:**

```
b = log₁₀(e) / (m_mean − m_min) = 0.4342944819 / (m_mean − m_min)
```

Where:
- `m_mean` is the average magnitude of events in the local 50-km, 3-year window
- `m_min` is the minimum magnitude completeness threshold (fixed at `1.0` in
  the batch path)

```python
# feature_engineering.py — add_recent_local_features()
if len(local_mags) >= 5:
    m_mean = np.mean(local_mags)
    m_min  = 1.0  # completeness threshold
    if m_mean > m_min:
        b_val = 0.4342944819 / (m_mean - m_min)
        local_b_value_50km_3y[row_index] = max(0.3, min(3.0, b_val))
```

**Design decisions to note:**

- **Minimum 5 events required.** Fewer than 5 local events is not enough to
  estimate b-value reliably. If there are fewer than 5, the default `b = 1.0`
  is used. This prevents noisy estimates from tiny samples.
- **Clamped to [0.3, 3.0].** Physical b-values outside this range are almost
  certainly estimation artifacts. The clamp keeps the feature well-behaved for
  the model.
- **3-year window, not 30 days.** The b-value requires enough events to estimate
  reliably. A 30-day window would frequently have fewer than 5 events in a
  50-km radius. Three years gives a stable sample in all but the quietest regions
  of the Philippines.

**Leakage check:** The window is `[event_time − 3 years, event_time)`. The
open right bracket means the event itself is not included. Safe.

---

## Part 9: Group 6 — Physics-Derived Features

**Source:** [`add_advanced_features()`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/feature_engineering.py#L443-L447)
in `feature_engineering.py` — functions of the event's own magnitude and depth,
no catalog lookup.

These two features encode domain knowledge directly. They give the model a
physics anchor that pure data-driven features cannot provide.

### `rupture_depth_attenuation`

**The intuition:** A magnitude 7 earthquake at 5 km depth is far more dangerous
and more likely to trigger shallow aftershocks than a magnitude 7 at 200 km
depth. But the model, if given only `magnitude` and `depth_km` as separate
inputs, has to *learn* this interaction from data — which takes many examples to
do well. We can help it by pre-computing the interaction term ourselves.

**The formula:**

```
rupture_depth_attenuation = magnitude × exp(−depth_km / 50)
```

```python
# feature_engineering.py — add_advanced_features()
df["rupture_depth_attenuation"] = df["magnitude"] * np.exp(-df["depth_km"] / 50.0)
```

The exponential term `exp(−depth_km / 50)` is a decay function with a
**length scale of 50 km**. At depth = 0 km: `exp(0) = 1.0` (full magnitude weight).
At depth = 50 km: `exp(−1) ≈ 0.37` (about 37% of the weight).
At depth = 100 km: `exp(−2) ≈ 0.14`.
At depth = 200 km: `exp(−4) ≈ 0.018`.

So a shallow M7 gives `rupture_depth_attenuation ≈ 7.0`, while a deep M7 at
200 km gives ≈ `0.12`. That is a 60-fold difference for the same raw magnitude —
which is physically correct.

The 50-km length scale reflects that the Philippine crust is roughly 30–50 km
thick, and events below that depth are increasingly decoupled from the surface
stress regime.

**Leakage check:** Uses only `magnitude` and `depth_km` from the event record
itself. No catalog lookup. Safe.

### `baths_law_limit`

**The intuition:** In seismology, Bath's Law (1965) is an empirical observation:
the largest aftershock in a sequence is typically about 1.2 magnitude units below
the mainshock. If the mainshock was M7.0, expect a largest aftershock around M5.8.

We encode this as a feature directly:

```
baths_law_limit = magnitude − 1.2
```

```python
# feature_engineering.py — add_advanced_features()
df["baths_law_limit"] = df["magnitude"] - 1.2
```

**Why this is useful even though it's just `magnitude - 1.2`:** The model could
in principle discover this relationship from data by combining the `magnitude`
feature with a learned constant. But explicitly providing it means:

1. The model doesn't have to waste capacity learning a well-known constant
2. The feature name signals to the model *why* this matters — it is a physics-
   anchored upper bound on expected aftershock magnitude, not just a shifted
   magnitude
3. The target column `max_aftershock_mag_24h` is directly predictable from this
   feature for simple sequences

For events with `magnitude < 1.2`, `baths_law_limit` will be negative — which
is fine. It means Bath's Law predicts no detectable aftershock from such a small
event, which is also correct.

**Leakage check:** Uses only `magnitude` from the event record itself. Safe.

---

## Part 10: Quick-Reference Table — All 65 Features

The columns below are in the exact order they appear in
[`training_dataset_mc_1_0.features.txt`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/training_set/training_dataset_mc_1_0.features.txt).

| # | Feature | Group | Source function | Short description |
|---|---|---|---|---|
| 1 | `magnitude` | Basics | raw catalog | Richter magnitude of this event |
| 2 | `depth_km` | Basics | raw catalog | Depth below surface (km) |
| 3 | `latitude` | Basics | raw catalog | Epicenter latitude (°N) |
| 4 | `longitude` | Basics | raw catalog | Epicenter longitude (°E) |
| 5 | `eta` | Parent/η | `add_parent_features` | Raw nearest-neighbor distance η |
| 6 | `log10_eta` | Parent/η | `add_parent_features` | log₁₀(η) |
| 7 | `log10_rescaled_time` | Parent/η | `rescaled_time_distance` | Magnitude-weighted temporal component of log₁₀η |
| 8 | `log10_rescaled_distance` | Parent/η | `rescaled_time_distance` | Magnitude-weighted spatial component of log₁₀η |
| 9 | `is_strong_link` | Parent/η | `add_parent_features` | 1 if η < η₀ (strong sequence link) |
| 10 | `has_parent` | Parent/η | `add_parent_features` | 1 for all events except the catalog's first |
| 11 | `parent_time_gap_days` | Parent/η | `add_parent_features` | Days elapsed since the parent event |
| 12 | `parent_distance_km` | Parent/η | `add_parent_features` | Surface distance to parent (km) |
| 13 | `parent_magnitude` | Parent/η | `add_parent_features` | Magnitude of the parent event |
| 14 | `parent_depth_km` | Parent/η | `add_parent_features` | Depth of the parent's hypocenter (km) |
| 15 | `event_year` | Time | `add_time_features` | Calendar year |
| 16 | `event_month` | Time | `add_time_features` | Calendar month (1–12) |
| 17 | `event_dayofyear` | Time | `add_time_features` | Day of year (1–366) |
| 18 | `event_hour` | Time | `add_time_features` | Hour of day (0–23) |
| 19 | `event_weekday` | Time | `add_time_features` | Day of week (0=Mon, 6=Sun) |
| 20 | `events_past_1d` | Global activity | `add_recent_global_features` | Catalog-wide event count, last 24 hours |
| 21 | `local_events_10km_past_1d` | Local activity | `add_recent_local_features` | Events within 10 km, last 1 day |
| 22 | `local_max_mag_10km_past_1d` | Local activity | `add_recent_local_features` | Max magnitude within 10 km, last 1 day |
| 23 | `local_log10_energy_10km_past_1d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 10 km, last 1 day |
| 24 | `local_events_25km_past_1d` | Local activity | `add_recent_local_features` | Events within 25 km, last 1 day |
| 25 | `local_max_mag_25km_past_1d` | Local activity | `add_recent_local_features` | Max magnitude within 25 km, last 1 day |
| 26 | `local_log10_energy_25km_past_1d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 25 km, last 1 day |
| 27 | `local_events_50km_past_1d` | Local activity | `add_recent_local_features` | Events within 50 km, last 1 day |
| 28 | `local_max_mag_50km_past_1d` | Local activity | `add_recent_local_features` | Max magnitude within 50 km, last 1 day |
| 29 | `local_log10_energy_50km_past_1d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 50 km, last 1 day |
| 30 | `local_events_100km_past_1d` | Local activity | `add_recent_local_features` | Events within 100 km, last 1 day |
| 31 | `local_max_mag_100km_past_1d` | Local activity | `add_recent_local_features` | Max magnitude within 100 km, last 1 day |
| 32 | `local_log10_energy_100km_past_1d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 100 km, last 1 day |
| 33 | `events_past_7d` | Global activity | `add_recent_global_features` | Catalog-wide event count, last 7 days |
| 34 | `local_events_10km_past_7d` | Local activity | `add_recent_local_features` | Events within 10 km, last 7 days |
| 35 | `local_max_mag_10km_past_7d` | Local activity | `add_recent_local_features` | Max magnitude within 10 km, last 7 days |
| 36 | `local_log10_energy_10km_past_7d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 10 km, last 7 days |
| 37 | `local_events_25km_past_7d` | Local activity | `add_recent_local_features` | Events within 25 km, last 7 days |
| 38 | `local_max_mag_25km_past_7d` | Local activity | `add_recent_local_features` | Max magnitude within 25 km, last 7 days |
| 39 | `local_log10_energy_25km_past_7d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 25 km, last 7 days |
| 40 | `local_events_50km_past_7d` | Local activity | `add_recent_local_features` | Events within 50 km, last 7 days |
| 41 | `local_max_mag_50km_past_7d` | Local activity | `add_recent_local_features` | Max magnitude within 50 km, last 7 days |
| 42 | `local_log10_energy_50km_past_7d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 50 km, last 7 days |
| 43 | `local_events_100km_past_7d` | Local activity | `add_recent_local_features` | Events within 100 km, last 7 days |
| 44 | `local_max_mag_100km_past_7d` | Local activity | `add_recent_local_features` | Max magnitude within 100 km, last 7 days |
| 45 | `local_log10_energy_100km_past_7d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 100 km, last 7 days |
| 46 | `events_past_30d` | Global activity | `add_recent_global_features` | Catalog-wide event count, last 30 days |
| 47 | `local_events_10km_past_30d` | Local activity | `add_recent_local_features` | Events within 10 km, last 30 days |
| 48 | `local_max_mag_10km_past_30d` | Local activity | `add_recent_local_features` | Max magnitude within 10 km, last 30 days |
| 49 | `local_log10_energy_10km_past_30d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 10 km, last 30 days |
| 50 | `local_events_25km_past_30d` | Local activity | `add_recent_local_features` | Events within 25 km, last 30 days |
| 51 | `local_max_mag_25km_past_30d` | Local activity | `add_recent_local_features` | Max magnitude within 25 km, last 30 days |
| 52 | `local_log10_energy_25km_past_30d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 25 km, last 30 days |
| 53 | `local_events_50km_past_30d` | Local activity | `add_recent_local_features` | Events within 50 km, last 30 days |
| 54 | `local_max_mag_50km_past_30d` | Local activity | `add_recent_local_features` | Max magnitude within 50 km, last 30 days |
| 55 | `local_log10_energy_50km_past_30d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 50 km, last 30 days |
| 56 | `local_events_100km_past_30d` | Local activity | `add_recent_local_features` | Events within 100 km, last 30 days |
| 57 | `local_max_mag_100km_past_30d` | Local activity | `add_recent_local_features` | Max magnitude within 100 km, last 30 days |
| 58 | `local_log10_energy_100km_past_30d` | Local activity | `add_recent_local_features` | log₁₀ of total seismic energy within 100 km, last 30 days |
| 59 | `nearest_recent_event_distance_km_past_30d` | Local activity | `add_recent_local_features` | Distance to nearest event within 100 km, last 30 days (km) |
| 60 | `nearest_recent_event_magnitude_past_30d` | Local activity | `add_recent_local_features` | Magnitude of that nearest event |
| 61 | `nearest_recent_event_age_days_past_30d` | Local activity | `add_recent_local_features` | Age (days) of that nearest event |
| 62 | `rupture_depth_attenuation` | Physics | `add_advanced_features` | magnitude × exp(−depth_km / 50) |
| 63 | `seis_traffic_ratio_30d` | Global activity | `add_recent_global_features` | events_past_30d / avg_monthly_count_over_5y |
| 64 | `baths_law_limit` | Physics | `add_advanced_features` | magnitude − 1.2 (expected max aftershock magnitude) |
| 65 | `local_b_value_50km_3y` | Local activity | `add_recent_local_features` | Aki MLE b-value, 50-km radius, 3-year window |

---

## Appendix: Key Terms at a Glance

| Term | Plain meaning |
|---|---|
| **η (eta)** | The nearest-neighbor distance between an event and its parent. Small = closely related. Large = coincidental. |
| **η₀ (eta-zero)** | The threshold that separates strong (real) links from weak (coincidental) links. |
| **Parent event** | The earlier earthquake that minimizes η for the current event. |
| **Train/serve skew** | When features computed at training time differ from features computed at serving time — a silent model failure. |
| **Data leakage** | Using future information to compute a feature. Produces artificially good evaluation scores but fails in deployment. |
| **b-value** | The Gutenberg-Richter slope describing how earthquake frequency scales with magnitude. Typically ~1.0. |
| **Bath's Law** | Empirical rule: the largest aftershock is ~1.2 magnitude units below the mainshock. |
| **Haversine formula** | Trigonometric formula for computing the surface distance between two latitude/longitude points on a sphere. |
| **Bounding box pre-filter** | A fast rectangular lat/lon filter applied before Haversine distance, to reduce the candidate set and speed up computation. |
| **Seismic energy proxy** | 10^(1.5 × magnitude) — a proportional energy scale used to sum energy contributions from multiple events correctly. |
| **Aki (1965) MLE** | Maximum likelihood estimator for the b-value: b = 0.4342944819 / (m_mean − m_min). |
| **Fractal dimension (d_f)** | A number (1.6 by default) describing how earthquake epicenters are distributed in space. Used in the η formula. |
| **q (rescale parameter)** | Split weight (0.5) that divides log₁₀η equally between its temporal and spatial components. |
