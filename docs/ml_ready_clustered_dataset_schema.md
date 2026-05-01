# ML-Ready Clustered Dataset Schema After Zaliapin & Ben-Zion-Style Clustering

**Audience:** AI coding assistant / implementation agent (Codex, Claude, or similar)

**Scope:** This guide describes which columns may be created after running the clustering algorithm described in the provided Zaliapin & Ben-Zion (2013a) documents, and which additional ML-oriented features are only implementation extensions.

**Strict grounding rule:** Do not treat any field as paper-specified unless it is directly supported by the provided documents. Fields marked as **extension** are not directly specified as output columns in the provided documents and must be verified before implementation.

---

## 1. Source Dataset Columns Observed

The uploaded PHIVOLCS CSV has these columns:

```text
Date-Time
Latitude
Longitude
Depth
Magnitude
Location
Month
Year
```

These are sufficient for the algorithm inputs described in the provided documents:

- origin time `t_i`
- latitude and longitude for epicentral surface distance
- depth, although the 2013a main analysis ignores depth and uses surface distance between epicenters
- magnitude `m_i`

---

## 2. Required Pre-Clustering Normalized Columns

Create these before clustering so the algorithm can run consistently.

| Column | Type | Status | Meaning | Verification / rule |
|---|---:|---|---|---|
| `event_id` | string/int | implementation-required | Stable unique row identifier. | Not explicitly named in the documents, but needed to store parent and cluster references. |
| `origin_time` | datetime | supported input normalization | Parsed version of `Date-Time`. | Required because the algorithm uses event time `t_i`. |
| `origin_time_years` | float | supported input normalization | Origin time expressed in years or fractional years. | The provided document says time is expressed in years. |
| `latitude` | float | supported input normalization | Renamed/normalized `Latitude`. | Algorithm input. |
| `longitude` | float | supported input normalization | Renamed/normalized `Longitude`. | Algorithm input. |
| `depth_km` | float | retained input | Renamed/normalized `Depth`. | Keep for traceability, but do not use in the 2013a main distance calculation unless intentionally extending the method. |
| `magnitude` | float | supported input normalization | Renamed/normalized `Magnitude`. | Algorithm input. |
| `location_text` | string | retained metadata | Original `Location`. | Useful metadata, not part of the clustering formula. |
| `month` | string/int | retained metadata | Original `Month`. | Not part of clustering formula. |
| `year` | int | retained metadata | Original `Year`. | Not part of clustering formula. |

---

## 3. Direct Algorithm Output Columns

These columns are directly supported by the provided documents as outputs or necessary post-processing results.

| Column | Type | Status | Meaning |
|---|---:|---|---|
| `parent_id` | string/int/null | directly supported | ID of the nearest-neighbor predecessor, equivalent to `parent[k]`. Null for the first event or events where no valid earlier event exists after filtering. |
| `eta` | float/null | directly supported | Nearest-neighbor distance `eta[k]`, minimized over all earlier events. |
| `log10_eta` | float/null | directly supported diagnostic / implementation field | Log-transformed nearest-neighbor distance. The documents use `log10 eta` for threshold selection and diagnostics. |
| `is_strong_link` | bool | directly supported | `true` when `eta < eta_0`; `false` when `eta >= eta_0`. |
| `link_type` | categorical | directly supported | `strong` or `weak`, derived from the threshold rule. |
| `cluster_id` | string/int | directly supported | Connected component ID after weak links are cut from the spanning tree. |
| `event_role` | categorical | directly supported | One of `single`, `mainshock`, `foreshock`, or `aftershock`. |

Allowed values:

```text
event_role in {single, mainshock, foreshock, aftershock}
link_type in {strong, weak}
```

---

## 4. Cluster / Family Columns That Are Safe to Attach Per Row

These are derived from the documented cluster definitions. They are not always listed as row-level output columns, but they are directly implied by the documented rules for clusters, singles, families, and event labels.

| Column | Type | Status | Meaning | How to derive |
|---|---:|---|---|---|
| `cluster_type` | categorical | derived from supported definitions | `single` or `family`. | If cluster size is 1, `single`; if cluster size >= 2, `family`. |
| `cluster_size` | int | supported diagnostic / derived | Number of events in the cluster. | Count rows with same `cluster_id`. |
| `is_single` | bool | derived from supported label | Whether `event_role == 'single'`. | Directly from label. |
| `is_family_member` | bool | derived from supported cluster type | Whether event belongs to a multi-event family. | `cluster_size >= 2`. |
| `mainshock_id` | string/int/null | derived from supported family rule | Mainshock ID for the event's family. | For each family, choose largest magnitude; break ties by earliest time. For singles, use null or self consistently. |
| `mainshock_time` | datetime/null | derived from supported family rule | Origin time of the family mainshock. | Copy from the selected mainshock event. |
| `mainshock_magnitude` | float/null | derived from supported family rule | Magnitude of the family mainshock. | Copy from the selected mainshock event. |
| `foreshock_count_in_family` | int | supported diagnostic / derived | Count of foreshocks in the same family. | Count rows in cluster with `event_role == 'foreshock'`. |
| `aftershock_count_in_family` | int | supported diagnostic / derived | Count of aftershocks in the same family. | Count rows in cluster with `event_role == 'aftershock'`. |

