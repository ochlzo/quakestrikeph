# Earthquake Declustering — Nearest-Neighbor Algorithm (Zaliapin & Ben-Zion, 2020)

> **Reference paper:** Zaliapin, I., & Ben-Zion, Y. (2020). *Earthquake declustering using the nearest-neighbor approach in space-time-magnitude domain.* J. Geophys. Res.: Solid Earth, 125, e2018JB017120. DOI: `10.1029/2018JB017120`

This document is a language-independent specification of the algorithm for AI coding assistants. It describes **what** the algorithm does and **how** to implement it. The original MATLAB source files (referenced in §10) contain the **exact** numerical recipes — consult them when an implementation choice is ambiguous.

---

## 1. Problem Statement

**Input:** an earthquake catalog `C = {(t_i, x_i, m_i)}` for `i = 1..N`, where:
- `t_i` — origin time (in fractional years, e.g. `1986.1524`)
- `x_i = (lon_i, lat_i, depth_i)` — hypocenter (depth in km; for epicenter-only analysis set all depths to 0)
- `m_i` — magnitude

**Output:** a partition of the catalog into two classes:
- **Background** events (independent / tectonically driven)
- **Clustered** events (aftershocks, foreshocks, swarms — triggered by other events)

The algorithm is **stochastic** (Monte Carlo): each run yields one realization of the partition. Stability comes from agreement across many realizations — typically >75% of events keep the same label in >90% of runs.

---

## 2. Core Concept: Nearest-Neighbor Proximity

For two events `i` (earlier) and `j` (later), the Baiesi–Paczuski proximity is

```
η_ij = t_ij · (r_ij)^d · 10^(-w · m_i)        if  t_ij = t_j - t_i > 0
     = ∞                                      otherwise
```

where:
- `t_ij` — interevent time (years)
- `r_ij` — epicentral / hypocentral distance (km)
- `d`   — fractal dimension of epicenters (≈1.5) or hypocenters (≈2.5)
- `w`   — magnitude weighting; **for declustering use `w = 0`** (this collapses the magnitude term to 1, deflating the attraction domain of large events so background seismicity inside aftershock zones can be recovered)

For each event `j` (after the first), find the unique parent `i < j` minimizing `η_ij`:

```
η_j = min { η_ij : i < j }
```

`η_j` is the **nearest-neighbor proximity** of event `j`. The collection `{η_j}` is bimodal in real catalogs: a low-`η` mode = clustered events, a high-`η` mode = background events. This bimodality is what the algorithm exploits.

> **Implementation tip — efficiency.** A naive O(N²) scan over all earlier events is too slow for large catalogs. Use the candidate-pruning trick from `bp_add_1.m` / `bp_2cat_add_1.m`: estimate an upper bound on the proximity using the 30–50 immediately preceding events, then restrict the parent search to events within a corresponding space–time box. See §10.

> **Numerical floors.** Use `t_ij = max(t_ij, 1 sec)` and `r_ij = max(r_ij, 1 m)` to avoid `log(0)` when events are co-located in time or space.

> **Logarithmic form (preferred).** Implementations work in log space to avoid overflow:
> `log10(η_ij) = log10(t_ij) + d · log10(r_ij) − w · m_i`

---

## 3. The Declustering Algorithm — 4 Steps

The user supplies three parameters: `d` (fractal dimension), `η₀` (initial proximity cutoff), `α₀` (cluster threshold). See §6 for parameter selection.

### Step 1 — Identify the most clustered events

Compute `η_i` for every event in the catalog (using `w = 0`). Form the index set of "uncluttered candidates":

```
J = { i : η_i > η₀ }      (size N₀ ≤ N)
```

`J` is used in Step 2 to estimate the spatial pattern of background activity. `η₀` should sit roughly between the two modes of the histogram of `log10(η)`. Default: `η₀ = 10⁻¹` (use `10⁻²·⁵` for narrow, fault-confined catalogs like Parkfield).

### Step 2 — Estimate location-specific background intensity via reshuffled catalogs

Generate `M` reshuffled catalogs (default `M = 100`), each constructed as follows:

