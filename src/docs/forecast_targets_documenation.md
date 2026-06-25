# Training Document: Building the Forecast Targets (Labeling)
> **Who this is for:** Junior developers on the QuakestrikePH team. No ML or
> seismology background assumed.
>
> **Read this after:** `training_feature_engineering.md` — this document covers
> the second half of `build_training_dataset.py`: how we define what the model
> is trying to predict, and why the target design was made the way it was.
>
> **Key files:**
> - [`build_training_dataset.py`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/build_training_dataset.py) — the script that produces the training CSV
> - [`training_dataset_mc_1_0.targets.txt`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/training_set/training_dataset_mc_1_0.targets.txt) — the saved list of all target column names

---

## How to Read This Document

1. **The labeling question** — what exactly are we asking the model to learn?
2. **The forecast window** — why 24 hours?
3. **How labeling works** — the algorithm that assigns targets to each event
4. **Why only events in aftershock clusters get non-zero targets**
5. **The spatial zone target** — the main classification output, explained in full
6. **The distance targets** — nearest, median, p90, and why max was dropped
7. **The magnitude target** — what it predicts and its current limitation
8. **Design decisions explained** — cumulative vs. disjoint bins, spatial zone vs. independent flags
9. **The full target reference** — all 10 targets in one table
10. **What a labeled row looks like** — a concrete example

---

## Part 1: The Labeling Question

After all the features are computed for each earthquake (see
`training_feature_engineering.md`), the model still needs to know: **for this
event, what actually happened in the next 24 hours?**

This is the **labeling** step. We look forward in time from each event in the
catalog, check what happened in the following 24-hour window, and attach those
observations as target columns. The model later trains to predict these targets
from the features alone — without looking at the future.

The targets answer questions like:

- Did any aftershock occur?
- If so, how close was the nearest one?
- How many were within 10 km? 25 km? 50 km?
- What was the biggest aftershock?
- Where did most of them land (in what distance band)?

> [!IMPORTANT]
> Labels are computed from the **clustered dataset only**. We only look for
> aftershocks *within the same cluster* as the trigger event. This is intentional:
> an earthquake in a different cluster is, by definition, not causally linked to
> our event. We are not asking "did any earthquake happen nearby?" — we are
> asking "did this specific event produce aftershocks?"

---

## Part 2: The Forecast Window

The forecast window is **24 hours** from the event's origin time.

```python
# build_training_dataset.py
FORECAST_HOURS = 24
forecast_days = forecast_hours / 24.0  # = 1.0 day
```

**Why 24 hours?**

- It is the operationally most useful window for public disaster response and
  emergency planning. The first 24 hours after a large earthquake are when the
  risk of damaging aftershocks is highest (Omori's Law: aftershock rate decays
  as a power law after the mainshock).
- It is a natural human planning unit — emergency coordinators think in days,
  not hours or weeks.
- Longer windows (72h, 1 week) can be added as future targets, but the model
  must be trained and evaluated separately for each window. The current design
  does not mix forecast windows.

---

## Part 3: How Labeling Works — The Algorithm

The labeling happens in the `add_forecast_targets()` function in
[`build_training_dataset.py`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/scripts/build_training_dataset.py).

### Step 1: Find which clusters contain aftershocks

The function first identifies all `cluster_id` values that contain at least one
event with `event_role = "aftershock"`. Only events in these clusters are
considered when assigning non-zero labels.

```python
# build_training_dataset.py — add_forecast_targets()
aftershock_clusters = set(
    df.loc[
        df["event_role"].astype(str).str.lower().eq("aftershock"),
        "cluster_id",
    ]
)
candidate_df = df[df["cluster_id"].isin(aftershock_clusters)]
```

This filters out all singleton clusters (singles) and all families that happen
to have no aftershocks (mainshock-only families, mainshock+foreshock families).
For those events, every target stays at its default: `0` for binary flags and
`NaN` for distance/magnitude estimates.

### Step 2: Process each cluster

