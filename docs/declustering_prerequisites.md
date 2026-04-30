# Prerequisites and Parameter Estimation for the Nearest-Neighbor Declustering Algorithm

> **Companion document to** `declustering_algorithm.md`. This document covers everything that needs to be **done or decided before** running the declustering algorithm: validating the input catalog, estimating the fractal dimension `d`, picking the initial proximity cutoff `η₀`, and choosing the cluster threshold `α₀`. It is language-independent.

A bad answer from a good algorithm almost always traces back to skipped prerequisites. Run through this document in order.

---

## 1. Catalog Quality Checklist

Before computing any proximity, verify the catalog meets these requirements.

### 1.1 Required fields per event
- **Origin time** — fractional years (or any monotonic real-valued time you can convert to seconds for proximity calculation).
- **Latitude, Longitude** — decimal degrees, signed (south/west negative).
- **Depth** — in km. If you only have epicenters, set all depths to `0` (the algorithm defaults to epicentral analysis).
- **Magnitude** — preferably a single, homogenized scale (see §1.4).

### 1.2 Magnitude of completeness `M_c`
**Why it matters:** the algorithm assumes a complete catalog above some threshold magnitude. If `M_c` is wrong, low-magnitude events will be missing in some regions/times, which shows up as fake spatial holes and biases the bootstrap intensity estimate in Step 2.