Implementation note: For single-event clusters, choose one convention and keep it consistent:

```text
Option A: mainshock_id = null for singles
Option B: mainshock_id = event_id for singles
```

The documents characterize singles as single-event trees / background-standalone events. They do not prescribe the storage convention for `mainshock_id` on singles.

---

## 5. Recommended ML-Ready Clustered Dataset Schema

Use this as the default post-clustering dataset schema.

```text
event_id
origin_time
origin_time_years
latitude
longitude
depth_km
magnitude
location_text
month
year

parent_id
eta
log10_eta
is_strong_link
link_type

cluster_id
cluster_type
cluster_size
event_role
is_single
is_family_member

mainshock_id
mainshock_time
mainshock_magnitude
foreshock_count_in_family
aftershock_count_in_family
```

---

## 6. Suggested Meaningful ML Features: Verification Required

The following features may be useful for machine learning, but they are **not directly specified as output columns in the provided documents**. They must be treated as implementation extensions.

Do not create these blindly. First verify that each feature is computable from existing post-clustering columns and that it is appropriate for the ML task.

### Applicability Legend

```text
APPLICABLE_EXTENSION = Can be computed from documented quantities, but is not a documented output column.
NOT_DIRECTLY_SUPPORTED = Not specified by the documents and requires a separate project/model definition.
```

| Suggested feature | Status | Applicability check before applying | Safe derivation if applicable |
|---|---|---|---|
| `distance_to_mainshock_km` | APPLICABLE_EXTENSION | Only if `mainshock_id` exists and the event belongs to a family or a chosen single-event convention exists. | Surface epicentral distance between event and its family mainshock. Use the same surface-distance convention used for `r_ij`; do not use depth unless intentionally extending the method. |
| `time_since_mainshock_days` | APPLICABLE_EXTENSION | Only if `mainshock_time` exists. For foreshocks, value will be negative if computed as `event_time - mainshock_time`; decide whether that is allowed. | `(origin_time - mainshock_time)` converted to days. |
| `abs_time_from_mainshock_days` | APPLICABLE_EXTENSION | Use only if the model needs unsigned temporal separation. | `abs(time_since_mainshock_days)`. |
| `magnitude_difference_from_mainshock` | APPLICABLE_EXTENSION | Only if `mainshock_magnitude` exists. Decide sign convention before implementation. | Recommended convention: `mainshock_magnitude - magnitude`, so aftershocks/foreshocks smaller than mainshock have positive values. |
| `days_since_parent` | APPLICABLE_EXTENSION | Only if `parent_id` exists and parent row can be joined. Null for first event / no parent. | `(origin_time - parent_origin_time)` converted to days. This is based on the documented `t_ij` concept, but the column itself is not a specified output. |
| `distance_to_parent_km` | APPLICABLE_EXTENSION | Only if `parent_id` exists and parent row can be joined. Null for first event / no parent. | Surface epicentral distance between event and parent. This is based on the documented `r_ij` concept, but the column itself is not a specified output. |
| `parent_magnitude` | APPLICABLE_EXTENSION | Only if `parent_id` exists and parent row can be joined. | Parent event's magnitude. This is related to the pairwise formula using earlier-event magnitude `m_i`, but the standalone column is not a specified output. |
| `eta_rank_within_cluster` | APPLICABLE_EXTENSION | Only if `eta` exists and ranking is useful for the ML task. | Rank events by `eta` within each `cluster_id`. Not specified in documents. |
| `is_aftershock` | APPLICABLE_EXTENSION | Only if creating a binary ML target from the documented label. | `event_role == 'aftershock'`. This is a recoding of the documented label, not a new paper output. |
| `is_mainshock` | APPLICABLE_EXTENSION | Only if creating a binary target or auxiliary feature from the documented label. | `event_role == 'mainshock'`. |
| `is_foreshock` | APPLICABLE_EXTENSION | Only if creating a binary target or auxiliary feature from the documented label. | `event_role == 'foreshock'`. |
| `is_background_standalone` | APPLICABLE_EXTENSION | Only if mapping `single` to background/standalone. | `event_role == 'single'`. |
| `aftershock_probability` | NOT_DIRECTLY_SUPPORTED | Do not create from the clustering algorithm alone. The provided documents output labels and clusters, not probabilities. | Requires a separately defined ML model, calibration method, or probabilistic forecasting method outside the provided documents. |
| `risk_level` | NOT_DIRECTLY_SUPPORTED | Do not create from the clustering algorithm alone. The provided documents do not define Low/Medium/High risk levels. | Requires a separate project-specific rule, thresholding scheme, or model output. |