1. Take the spatial locations `{x_j : j ∈ J}` from Step 1.
2. Draw `N₀` uniform random times on `[min(t), max(t)]`, sorted ascending.
3. Randomly permute (a) the spatial locations among themselves and (b) the magnitudes among themselves (independent permutations) before pairing them with the new times.

Each reshuffled catalog `C_k` has:
- A stationary Poisson time component
- The original spatial pattern (preserved up to permutation)
- Independent space and time marginals

For every event `i` in the **original** catalog `C`, compute its nearest-neighbor proximity `κ_{k,i}` **with respect to events in `C_k`** (cross-catalog NN, i = original event seeking parent in reshuffled set; see `bp_2cat_add_1.m`).

Stack across realizations:

```
k_i = (κ_{1,i}, κ_{2,i}, ..., κ_{M,i})
```

The empirical distribution of `k_i` approximates what the NN-proximity would look like at event `i`'s location if seismicity were stationary and unclustered there.

### Step 3 — Normalize the proximity

Define the **normalized log-proximity** for each event `i`:

```
log10(α_i) = log10(η_i) − mean( log10(k_i) )
```

i.e. subtract the mean-log of the bootstrap proximities at that location from the observed log-proximity. Under the null hypothesis of stationarity + space-time independence, `log10(α_i)` has the same distribution at every location and is centered near 0. Clustered events produce strongly negative `log10(α_i)`.

### Step 4 — Random thinning (the actual declustering)

For each event `i`, set the probability that it is retained as background:

```
P_back,i = min( α_i · A₀, 1 )           where A₀ = 10^α₀
```

In log form: event `i` is background iff

```
log10(α_i) + α₀ > log10(U_i)            with U_i ~ Uniform(0, 1)  i.i.d.
```

Equivalently, draw `r ~ Uniform(0,1)` for each `i` and keep `i` as background when `10^(log10(α_i) + α₀) > r`.

Events not selected as background are classified as **clustered**.

> **Why thinning instead of a hard threshold?** A hard threshold on `α_i` produces "holes" — empty space-time regions inside aftershock zones where background events would otherwise be expected. Random thinning probabilistically retains some events in those zones, statistically reconstructing the latent background.

> **Reusable intermediate result.** The expensive part is computing `log10(α_i)` (Steps 1–3). Once stored, you can produce many alternative declustered catalogs at different `α₀` cheaply by just re-running Step 4. This is exactly the workflow in §4 of the source-code description: persist `ad0 = log10(α_i)` and re-thin on demand.

---

## 4. Optional: Cluster Structure (Foreshocks / Mainshock / Aftershocks)

The parent pointers from §2 connect every event to its nearest predecessor, building a forest. Once Step 4 labels some events as background, **cut every parent link whose child is a background event.** The remaining connected components are clusters; each cluster is rooted at one background event.

For each cluster:
- **Mainshock** = the event with the largest magnitude in the cluster.
- **Foreshocks** = cluster members occurring **before** the mainshock.
- **Aftershocks** = cluster members occurring **after** the mainshock.
- **Background** = the cluster root (which may or may not be the mainshock).

Per-cluster summary statistics typically computed (see `cluster_analysis` outputs in §10):
- Counts: total members, foreshock count, aftershock count
- Magnitudes: mainshock `m`, max foreshock `m`, max aftershock `m`
- Distances: average foreshock-to-mainshock and aftershock-to-mainshock distance
- Durations: cluster duration, foreshock duration, aftershock duration, average pre-/post-mainshock interval
- Seismic moment: total, mainshock, foreshock total, aftershock total (use `M₀ = 10^(1.5·m + 9.1)` N·m, the standard moment-magnitude relation)

**Choice of "the" background event.** When reducing each cluster to one representative for the declustered catalog, two conventions exist:
- Keep the **first** event in the cluster (the root). Used when only space matters.
- Keep the **largest** event (the mainshock). Useful when you want big events flagged as background.

The two conventions give nearly identical spatial distributions because intra-cluster spread is much smaller than inter-cluster spread.

---

## 5. Distance Computation

The paper works with **epicenters only** (set `depth_i = 0` for all events when running epicentral analysis).