**Practical recipe (Maximum Curvature method, MAXC):**
1. Bin the catalog magnitudes into bins of width `Δm = 0.1` (or the catalog's own magnitude resolution).
2. Compute the non-cumulative frequency-magnitude distribution `N(m)` — count of events in each bin.
3. The bin with the **highest count** gives `M_c^MAXC`.
4. Add a safety correction: `M_c = M_c^MAXC + 0.2`.

MAXC is fast and robust but tends to underestimate `M_c` in heterogeneous catalogs. If high accuracy matters, also run one of: Goodness-of-Fit Test (GFT) at 95%, b-value stability (MBS), or Entire Magnitude Range (EMR) — and take the maximum across methods. See Mignan & Woessner (2012) for a comparative review.

**Filter the catalog:** drop all events with `m < M_c` before declustering. Keeping incomplete events injects spurious clustering signal.

**Watch for time-dependent `M_c`:** old parts of a long catalog usually have higher `M_c` than the recent parts (network upgrades). Either truncate the catalog to the period where `M_c` is uniform, or compute `M_c(t)` and keep only events above the time-varying threshold. Spatially varying `M_c` can produce the same artifact (see §1.6).

### 1.3 Location accuracy
**Rule of thumb:** the typical hypocentral location error must be **smaller than** the spatial scale you care about. The algorithm uses a 1-meter floor for distances (`r_min = 1 m`); locations that disagree below this floor are treated as identical. For relocated catalogs (e.g. Hauksson et al., GrowClust products) errors are typically <1 km horizontally; for older raw catalogs they can exceed 5 km, which biases small-scale clustering.

If location errors vary across the catalog (e.g. denser stations after some date), the algorithm may interpret the change as a change in clustering. Either (a) restrict to the well-located portion or (b) note the artifact in your interpretation.

### 1.4 Magnitude scale homogenization
Catalogs assembled from multiple agencies often mix `M_L`, `m_b`, `M_S`, `M_w`, and duration magnitudes. Convert all to a single scale (preferably `M_w`) using empirical conversion relations valid for your region before declustering. Mixed scales produce a **multimodal** magnitude distribution that breaks `M_c` estimation and the b-value.

### 1.5 Duplicates and bookkeeping
- Remove duplicate events (same origin time + close location reported by overlapping networks).
- Sort by origin time, ascending. The algorithm assumes strictly monotonic time; ties (`t_i = t_j`) should be broken by tiny perturbation or by deduplication.
- Verify there are no obvious data errors: magnitudes outside `[-2, 10]`, depths outside `[0, 700] km`, lat outside `[-90, 90]`, lon outside `[-180, 180]`.

### 1.6 Time span and event count
- The Step-2 bootstrap needs enough events with `η_i > η₀` to estimate location-specific intensity. As a rough lower bound, aim for **≥ 1000 events** above `M_c` after this filter. With fewer events, results become noisy and `α₀` selection unstable.
- Catalogs spanning **fewer than ~5 years** rarely contain enough independent background events to produce useful statistics.
- If the catalog has obvious step changes in seismicity rate (network upgrades, station outages, post-event detection bursts), document them — they will appear as nonstationarity in the declustered output even when the algorithm is working correctly.

---

## 2. Estimating the Fractal Dimension `d`

The fractal dimension of epicenters/hypocenters appears in the proximity formula as the exponent of `r_ij`. It controls the trade-off between time and space in the nearest-neighbor metric.

### 2.1 Defaults (use if estimation is impractical)
- **Epicenters (2D analysis):** `d = 1.5`
- **Hypocenters (3D analysis):** `d = 2.5`

The algorithm is **insensitive** to `d` — variations of ±0.3 around the right value produce nearly identical declustered catalogs. Use the default if you have fewer than ~500 events or a clear practical reason not to estimate.

### 2.2 Correlation Integral Method (Grassberger–Procaccia, 1983)

The standard approach. Procedure for epicenters; for hypocenters, use 3D distances.

1. **Build pair distances.** Take all unique pairs `(i, j), i < j` and compute the great-circle epicentral distance `r_ij` (km). For very large catalogs, randomly subsample ~10,000 events to keep this `O(N²)` step tractable.

2. **Define the correlation integral:**
   ```
   C(r) = (2 / (N(N-1))) · #{ (i,j) : i < j and r_ij < r }
   ```
   (the fraction of pairs closer than `r`).

3. **Compute `C(r)` over a log-spaced grid** of distances, e.g. 30 values from `r_min = 0.5 km` to `r_max = 100 km` (adjust the upper bound to roughly the linear extent of your study region; lower bound to the location uncertainty).

4. **Plot `log10(C(r))` vs `log10(r)`.** A finite fractal set produces a linear region:
   ```
   log10(C(r)) ≈ d · log10(r) + const
   ```
   The slope of this linear region is `d`.

5. **Fit a line** by least-squares over the linear segment only. Exclude:
   - **Small `r`:** below the typical location error (depopulation regime — flattens the curve).
   - **Large `r`:** beyond the spatial extent of the study region (saturation — flattens to 1).

   In published studies, fits are typically over one decade in `r`, e.g. `1 km` to `12.6 km` for regional catalogs (slope of the log-log linear segment).

6. **Quality check:** the fitted `R²` should be > 0.97. A poor linear fit means either (a) the catalog has multiscale structure (use a multifractal spectrum instead) or (b) the chosen `r`-range is wrong. Fall back to the default `d = 1.5` (epicenters) if you cannot get a clean linear segment.

### 2.3 Pseudocode

```
function estimate_fractal_dimension(events, r_min, r_max, n_bins=30):
    # subsample if events is huge
    if len(events) > 10000:
        events = random_sample(events, 10000)

    pair_distances = []
    for i in 1..len(events):
        for j in i+1..len(events):
            pair_distances.append(great_circle(events[i], events[j]))

    r_grid = logspace(log10(r_min), log10(r_max), n_bins)
    C = [ count(pair_distances < r) / len(pair_distances) for r in r_grid ]

    # find linear segment in log-log space (the "scaling region")
    log_r = log10(r_grid)
    log_C = log10(C)

    # automated linear range: drop points where d(log_C)/d(log_r) deviates
    # from the median local slope by more than 25%
    slope_at_each_point = local_slope(log_r, log_C, window=3)
    median_slope = median(slope_at_each_point)
    in_linear_range = abs(slope_at_each_point - median_slope) < 0.25 * abs(median_slope)

    d, intercept, R2 = linear_fit(log_r[in_linear_range], log_C[in_linear_range])

    if R2 < 0.97:
        warn("Linear fit poor — falling back to default d = 1.5")
        return 1.5
    return d
```

### 2.4 Sanity range
Reported `d` values for tectonic catalogs cluster between **1.0 and 2.0** for epicenters (1.0 ≈ linear fault, 2.0 ≈ surface-filling), and **2.0 to 3.0** for hypocenters. Values outside these ranges indicate a bad fit, not a valid measurement.

---

## 3. The b-value (Gutenberg–Richter)

**Important:** the declustering algorithm uses `w = 0`, so the b-value does **not** enter the proximity calculation directly. You compute the b-value as a **catalog quality check** and to confirm `M_c`. (You only need `b` in the proximity if you do cluster analysis with `w = 1`.)

### 3.1 Maximum Likelihood Estimator (Aki, 1965)
For events with `m ≥ M_c`:
```
b̂ = log10(e) / (mean(m) − M_c + Δm/2)
   ≈ 0.4343 / (mean(m) − M_c + Δm/2)
```
where `Δm` is the magnitude binning resolution (typically `0.1`). Standard error: `σ_b ≈ b̂ / sqrt(N)`.

### 3.2 Sanity check
For tectonic catalogs `b ≈ 1.0` (range typically `0.7 – 1.3`). Strong deviations usually mean (a) wrong `M_c`, (b) mixed magnitude scales, or (c) anomalous tectonic regime (volcanic, induced seismicity).

---

## 4. Selecting the Initial Proximity Cutoff `η₀`

`η₀` is the threshold used in Step 1 of the algorithm to remove the most-clustered events from the bootstrap pool. Picking it correctly is the single most important pre-run decision.

### 4.1 Compute the proximity histogram
Run the proximity computation **once** with `w = 0` and the chosen `d`:
```
η_i  =  min over i<j of  [ t_ij · r_ij^d ]    for each event j > 1
```
Then form the histogram of `log10(η_i)` (drop infinities). For a typical regional catalog this distribution is **bimodal**:
- A **left mode** (small `log10(η)`) — clustered events.
- A **right mode** (large `log10(η)`) — background events.

### 4.2 Visual selection (works in most cases)
Plot the histogram with ~50–80 bins. Pick `log10(η₀)` at the **trough between the two modes**. Set `η₀ = 10^(log10(η₀))`.

**Typical values from the published paper (use as starting points):**

| Catalog type | `η₀` |
|---|---|
| Global, regional with `M_c ≥ 2.5` (most cases) | `10⁻¹` |
| Catalogs dominated by a single aftershock sequence (e.g. Landers area) | `10⁻¹` (still works) |
| Narrow fault zones, very high spatial intensity (e.g. Parkfield) | `10⁻²·⁵` |
| Volcanic / geothermal / induced (high background, weak bimodality) | `10⁻⁴` to `10⁻²` (estimate per case) |

### 4.3 Automated selection — 1D Gaussian Mixture Model

When the trough is not obvious (continuous distribution, three modes, etc.), fit a two-component Gaussian mixture to `log10(η_i)`:

```
p(x) = π₁ · 𝒩(x; μ₁, σ₁²) + π₂ · 𝒩(x; μ₂, σ₂²),    π₁ + π₂ = 1
```

Fit by Expectation-Maximization (EM). Then pick `log10(η₀)` as the **decision boundary** where the two components contribute equal probability density:

```
solve for x:  π₁ · 𝒩(x; μ₁, σ₁²) = π₂ · 𝒩(x; μ₂, σ₂²)
```

Take the root that lies **between** the two means. For equal mixture weights this reduces to a quadratic; in code, use a numerical root-finder on the difference of the two PDFs in the interval `[μ₁, μ₂]` (assuming `μ₁ < μ₂`).

This is the procedure cited in Zaliapin & Ben-Zion (2016a, §3.4) and applied in subsequent papers on induced and volcanic seismicity.

### 4.4 What can go wrong

- **No visible trough.** The catalog is either very sparse, very strongly clustered (almost all events are aftershocks), or has very weak clustering. In the first two cases, declustering is still possible — start with `η₀ = 10⁻¹` and do a sensitivity analysis. In the third case, the catalog may already be near-Poisson and declustering will remove very few events.
- **Three or more modes.** Multiple fault systems with very different background rates, or a mix of natural and induced seismicity. Either split the catalog spatially and decluster each region separately, or use a multi-component mixture and pick the rightmost trough.
- **Threshold instability.** If declustering results change a lot when `η₀` varies by ±0.5 in log10 units, the catalog likely lacks clean bimodality. Report `η₀` as a sensitivity range, not a single value.

### 4.5 The `η₀`-sensitivity escape hatch

The paper notes that `η₀` only affects the **relative** spatial intensity estimate, not the absolute number of background events (which is controlled by `α₀`). So a wrong `η₀` typically distorts the spatial pattern slightly without dramatically changing how many events are kept. You can largely fix a wrong `η₀` by re-tuning `α₀`. The exception is catalogs dominated by one aftershock sequence (>90% of events from one mainshock), where `η₀` matters a lot.

---

## 5. Choosing the Cluster Threshold `α₀`

`α₀` is the only parameter to which the declustering result is **highly sensitive**. It controls the total number of events labeled background.

### 5.1 What to do before tuning `α₀`

You can only tune `α₀` **after** Steps 1–3 of the algorithm are done — i.e. after you have computed `log10(α_i)` for every event. The expensive computation does not need to be repeated for different `α₀` values; only Step 4 (thinning) is rerun.

### 5.2 Search range
Always start in `[-1, +1]` and expand if needed. The published examples land at:

| Catalog | Optimal `α₀` (median p-values acceptable) |
|---|---|
| Synthetic ETAS | `0.0` (agrees with ground truth) |
| Global NCEDC `m ≥ 5` | `−0.6` |
| Southern California `m ≥ 2.5` | `−0.8` |
| Southern California `m ≥ 3.5` | `0.0` |
| Landers rupture zone `m ≥ 0` | `0.2` |
| Parkfield `m ≥ 1` | `0.0` |

There is no universal "best" `α₀` — it depends on the catalog and what you want from declustering.

### 5.3 Stopping criteria (pick one based on your application)

**Criterion A — target background fraction.** If you need a specific percentage of background events (e.g. for hazard analysis):
1. Sweep `α₀` from `-1` to `+1` in steps of `0.1`.
2. For each value, run Step 4 and count `N_bg / N_total`.
3. Pick the `α₀` that hits your target (~20–30% is typical for tectonic catalogs).

**Criterion B — Poisson stationarity.** If you need a (statistically) Poisson background:
1. Sweep `α₀`, run Step 4 at each value (multiple realizations).
2. For each declustered catalog, run the bridge / KS / Brown–Zhao tests.
3. Pick the **largest** `α₀` for which none of the tests rejects the null at the chosen significance level (with multiple-test correction).

**Criterion C — bimodality of `log10(α_i)`.** If the histogram of `log10(α_i)` is itself bimodal, place `α₀` at the negative of the trough location (so events with `log10(α_i) > -α₀` are kept). This is rare but clean when it works.

**Criterion D — exploratory.** Run multiple `α₀` values and inspect the declustered map/timeline visually. Pick the value that looks reasonable and report it transparently. Honest practice when ground truth is unavailable.

### 5.4 Stochastic stability
Each `α₀` defines a **probabilistic** classifier. Run thinning (Step 4) **many times** (e.g. 500–10,000 realizations) and:
- Report the per-event background frequency `f_i = (# realizations where i is background) / (# realizations)` — this is more informative than a single binary label.
- A stable result has >75% of events with `f_i > 0.9` or `f_i < 0.1` (i.e. consistently classified one way or the other).

---

## 6. Other Computational Parameters

### 6.1 `M` (also called `Nboot`) — number of reshuffled catalogs in Step 2
- Default: `100`.
- Increase to `200–500` for small catalogs (`N < 5000`) where bootstrap noise matters.
- Cost is roughly linear in `M`; the rate-limiting step is the cross-catalog NN proximity.

### 6.2 ST-test bandwidths
For evaluating the declustered catalog with the space-time factorization test:
- **Spatial bandwidth `r₀`:** typical `100 km` for regional catalogs; scale to `~1/10` of catalog spatial extent.
- **Temporal bandwidth `τ₀`:** typical `3 years`; scale to `~1/5` of catalog duration.
- These are quality-test parameters only; they do not affect declustering.

### 6.3 Number of permutations for significance testing
- Default: `500`.
- Use `1000+` if you need to resolve p-values below `0.01`.

---

## 7. Pre-flight Sanity Checklist

Before running the full pipeline, confirm all of the following:

- [ ] Catalog sorted by origin time, ascending.
- [ ] No duplicate events.
- [ ] Single homogeneous magnitude scale.
- [ ] All events have `m ≥ M_c` (and `M_c` is documented).
- [ ] Time span is at least a few years and event count is >1000 above `M_c`.
- [ ] `b-value ≈ 1` confirms catalog quality (or deviation is explained).
- [ ] `d` has been estimated from data, or default chosen with justification.
- [ ] `η₀` has been chosen from the histogram of `log10(η_i)` (visual or GMM).
- [ ] The histogram of `log10(η_i)` actually shows bimodality (or you have noted that it does not).
- [ ] You have a plan for choosing `α₀` (Criterion A, B, C, or D).
- [ ] Distances are computed with great-circle geometry, not flat-earth, in the final proximity (flat-earth is fine for candidate prefiltering).
- [ ] `w = 0` is set for declustering (not `w = 1`, which is for cluster analysis only).
- [ ] Random seed is recorded (declustering is stochastic — reproducibility requires the seed).

---

## 8. Summary: Minimum Viable Parameter Set

For a generic regional tectonic catalog of moderate size when you don't want to do full estimation:

```
M_c            =  estimated by MAXC + 0.2
d              =  1.5            (epicentral analysis)
w              =  0              (declustering, not cluster analysis)
η₀             =  10⁻¹           (refine from histogram if possible)
α₀             =  0              (refine using Criterion A or B above)
M (Nboot)      =  100
```

Run the pipeline, inspect `log10(α_i)` distribution, sweep `α₀ ∈ [-1, 1]`, and pick the threshold using one of the stopping criteria.

---

## 9. References for Further Reading

- **Magnitude completeness:** Mignan, A., & Woessner, J. (2012). *Estimating the magnitude of completeness for earthquake catalogs.* Community Online Resource for Statistical Seismicity Analysis. DOI: `10.5078/corssa-00180805`. Comparative review of MAXC, GFT, MBS, EMR, and MBASS.
- **Fractal dimension:** Grassberger, P., & Procaccia, I. (1983). *Measuring the strangeness of strange attractors.* Physica D, 9, 189–208. The original correlation integral method.
- **Bimodality / GMM threshold:** Zaliapin, I., & Ben-Zion, Y. (2016a). *Discriminating Characteristics of Tectonic and Human-Induced Seismicity.* BSSA, 106(3). DOI: `10.1785/0120150211`. Section 3.4 covers the 1-D Gaussian mixture model for `η₀` selection.
- **b-value MLE:** Aki, K. (1965). *Maximum likelihood estimate of b in the formula log N = a − bM and its confidence limits.* Bull. Earthq. Res. Inst., 43, 237–239.
- **Reference implementations:** Goebel, T. (`github.com/tgoebel/clustering-analysis`) — Python implementation of nearest-neighbor cluster analysis on Southern California catalogs, useful as a cross-check.
- **Original method paper:** Zaliapin & Ben-Zion (2020), JGR Solid Earth, `10.1029/2018JB017120` — see the companion file `declustering_algorithm.md` for the algorithmic details.
