# Zaliapin-Ben-Zion-Style C++ Clustering Plan

This plan is based only on:

- `dataset/phivolcs_earthquake_2018_2026.csv`
- `docs/zaliapin-ben-zion-2013a-algorithm.md`
- `docs/zaliapin-ben-zion-conceptual-guide.md`
- `docs/ml_ready_clustered_dataset_schema.md`

The implementation will build a C++ pipeline that creates an ML-ready clustered dataset after the required prerequisites are chosen from PHIVOLCS diagnostics. The algorithm must not assume Southern California parameter values where the documents say PHIVOLCS-specific diagnostics are required.

## Agreed Decisions

- Milestone 1 only generates diagnostics needed to choose `m_c`.
- Milestone 1 does not compute nearest-neighbor links.
- Milestone 1 does not create the final clustered dataset.
- Final clustering starts only after `m_c` is chosen.
- `eta_0` must be chosen from PHIVOLCS `log10_eta` diagnostics after nearest-neighbor distances are computed.
- Single-event clusters use null values for `mainshock_id`, `mainshock_time`, and `mainshock_magnitude`.
- The main clustering distance uses latitude/longitude surface distance and ignores depth.
- Do not create unsupported columns such as `aftershock_probability` or `risk_level`.

## Scope

In scope:

- C++ implementation for parsing, validating, sorting, and normalizing the PHIVOLCS CSV.
- Magnitude diagnostics for selecting `m_c`.
- Nearest-neighbor `parent_id`, `eta`, and `log10_eta` computation after `m_c` is chosen.
- PHIVOLCS-specific diagnostics for selecting `eta_0`.
- Strong/weak link classification after `eta_0` is chosen.
- Union-find spanning forest construction using only strong links.
- Cluster and event-role labeling.
- Recommended ML-ready clustered dataset output schema.

Out of scope:

- Probabilistic aftershock prediction.
- Risk level classification.
- Depth-based clustering distance.
- Blind use of `eta_0 = 1e-5` for PHIVOLCS data.
- Extension-only ML features unless separately approved.

## Prerequisite Tasks

1. Generate magnitude diagnostics from `dataset/phivolcs_earthquake_2018_2026.csv`.
2. Choose `m_c` from those diagnostics.
3. Use default `b = 1` and `d_f = 1.6` unless PHIVOLCS-specific estimates are computed first.
4. After `m_c` is chosen, compute nearest-neighbor `log10_eta`.
5. Choose `eta_0` from the PHIVOLCS `log10_eta` distribution using histogram inspection or GMM/EM diagnostics.

## Milestone 1: `m_c` Diagnostics Only

1. Read `dataset/phivolcs_earthquake_2018_2026.csv`.
2. Validate required fields:
   - `Date-Time`
   - `Latitude`
   - `Longitude`
   - `Depth`
   - `Magnitude`
   - `Year`
3. Parse and normalize:
   - `event_id`
   - `origin_time`
   - `latitude`
   - `longitude`
   - `depth_km`
   - `magnitude`
   - `location_text`
   - `month`
   - `year`
4. Sort rows by parsed `origin_time`.
5. Generate magnitude diagnostics needed to choose `m_c`:
   - event count by magnitude bin
   - cumulative count by magnitude threshold
   - yearly event counts by candidate magnitude cutoff
   - missing or invalid parse report
6. Write diagnostic outputs:
   - `outputs/mc_diagnostics/magnitude_bins.csv`
   - `outputs/mc_diagnostics/magnitude_cutoff_counts.csv`
   - `outputs/mc_diagnostics/yearly_counts_by_magnitude_cutoff.csv`
   - `outputs/mc_diagnostics/input_validation_report.txt`

## Milestone 2: Nearest-Neighbor Diagnostics for `eta_0`

Start this milestone only after `m_c` is chosen.

1. Filter events with `magnitude >= m_c`.
2. Express event time in years or fractional years as required by the algorithm.
3. Compute surface epicentral distance in kilometers from latitude/longitude.
4. Ignore depth in the main distance calculation.
5. For every later event `j`, find the earlier event `i` that minimizes:

```text
log10_eta = log10(t_ij) + d_f * log10(r_ij) - b * m_i
```

6. Output nearest-neighbor diagnostics:
   - `event_id`
   - `parent_id`
   - `eta`
   - `log10_eta`
7. Generate histogram-ready `log10_eta` diagnostics for choosing `eta_0`.
8. Optionally generate `(log10_T, log10_R)` diagnostics using `q = 0.5`, because the documents say this is for visualization and not for cluster identification.

## Milestone 3: Thresholding and Spanning Forest

Start this milestone only after `eta_0` is chosen.

1. Classify each parent link:
   - `strong` when `eta < eta_0`
   - `weak` when `eta >= eta_0`
2. Use union-find to build clusters from strong links only.
3. Assign:
   - `cluster_id`
   - `cluster_type`
   - `cluster_size`
   - `is_family_member`
   - `is_single`

## Milestone 4: Event Role Labeling

1. For single-event clusters, assign:
   - `event_role = single`
   - `mainshock_id = null`
   - `mainshock_time = null`
   - `mainshock_magnitude = null`
2. For family clusters, choose the mainshock as:
   - largest magnitude in the family
   - earliest time as tie-breaker if magnitudes are equal
3. Label family events:
   - mainshock event as `mainshock`
   - events before the mainshock as `foreshock`
   - events after the mainshock as `aftershock`
4. Compute per-family counts:
   - `foreshock_count_in_family`
   - `aftershock_count_in_family`

## Milestone 5: ML-Ready Clustered Dataset

Emit the recommended schema:

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

## Validation Gates

1. Confirm required input columns exist.
2. Confirm required numeric and datetime fields parse.
3. Confirm `m_c` was chosen before nearest-neighbor computation.
4. Confirm `eta_0` was chosen before final clustering.
5. Confirm weak links are not used for cluster membership.
6. Confirm `parent_id` is not treated as `mainshock_id`.
7. Confirm every family has exactly one mainshock.
8. Confirm all `event_role` values are one of:
   - `single`
   - `mainshock`
   - `foreshock`
   - `aftershock`
9. Confirm singles have null mainshock fields.
10. Confirm no unsupported probability or risk columns are created.