**Spatial distance** between two events should use proper geographic distance on a sphere (Haversine / great-circle), then optionally combine with depth:

```
r_horizontal = great_circle_distance(lat_i, lon_i, lat_j, lon_j)        # km
r_3D         = sqrt( r_horizontal² + (depth_i - depth_j)² )             # km
```

A flat-earth approximation (`Δlat·111 km`, `Δlon·111·cos(lat)` km) is acceptable as an upper-bound prefilter when narrowing down candidate parents, but the final `r_ij` used in `η_ij` should be the geographic distance.

---

## 6. Parameter Selection

| Parameter | Meaning | Default | How to tune |
|-----------|---------|---------|-------------|
| `d` | Fractal dimension of epicenters/hypocenters | `1.5` (epicenters), `2.5` (hypocenters) | Estimate from the catalog if possible; mid-range default works because results are insensitive to `d`. |
| `w` | Magnitude weight in proximity | **`0` for declustering** | Do not change unless deviating from the published method. |
| `η₀` | Initial proximity cutoff (Step 1) | `10⁻¹` | Plot histogram of `log10(η)` computed with `w=0`; pick the trough between the two modes. Use `10⁻²·⁵` for fault-confined catalogs (e.g. Parkfield). |
| `M` (or `Nboot`) | Number of reshuffled catalogs in Step 2 | `100` | Larger improves accuracy of `mean(log10(k_i))` but is linear cost. |
| `α₀` | Cluster threshold (Step 4) | Explore in `[-1, 1]` around `0` | Controls **how many** events end up as background. More positive → more background events retained. Pick by the application's stopping criterion (e.g. "largest `α₀` for which the Poisson null is not rejected", or "retain ≈25%"). |

**Sensitivity:** results are **insensitive** to `d` and `η₀` over reasonable ranges and **very sensitive** to `α₀`. Tune `α₀` last and explore a range.

---

## 7. Quality Assessment (Optional but Recommended)

After producing a declustered catalog, test whether the background field is consistent with a stationary Poisson process and / or has independent space–time components. The paper uses five tests; pick a subset:

**Time stationarity (uses event times only):**
- **Bridge test** — compare cumulative event count `P([0,t])` against the linear expectation `Nt/T`. Statistic: `X_B = max |Δ(t)|` where `Δ(t) = (P([0,t]) - Nt/T) / sqrt(Nt(T-t)/T²)`. Quantiles via Monte Carlo.
- **Kolmogorov–Smirnov (KS)** — transform times to `u_i = (t_i - t_min)/(t_max - t_min)` and KS-test against `Uniform(0,1)`.
- **Brown–Zhao** — bin times into `K` equal-width segments, count `N_k`. With `Y_k = sqrt(N_k + 3/8)`, statistic `χ²_BZ = 4·Σ(Y_k − ȳ)²` is approximately `χ²(K-1)` under the null.

**Space–time independence (uses both):**
- **Space–Time factorization (ST) test** — estimate `Λ̂(x,t)`, `Λ̂_space(x)`, `Λ̂_time(t)` by uniform-kernel density (proportion of events within bandwidths `r₀, τ₀`); statistic is the supremum of `Λ̂(x,t) / (Λ̂_space(x)·Λ̂_time(t))`. Significance via permutations of times. Typical bandwidths: `r₀ = 100 km`, `τ₀ = 3 yr`.
- **Luen–Stark (LS) test** — supremum deviation between empirical joint distribution of `(x,t)` and the independence distribution over lower-left quadrants. Significance via time permutations.

If you want a stationary Poisson background, choose `α₀` as the **largest** value at which (after multiple-test correction) the chosen tests do not reject the null.

> **Caveat:** for catalogs spanning a wide magnitude range (`m_max − m_min > 4`), the background is generally **not** stationary even after declustering. This is a real feature of the seismicity, not a flaw of the algorithm.

---

## 8. Output Schema

A complete pipeline produces the following arrays/objects (all per-event unless noted):