For each cluster that has aftershocks, we sort its members by time and scan
forward from each member's position:

```python
for _, group in candidate_df.groupby("cluster_id", sort=False):
    group = group.sort_values("event_time")
    times = group["event_time"].to_numpy(dtype="datetime64[ns]")
    ...
    for position, original_index in enumerate(group_indices):
        # Find the window: from just after this event to +24h
        start = np.searchsorted(times, times[position], side="right")
        end = np.searchsorted(
            times,
            times[position] + np.timedelta64(int(forecast_days * 86400), "s"),
            side="right",
        )
```

`np.searchsorted` efficiently finds which positions in the sorted time array
fall within the 24-hour window after the current event. This is fast because
the array is already sorted.

### Step 3: Check for aftershocks in the window

Within the window `[start, end)`, we look only at events whose `event_role` is
`"aftershock"`:

```python
future_positions = aftershock_positions[
    (aftershock_positions >= start) & (aftershock_positions < end)
]
if len(future_positions) == 0:
    continue  # no aftershock in the 24h window → all targets remain 0/NaN
```

If there ARE aftershocks in the window, we compute the surface distance from
the current event's epicenter to each of them (using the same Haversine formula
from `feature_engineering.py`), and then assign all the targets.

---

## Part 4: Why Only Same-Cluster Events Count

This is the most important design decision in the labeling logic, and it is
worth understanding deeply.

**Scenario:** An M5.0 earthquake happens in Manila Bay. Thirty minutes later,
an M3.2 earthquake happens 400 km away in Mindanao. Is the M3.2 an "aftershock"
of the M5.0 for labeling purposes?

**The answer is no** — and the code enforces this because we only look inside
the same cluster. The Zaliapin–Ben-Zion clustering already decided that the M3.2
is either in a different cluster or is a standalone single. Including it in the
label would be noise: the model would learn to predict aftershocks from
seismically unrelated events, which is meaningless.

**What this means for singles and background events:** A `single` (standalone
background event) can never produce aftershocks in our labeling scheme, because
singles form their own one-event cluster by definition. Their 24-hour targets
will always be 0. In practice, this is correct — singles are background events
with no detected causal relationship to other earthquakes.

**What this means for mainshocks:** A mainshock in a family CAN have aftershocks
within its cluster (in fact, that is what makes it a mainshock). So mainshocks
are the primary rows that get non-zero labeling. Foreshocks and earlier members
of a sequence can also get non-zero labels if a later event in the same cluster
falls in their 24-hour window.

---

## Part 5: The Spatial Zone Target (The Main Output)

The most important target is:

```
aftershock_spatial_zone_24h
```

This is a **multiclass classification target** — a single number that encodes
both whether an aftershock happened AND where it landed:

| Value | Meaning |
|---|---|
| `0` | No aftershock in the next 24h |
| `1` | Nearest aftershock was within 10 km |
| `2` | Nearest aftershock was 10–25 km away |
| `3` | Nearest aftershock was 25–50 km away |
| `4` | Nearest aftershock was more than 50 km away |

```python
# build_training_dataset.py
target_spatial_zone = np.zeros(len(df), dtype=np.int8)
has_aftershock = target_aftershock == 1
nearest = target_nearest_distance

target_spatial_zone[has_aftershock & (nearest <= 10.0)] = 1
target_spatial_zone[has_aftershock & (nearest > 10.0) & (nearest <= 25.0)] = 2
target_spatial_zone[has_aftershock & (nearest > 25.0) & (nearest <= 50.0)] = 3
target_spatial_zone[has_aftershock & (nearest > 50.0)] = 4
```

### Why one multiclass target instead of five independent binary targets?

The model was originally designed with five separate binary targets — one for
each distance band. This caused a problem: the five models could produce
**incoherent probabilities** at serving time. For example:

- `aftershock_24h = 0.85` (85% chance of any aftershock)
- `aftershock_within_50km_24h = 0.30` (30% chance within 50 km)