---

## 7. Required Verification Gates Before Applying Extension Features

An AI coding assistant must run these checks before adding any extension feature.

### Gate 1: Confirm direct clustering outputs exist

Required columns:

```text
event_id
origin_time
latitude
longitude
magnitude
parent_id
eta
cluster_id
event_role
```

If any of these are missing, do not compute extension features yet.

### Gate 2: Confirm mainshock fields are available before mainshock-relative features

Required for mainshock-relative features:

```text
mainshock_id
mainshock_time
mainshock_magnitude
```

Needed for:

```text
distance_to_mainshock_km
time_since_mainshock_days
abs_time_from_mainshock_days
magnitude_difference_from_mainshock
```

If the event is a `single`, use the chosen convention consistently:

```text
mainshock fields null for singles
```

or

```text
mainshock fields point to self for singles
```

Do not mix both conventions.

### Gate 3: Confirm parent joins before parent-relative features

Required for parent-relative features:

```text
parent_id
parent origin_time
parent latitude
parent longitude
parent magnitude
```

Needed for:

```text
days_since_parent
distance_to_parent_km
parent_magnitude
```

For the first event or events with no parent, output null.

### Gate 4: Keep surface-distance convention consistent

The provided documents say the 2013a main analysis uses surface distance between epicenters and ignores depth. Therefore:

```text
Use latitude/longitude surface distance for distance_to_parent_km and distance_to_mainshock_km.
Do not include depth in these distances unless you explicitly mark it as a project-specific extension.
```

### Gate 5: Do not invent probabilities or risk levels

The clustering documents do not define:

```text
aftershock_probability
risk_level
Low / Medium / High thresholds
```

Therefore, do not generate these columns from the clustering algorithm alone. They can only be added after a separate model, rule, calibration method, or project specification defines them.

---

## 8. Implementation Notes for Coding Assistants

### 8.1 Do not confuse `parent_id` with `mainshock_id`

`parent_id` is the nearest-neighbor predecessor selected by minimum `eta` among earlier events. It is not necessarily the mainshock.

`mainshock_id` is the largest-magnitude event in a multi-event family, with earliest time used as the tie-breaker.

### 8.2 Do not treat weak parent links as cluster membership links

Every event except the first can have a nearest-neighbor parent before thresholding. But cluster membership is determined only after weak links are cut.

Correct sequence:

```text
1. Compute nearest-neighbor parent and eta.
2. Choose eta_0 from the log10_eta distribution.
3. Mark links as strong or weak.
4. Cut weak links.
5. Build connected components / spanning forest.
6. Assign cluster_id.
7. Assign event_role.
8. Only then compute optional ML extension features.
```

### 8.3 Do not use `eta_0 = 1e-5` blindly

The provided documents report `eta_0 approx 1e-5` for the southern California example, but state that other regions require inspecting the local `log10_eta` histogram or fitting the threshold. For PHIVOLCS / Philippines data, choose `eta_0` from the dataset, not by copying the southern California value.

### 8.4 Optional diagnostic fields

These are allowed for diagnostics but are not core labels:

```text
T
R
log10_T
log10_R
```

The documents state that `T` and `R` are for visualization and are not involved in cluster identification.

---

## 9. Minimal Output Contract

A correct clustered dataset must at least contain:

```text
event_id
origin_time
latitude
longitude
magnitude
parent_id
eta
log10_eta
link_type
cluster_id
event_role
```

A more ML-ready clustered dataset should additionally contain:

```text
cluster_type
cluster_size
mainshock_id
mainshock_time
mainshock_magnitude
foreshock_count_in_family
aftershock_count_in_family
```

Extension features may be added only after passing the verification gates above.

---

## 10. Non-Negotiable Constraints

- Do not invent output columns as if they were specified by the paper.
- Do not generate `aftershock_probability` from labels alone.
- Do not generate `risk_level` without a separately defined rule/model.
- Do not use depth in the main clustering distance unless explicitly implementing a project-specific extension.
- Do not assign mainshock by earliest event; assign it by largest magnitude, with earliest time only as tie-breaker.
- Do not treat parent-child links as final family links until weak links have been cut.
- Do not assume the southern California threshold applies to PHIVOLCS data.

---

## 11. Summary

Directly supported algorithm outputs:

```text
parent_id
eta
log10_eta
link_type / is_strong_link
cluster_id
event_role
```

Safely derived cluster/family fields:

```text
cluster_type
cluster_size
mainshock_id
mainshock_time
mainshock_magnitude
foreshock_count_in_family
aftershock_count_in_family
```

Useful but extension-only ML features:

```text
distance_to_mainshock_km
time_since_mainshock_days
magnitude_difference_from_mainshock
days_since_parent
distance_to_parent_km
parent_magnitude
```

Not supported by the provided documents without a separate model/specification:

```text
aftershock_probability
risk_level
```