| Field | Meaning |
|-------|---------|
| `eta` | Nearest-neighbor proximity `η_i` (Step 1, `w = 0`) |
| `P` | Parent index for each event (0 for the first event / orphans) |
| `D` | Distance to parent (km) |
| `T` | Time to parent (years) |
| `M_parent` | Magnitude of parent |
| `alpha` (or `ad0`) | Normalized log-proximity `log10(α_i)` (Step 3 output — **the reusable key value**) |
| `is_background` | Boolean per event (Step 4 result, depends on `α₀` and RNG) |
| `cluster_id` | Cluster label per event (after Step 4 + parent-link cutting) |
| `is_mainshock`, `is_foreshock`, `is_aftershock` | Roles within each cluster |
| `cluster.*` | Per-cluster summary record (counts, durations, magnitudes, distances, moments) |

---

## 9. End-to-End Pseudocode

```
function decluster(catalog, d, eta0, alpha0, Nboot):

    # Step 1: nearest-neighbor proximity on the original catalog (w = 0)
    (parent, eta, D, T, M_par) = nearest_neighbor_proximity(catalog, b=0, d=d)
    J = indices where eta > eta0

    # Step 2: build reshuffled catalogs and cross-catalog NN proximities
    log_kappa_sum = zeros(N)
    counts        = zeros(N)
    for k in 1..Nboot:
        C_k = build_reshuffled_catalog(catalog, J)         # uniform times, permuted x and m
        kappa_k = cross_catalog_nn(catalog, C_k, b=0, d=d) # one κ per original event
        log_kappa_sum += log10(kappa_k)  where finite
        counts        += 1               where finite
    mean_log_kappa = log_kappa_sum / counts

    # Step 3: normalize
    log_alpha = log10(eta) - mean_log_kappa     # this is "ad0" — persist this!

    # Step 4: thinning
    U = uniform_random(N)
    is_background = (log_alpha + alpha0) > log10(U)

    # Step 5 (optional): build clusters by cutting parent links of background events
    cluster_id, mainshock, foreshock, aftershock = build_clusters(parent, mag, is_background)

    return { log_alpha, is_background, cluster_id, mainshock, foreshock, aftershock, ... }
```

To re-decluster at a new `α₀` without redoing Steps 1–3, just re-run Step 4 against the persisted `log_alpha`.

---

## 10. Reference Implementation (MATLAB)

The original MATLAB sources are companion files to this document. They are the authoritative spec for numerical details (boundary cases, candidate pruning, distance floors, cross-catalog edge cases). When implementing in another language, mirror their behavior.

| File | Role |
|------|------|
| [`bp_add_1_m.txt`](./bp_add_1_m.txt) | Computes `η_i` and parent pointers within a single catalog (Step 1 / §2). Implements the candidate-pruning optimization. |
| [`bp_2cat_add_1_m.txt`](./bp_2cat_add_1_m.txt) | Cross-catalog nearest-neighbor proximity: each event in catalog A finds its nearest parent in catalog B. Used inside Step 2 to compute `κ_{k,i}`. |
| [`bp_thinning_fast_m.txt`](./bp_thinning_fast_m.txt) | Orchestrates Steps 1–3: runs `bp_add_1` once on the original catalog, runs `bp_2cat_add_1` `Nboot` times against reshuffled catalogs, and returns the normalized `α_i` (variable `a` in the code, often called `ad0` downstream). |

The `code_descripion.txt` file (also in this folder) documents the MATLAB-level entry points (`run_me_first`, `decluster_run`, `cluster_analysis`) and expected input/output catalog file formats.

---

## 11. Quick Implementation Checklist

- [ ] Sort the input catalog by time before doing anything else.
- [ ] Use `w = 0` in the proximity formula for declustering (do not use the cluster-analysis `w = 1` value).
- [ ] Work in log-space (`log10(η)`) to avoid numerical overflow on large catalogs.
- [ ] Apply distance/time floors (1 m, 1 sec) before taking logs.
- [ ] Use proper great-circle distance, not flat-earth Euclidean, for the final `r_ij`.
- [ ] Persist `log_alpha` (the Step 3 output) — it is the expensive intermediate and is `α₀`-independent.
- [ ] Treat the result as one realization; for stable conclusions, average over many runs (or compute per-event background frequencies across runs).
- [ ] Validate with a synthetic ETAS catalog with known ground truth before trusting the algorithm on a new region.