But 50 km contains ALL closer bands. If 85% of aftershocks exist and 30% are
within 50 km, the probabilities imply 55% of aftershocks happen beyond 50 km —
which may not match the `aftershock_beyond_50km` model's output. The results
contradict each other.

A single multiclass model trained on `aftershock_spatial_zone_24h` avoids this:
**all five probability outputs are derived from one model's softmax distribution**,
so by construction they always sum to 1 and the containment order is preserved.

### How the serving probabilities are derived from the zone target

At inference time, the model outputs a softmax probability for each zone (0–4).
The public-facing probabilities are then:

```
aftershock_24h             = P(zone=1) + P(zone=2) + P(zone=3) + P(zone=4)
aftershock_within_10km_24h = P(zone=1)
aftershock_within_25km_24h = P(zone=1) + P(zone=2)
aftershock_within_50km_24h = P(zone=1) + P(zone=2) + P(zone=3)
aftershock_beyond_50km_24h = P(zone=4)
```

These are **always consistent** with each other because they all come from the
same probability distribution.

---

## Part 6: The Distance Targets

Three regression targets describe the spatial spread of the aftershock cloud:

| Target | What it measures |
|---|---|
| `nearest_aftershock_distance_km_24h` | Distance to the single closest aftershock in the 24h window |
| `median_aftershock_distance_km_24h` | Median distance across all aftershocks in the window |
| `p90_aftershock_distance_km_24h` | 90th-percentile distance — i.e., 90% of aftershocks were closer than this |

```python
# build_training_dataset.py
target_nearest_distance[original_index] = float(np.nanmin(distances))
target_median_distance[original_index] = float(np.nanmedian(distances))
target_p90_distance[original_index] = float(np.nanpercentile(distances, 90))
```

These targets are `NaN` for events with no aftershocks in the window.

### Why not the maximum distance?

An earlier version of the design used the **maximum distance** to characterize
the spatial spread. It was dropped. The code comment explains why:

```python
# Robust statistics of the aftershock distance cloud (B). The median
# and p90 are stable; the old max was almost pure tail (p95 ~ 500 km)
# and not learnable.
```

The maximum is driven by extreme outliers. A single aftershock hundreds of
kilometres away (which does occasionally happen in long sequences) would dominate
the max, making it extremely variable and nearly impossible for a tree model to
learn a reliable regression target from. The median and p90 are much more stable
and represent what the typical and near-worst-case spatial spread looks like.

**At serving time**, these three values are reported together as a range:
*"The nearest aftershock is expected at X km, with 90% of aftershocks expected
within Y km."*

---

## Part 7: The Magnitude Target

```
max_aftershock_mag_24h
```

This is the magnitude of the **single largest aftershock** in the 24-hour window:

```python
target_max_magnitude[original_index] = float(np.nanmax(magnitudes[future_positions]))
```

This is `NaN` for events with no aftershocks.

### Why this is the current problem target

As documented in the `massive_earthquakes_modeling_reference.md`, this is the
target that failed catastrophically during the June 2026 Sarangani sequence:

| Event | Predicted | Actual |
|---|---|---|
| M7.8 mainshock | M4.31 | M6.4 |

The magnitude regression target is difficult for tree models to learn at high
magnitudes because the training data contains very few M7+ events. The global
data plan (detailed in the modeling reference) specifically aims to improve this
target.

> [!NOTE]
> `baths_law_limit` (a feature = `magnitude - 1.2`) encodes Bath's Law as an
> input to the model. In contrast, `max_aftershock_mag_24h` is the actual
> observed maximum aftershock — the thing we are trying to predict. Do not
> confuse the feature (a prior estimate) with the target (the ground truth).

---

## Part 8: The Cumulative Containment Targets

These four binary targets answer: *"Was there at least one aftershock within
this radius?"*

| Target | Meaning |
|---|---|
| `aftershock_within_10km_24h` | 1 if any aftershock within 10 km, 0 otherwise |
| `aftershock_within_25km_24h` | 1 if any aftershock within 25 km, 0 otherwise |
| `aftershock_within_50km_24h` | 1 if any aftershock within 50 km, 0 otherwise |
| `aftershock_beyond_50km_24h` | 1 if the nearest aftershock was beyond 50 km, 0 otherwise |

```python
# build_training_dataset.py
CUMULATIVE_RADII_KM = [10.0, 25.0, 50.0]

for radius in CUMULATIVE_RADII_KM:
    within_targets[radius][original_index] = int((distances <= radius).any())
```

### Cumulative vs. disjoint bins — why it matters

**Disjoint bins** (the old design): each bin is a donut ring — "was there an
aftershock between 10 and 25 km?"

**Cumulative containment** (the current design): each bin is a growing circle —
"was there an aftershock within 25 km?" which includes everything within 10 km too.

Cumulative bins are better because:

1. **They are monotone:** P(within 25 km) ≥ P(within 10 km) is always true by
   definition. Disjoint bins have no such guarantee and can produce results where
   the 10–25 km probability is paradoxically higher than the 0–10 km probability.

2. **They are easier to learn:** a cumulative target has many more positives for
   larger radii, giving the model more training signal. A disjoint 10–25 km donut
   is a much smaller region with fewer events.

3. **They are easier to explain to the public:** "70% chance of an aftershock
   within 25 km" is intuitive. "30% chance of an aftershock in the 10–25 km
   ring" is not.

The code comment in the script confirms this was a deliberate redesign:

```python
# Cumulative containment radii (km). Each yields a monotone "is there >=1
# aftershock within R km?" target -- nested, not disjoint donut bins -- so that
# P(within 10) <= P(within 25) <= ... <= P(aftershock). These replace the old
# disjoint distance bins, which were harder to learn and could not be made
# monotone.
```

---

## Part 9: The Full Target Reference

All 10 targets in the training dataset:

| Target column | Type | What it answers | NaN when |
|---|---|---|---|
| `aftershock_spatial_zone_24h` | Integer (0–4) | Which distance zone did the nearest aftershock land in? 0=none, 1=≤10km, 2=10–25km, 3=25–50km, 4=>50km | Never (defaults to 0) |
| `aftershock_24h` | Binary (0/1) | Did any aftershock occur in 24h? | Never (defaults to 0) |
| `aftershock_within_10km_24h` | Binary (0/1) | Was any aftershock within 10 km? | Never (defaults to 0) |
| `aftershock_within_25km_24h` | Binary (0/1) | Was any aftershock within 25 km? | Never (defaults to 0) |
| `aftershock_within_50km_24h` | Binary (0/1) | Was any aftershock within 50 km? | Never (defaults to 0) |
| `aftershock_beyond_50km_24h` | Binary (0/1) | Was the nearest aftershock beyond 50 km? | Never (defaults to 0) |
| `nearest_aftershock_distance_km_24h` | Float (km) | How far was the closest aftershock? | No aftershock in window |
| `median_aftershock_distance_km_24h` | Float (km) | Median distance of all aftershocks | No aftershock in window |
| `p90_aftershock_distance_km_24h` | Float (km) | 90th-percentile distance of aftershocks | No aftershock in window |
| `max_aftershock_mag_24h` | Float | Magnitude of the largest aftershock | No aftershock in window |

---

## Part 10: What a Labeled Row Looks Like

Here is a concrete example of what a single row in the training dataset contains
after both features and targets are attached.

**Scenario:** An M5.2 earthquake at 15 km depth. Over the next 24 hours, two
aftershocks occur in its cluster: M3.1 at 8 km away, and M2.8 at 22 km away.

| Field | Value | Explanation |
|---|---|---|
| `magnitude` | 5.2 | The triggering event's magnitude (feature) |
| `depth_km` | 15.0 | Depth (feature) |
| `baths_law_limit` | 4.0 | 5.2 - 1.2 (feature) |
| `aftershock_24h` | **1** | Yes, aftershocks occurred |
| `aftershock_spatial_zone_24h` | **1** | Nearest was 8 km away → zone 1 (≤10 km) |
| `aftershock_within_10km_24h` | **1** | 8 km ≤ 10 km → yes |
| `aftershock_within_25km_24h` | **1** | 8 km ≤ 25 km → yes |
| `aftershock_within_50km_24h` | **1** | 8 km ≤ 50 km → yes |
| `aftershock_beyond_50km_24h` | **0** | Nearest was 8 km, not beyond 50 |
| `nearest_aftershock_distance_km_24h` | **8.0** | Closest aftershock |
| `median_aftershock_distance_km_24h` | **15.0** | Median of [8, 22] |
| `p90_aftershock_distance_km_24h` | **20.6** | 90th percentile of [8, 22] |
| `max_aftershock_mag_24h` | **3.1** | Largest of M3.1 and M2.8 |

**Now the same M5.2, but no aftershocks in 24h:**

| Field | Value |
|---|---|
| `aftershock_24h` | **0** |
| `aftershock_spatial_zone_24h` | **0** |
| `aftershock_within_10km_24h` | **0** |
| `aftershock_within_25km_24h` | **0** |
| `aftershock_within_50km_24h` | **0** |
| `aftershock_beyond_50km_24h` | **0** |
| `nearest_aftershock_distance_km_24h` | **NaN** |
| `median_aftershock_distance_km_24h` | **NaN** |
| `p90_aftershock_distance_km_24h` | **NaN** |
| `max_aftershock_mag_24h` | **NaN** |

---

## Part 11: The Pipeline in Order

To see how features and targets fit together, here is the complete call sequence
in `build_training_dataset.py`:

```python
# build_training_dataset.py — main()

df = pd.read_csv(args.input_csv)          # load clustered CSV from C++ output
df["event_time"] = parse_origin_time(...)  # parse timestamps

# === FEATURE BUILDING (covered in training_feature_engineering.md) ===
df = add_time_features(df)                 # event_year, month, dayofyear, hour, weekday
df = add_parent_features(df)               # eta, parent_magnitude, parent_distance, etc.
df = add_recent_global_features(df)        # events_past_1d/7d/30d, seis_traffic_ratio_30d
df = add_recent_local_features(df)         # local grids, nearest event, b-value
df = add_advanced_features(df)             # rupture_depth_attenuation, baths_law_limit

# === TARGET LABELING (covered in this document) ===
df = add_forecast_targets(df, args.forecast_hours)   # look 24h forward, assign all targets

# === COLUMN SELECTION AND SAVE ===
training_df, feature_columns, target_columns = select_training_columns(df, ...)
training_df.to_csv(args.output_csv, index=False)
```

Features are computed first from backward-looking data (safe from leakage).
Targets are attached last from forward-looking data (the ground truth the model
learns to predict).

---

## Appendix: Key Terms

| Term | Plain meaning |
|---|---|
| **Forecast window** | The time period (24h) after an event that we look into when assigning labels |
| **Target / label** | What we are asking the model to predict — the "answer" in the training data |
| **Binary target** | A 0 or 1 answer: did it happen or not? |
| **Regression target** | A continuous number: how far? how big? |
| **Multiclass target** | A category number (0–4): which zone? |
| **Cumulative bin** | A growing circle — "within R km" includes all smaller radii |
| **Disjoint bin** | A donut ring — "between R1 and R2 km" excludes smaller radii |
| **NaN** | "Not a number" — the value is missing because it is undefined (e.g., no aftershock → no nearest distance) |
| **Softmax** | A mathematical operation that converts raw model scores into probabilities that sum to 1 |
| **Spatial zone** | The single multiclass target that encodes both whether and where an aftershock happened |
| **Same-cluster constraint** | We only count aftershocks that belong to the same Zaliapin–Ben-Zion cluster as the trigger event |
