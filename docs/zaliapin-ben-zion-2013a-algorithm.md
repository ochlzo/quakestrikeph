# Zaliapin & Ben-Zion (2013a) — End-to-End Algorithm

**Source paper:** Zaliapin, I., & Ben-Zion, Y. (2013). *Earthquake clusters in southern California I: Identification and stability.* Journal of Geophysical Research: Solid Earth, 118(6), 2847–2864. DOI: 10.1002/jgrb.50179

**Audience:** Research team members (students) and AI coding agents.

**Scope:** This document describes the **cluster identification** algorithm of Zaliapin & Ben-Zion (2013a). The output is a labeling of every event in an earthquake catalog as one of: **single (background/standalone)**, **mainshock**, **foreshock**, or **aftershock**. Every claim, formula, parameter value, and procedural step in this document is taken directly from the 2013a paper. Optional engineering details (e.g., logarithmic computation for numerical safety) are clearly marked as such.

---

## 1. What the Algorithm Does

The algorithm partitions an earthquake catalog into statistically significant clusters by exploiting an empirical fact: in real seismicity catalogs, the distribution of nearest-neighbor distances (in a combined space-time-magnitude domain) is **bimodal**. One mode contains "clustered" events (abnormally close to their nearest neighbors); the other contains "background" events (farther away, consistent with a stationary inhomogeneous Poisson process). The valley between these modes provides a natural threshold for separating clusters from background.

The clusters are then organized as time-oriented trees. Within each multi-event tree (called a **family**), the largest-magnitude event is the **mainshock**, earlier events are **foreshocks**, and later events are **aftershocks**. Single-event trees are called **singles**.

Per the paper, the algorithm has three properties that distinguish it from prior methods (Section 3, paragraph [7] of the paper):

1. **Soft parameterization** — only three parameters are needed: the b-value, the spatial fractal dimension `d_f`, and the cluster threshold `η₀`.
2. **High stability** — results are robust to parameter values, minimum reported magnitude, catalog incompleteness, and location errors.
3. **No underlying cluster model** — no ETAS or other generative assumption is required.

> **Note on terminology.** The paper explicitly distinguishes its method from *catalog declustering* (paragraph [13]): "The problem considered in this study is different from catalog declustering, which is formulated as removing some events from a catalog in order to obtain a homogeneous remaining point field. We focus, instead, on identifying individual statistically significant clusters." For our task — labeling every event as mainshock/foreshock/aftershock/background — this is the correct algorithm.

---

## 2. Inputs

A catalog of `N` earthquakes, each described by:

- **Origin time** `t_i` (the paper expresses time in **years**, including fractional years)
- **Location**: hypocenter `(φ_i, λ_i, d_i)` where `φ_i` is latitude, `λ_i` is longitude, `d_i` is depth. The 2013a main analysis **ignores depth** and uses surface distance between epicenters (Section 3.1, paragraph [15]).
- **Magnitude** `m_i`

---

## 3. Pre-Processing

### 3.1 Sort by time

Sort all events by origin time in ascending order so that for any pair `(i, j)` with `i < j` we have `t_i ≤ t_j`.

### 3.2 Choose a minimum magnitude `m_c`

Pick a magnitude cutoff `m_c` and discard events with `m < m_c`. The paper used `m_c = 2` for southern California (paragraph [9]) even though the true completeness magnitude is above 3.0, and demonstrated that "the cluster structure of the events is insensitive to the catalog incompleteness as well as to the minimal reported magnitude" (paragraph [10]; full demonstrations in supporting information sections D and E of the paper).

### 3.3 Estimate the three parameters `(b, d_f, η₀)`

The algorithm is "completely parameterized by the triplet `(b, d_f, η₀)` whose values are estimated from the observations" (paragraph [32]).

**The b-value** of the Gutenberg-Richter magnitude distribution:

```
log₁₀ N(m) = a - b · m,    m ≥ m_c
```

The paper used **b = 1** in its main analysis (paragraph [15]) and recommends estimating `b` via the Tinti and Mulargia (1987) estimator, which accounts for the discreteness of reported magnitudes (Section 4.1, paragraph [38]). The paper notes that different estimators may produce values that "deviate within ±0.03" but this does not affect the qualitative results.

**The fractal dimension `d_f`** of the spatial epicenter distribution. The paper used **`d_f = 1.6`** in its main analysis (paragraph [15]) and refers to Harte (1998), Kagan (2007), and Molchan and Kronrod (2009) as reviews of fractal-dimension estimation methods.

**The cluster threshold `η₀`** is chosen *after* computing the nearest-neighbor distances and inspecting their distribution. See Section 6 below for the procedure.

> **Stability claim from the paper.** The paper's Discussion (paragraph [54]) states: "variations of the parameters within wide limits, largely exceeding their statistical variability, do not seriously affect the cluster identification." The full demonstration is in supporting information sections D (synthetic ETAS catalogs) and E (observed southern California catalog), summarized in Section 3.6 (paragraph [32]).

---

## 4. The Pairwise Distance (Equation 1 of the paper)

For an *earlier* event `i` and a *later* event `j` (i.e., `t_ij = t_j - t_i > 0`), define:

```
   η_ij = t_ij · (r_ij)^d_f · 10^(-b · m_i),    if t_ij > 0
   η_ij = ∞,                                    if t_ij ≤ 0
```

where:

- `t_ij = t_j - t_i` is the inter-occurrence time **in years**.
- `r_ij ≥ 0` is the spatial distance between the earthquake epicenters **in kilometers**. The paper specifies "surface distance between the event epicenters" (paragraph [15]); depth is ignored.
- `d_f` is the fractal dimension parameter from Section 3.3 above.
- `b` is the b-value parameter from Section 3.3 above.
- `m_i` is the magnitude of the **earlier** event.

The minus sign in the magnitude exponent makes the distance shrink for larger `m_i` (large earlier events get a longer "reach"), which is the mechanism by which the algorithm captures aftershock sequences of large mainshocks.

> **Engineering note (not from the paper).** Direct computation of `η_ij` for a large catalog can underflow floating-point representation. Standard practice is to compute in log-space:
>
> `log₁₀(η_ij) = log₁₀(t_ij) + d_f · log₁₀(r_ij) - b · m_i`
>
> The paper does not prescribe a specific numerical form, but the figures (e.g., Figure 4) work in `log₁₀ η`, so log-space is the natural representation.

### 4.1 Optional: rescaled time `T` and rescaled distance `R` (Equation 2 of the paper)

For visualization and analysis, the scalar distance `η_ij` is decomposed into a time component and a space component:

```
T_ij = t_ij · 10^(-q · b · m_i)
R_ij = (r_ij)^d_f · 10^(-(1-q) · b · m_i)
```

so that `η_ij = T_ij · R_ij`, equivalently `log₁₀ η_ij = log₁₀ T_ij + log₁₀ R_ij`.

The paper uses `q = 0.5` throughout (paragraph [17]).

> **Important.** The paper states explicitly (paragraph [32]): "the parameter `q` of equation (2) is only used for visual purposes (to define and plot rescaled time `T` and space `R`) and is not involved in the cluster identification." `T` and `R` are needed only for diagnostic plots (the joint `(log T, log R)` scatter), not for the labeling itself.

---

## 5. The Nearest-Neighbor Distance and the Spanning Tree

### 5.1 Definition of the nearest neighbor (parent)

For each event `j` (except the first event in the sorted catalog), define its **nearest-neighbor distance (NND)** as:

```
η_j = min { η_ij : i < j }
```

The earlier event `i* = argmin { η_ij : i < j }` is called the **nearest neighbor** or **parent** of event `j`. Event `j` is then called an **offspring** of `i*`.

By this definition (paragraph [25]):
- Every event except the first has exactly one parent.
- An event may have zero, one, or many offspring.

### 5.2 The spanning tree

Connecting every event to its parent forms a **single connected graph that contains every event** in the catalog. The paper calls this the **spanning network** or **spanning tree** (paragraph [25] and Figure 5a). From a graph-theoretic perspective, it is a tree: it has no loops (the paper proves this in supporting information section C; it is non-trivial because the property does not hold for arbitrary metrics in Euclidean spaces).

---

## 6. Selecting the Threshold `η₀`

The choice of `η₀` is informed by the empirical bimodal distribution of `log₁₀ η_j`.

### 6.1 What you should observe

When you compute `η_j` for every event and plot a histogram of `log₁₀ η_j`, you should see two distinct modes (Figure 4 of the paper):

- A **cluster mode** near small `η` (closer to the origin in the `(log T, log R)` plane).
- A **background mode** near large `η` (extended along and above the line `log₁₀ T + log₁₀ R = const`).

If the distribution is unimodal, the catalog either has very little clustering or the parameters need to be re-examined. The bimodal pattern has been documented across many regions and scales (paragraph [23] of the paper).

### 6.2 Two methods for choosing `η₀`

**Method A — Visual inspection.** Plot the histogram of `log₁₀ η_j` and pick a value in the valley between the two modes. The paper notes (paragraph [26]): "A visual inspection of Figure 4 suggests `η₀ = 10⁻⁵` as a reasonable separation threshold" for the southern California catalog.

**Method B — Gaussian Mixture Model (formal).** The paper cites Hicks (2011), who fit a 2-component Gaussian Mixture Model using the Expectation-Maximization (EM) algorithm. The fit can be done in 1-D on `log₁₀ η` or in 2-D on `(log₁₀ T, log₁₀ R)`. Per the paper (paragraph [26]): "Such a formal analysis suggests also that `η₀ ≈ 10⁻⁵`" for the southern California catalog.

> **For other regions:** Do not assume `η₀ = 10⁻⁵`. Always inspect your own histogram and re-fit. The bimodality is a general feature of seismicity, but the *location* of the valley depends on the catalog.

### 6.3 Definition of weak and strong links

Once `η₀` is chosen, every parent link in the spanning tree is classified (paragraph [26]):

- **Strong link**: `η_j < η₀` — corresponds to the cluster mode.
- **Weak link**: `η_j ≥ η₀` — corresponds to the background mode.

---

## 7. Cutting Weak Links — The Spanning Forest

Remove every weak link from the spanning tree. The remaining graph is no longer connected; it is a **spanning forest** (paragraph [27] and Figure 5b) — a collection of disjoint trees that collectively contain every event in the catalog.

Each tree in the forest is a **cluster**. The paper distinguishes two types:

- **Single** — a tree containing exactly one event. The event has no strong link to any earlier event, and no later event has a strong link to it.
- **Family** — a tree containing two or more events, all connected by strong links.

For southern California, with `m_c = 2` and using `b = 1`, `d_f = 1.6`, `η₀ = 10⁻⁵`, the paper reports separating 111,981 events into 41,393 statistically significant clusters (paragraph [1]).

---

## 8. Labeling Events Within Clusters (Section 3.5 of the paper)

### 8.1 Singles

If a cluster contains a single event, that event is labeled a **single**. The paper characterizes singles explicitly (paragraph [43]) as "**mainshocks with no offspring**" — i.e., events whose own parent link was weak (so they were not absorbed into a family above them) and which had no later events forming strong links down to them. Singles are not noise: paragraph [43] notes that "the existence of singles cannot be explained solely by catalog artifacts such as incompleteness or the minimal reported magnitudes," and Section 4.2 demonstrates that singles form a statistically distinct population.

For the purposes of mapping to the four-class user requirement (mainshock / foreshock / aftershock / background-standalone), **singles are the "background/standalone" class**. They are the maximal events of trivial single-event sequences and, together with family mainshocks, constitute the point field that would correspond to a declustered catalog (paragraph [13]).

### 8.2 Families: mainshock, foreshocks, aftershocks

For each family (multi-event cluster), apply the following rules (paragraph [29]):

1. **Mainshock**: the event with the **largest magnitude** in the family. If multiple events share the largest magnitude, the **first one in time** is the mainshock. Each family has exactly one mainshock.
2. **Aftershocks**: every event in the family that occurred **after** the mainshock.
3. **Foreshocks**: every event in the family that occurred **before** the mainshock.

> **Caveat from the paper (paragraph [29]):** "The event classification depends on the catalog magnitude cutoff. For instance, with a lower cutoff some singles may become mainshocks (after being connected to possible foreshocks and aftershocks), while with a higher cutoff, some mainshocks may become singles. Other changes of event types are also possible." This is a property of the conditional definition, not a flaw in the algorithm.

### 8.3 Reference statistics from the paper (Table 1)

For the southern California catalog with `m_c = 2` and the standard parameters `(b = 1, d_f = 1.6, η₀ = 10⁻⁵)`, the paper reports the following proportions across all 111,981 events:

| Magnitude range | Singles | Mainshocks | Aftershocks | Foreshocks |
|---|---|---|---|---|
| All (`m ≥ 2`) | 31% | 6% | 56% | 7% |
| `2 ≤ m < 3` | 32% | 4% | 56% | 7% |
| `3 ≤ m < 4` | 22% | 16% | 56% | 6% |
| `4 ≤ m < 5` | 8% | 30% | 58% | 4% |
| `5 ≤ m < 6` | 1% | 49% | 48% | 2% |
| `m ≥ 6` | 0% | 85% | 8% | 8% |

These can serve as a sanity-check baseline when implementing the algorithm: for a tectonic catalog at the equivalent magnitude scale, expect rough order-of-magnitude agreement, with mainshock proportion increasing strongly with magnitude.

---

## 9. End-to-End Pseudocode

```
INPUT:
  events: list of (t, lat, lon, depth, m), sorted ascending by t
  m_c:    magnitude completeness cutoff
  b:      Gutenberg-Richter b-value
  d_f:    fractal dimension of epicenters
  eta_0:  cluster threshold (determined after Step 3)

# --- Step 1: filter by completeness ---
events <- {e in events : e.m >= m_c}
N <- len(events)

# --- Step 2: compute nearest-neighbor distance for each event ---
parent <- array of size N, initialized to NULL
eta    <- array of size N, initialized to +infinity

for j in 1..N-1:                     # 0-indexed; first event has no parent
  for i in 0..j-1:
    t_ij <- events[j].t - events[i].t            # in years
    if t_ij <= 0:                                # per Eq. 1: eta_ij = +infinity
      continue
    r_ij <- surface_distance_km(events[i], events[j])
    if r_ij <= 0:                                # numerical safeguard for co-located events
      continue                                   # (the paper does not specify this case)
    # Compute in log space for numerical safety:
    log_eta_ij <- log10(t_ij) + d_f * log10(r_ij) - b * events[i].m
    if log_eta_ij < log10(eta[j]):
      eta[j]    <- 10 ** log_eta_ij
      parent[j] <- i

# --- Step 3: choose eta_0 ---
# Plot histogram of log10(eta[j]) for j = 1..N-1.
# Method A: pick eta_0 in the valley between the two modes by inspection.
# Method B: fit a 2-component Gaussian Mixture Model (EM) on log10(eta);
#           pick eta_0 at the crossover of the two component densities.
# (Steps 4-6 below depend on this choice.)

# --- Step 4: classify links and build the spanning forest ---
# Use union-find (disjoint set) to build clusters.
cluster <- DisjointSet(N)
for j in 1..N-1:
  if eta[j] < eta_0:                  # strong link
    cluster.union(j, parent[j])

# --- Step 5: label every event and assign cluster ids ---
label      <- array of size N
cluster_id <- array of size N
for each connected component C in cluster:
  cid <- next_cluster_id()
  for k in C:
    cluster_id[k] <- cid
  if size(C) == 1:
    label[C[0]] <- "single"
  else:
    # find mainshock: largest magnitude; break ties by earliest time
    M_max <- max(events[k].m for k in C)
    candidates <- {k in C : events[k].m == M_max}
    mainshock_idx <- argmin(events[k].t for k in candidates)

    label[mainshock_idx] <- "mainshock"
    for k in C, k != mainshock_idx:
      if events[k].t < events[mainshock_idx].t:
        label[k] <- "foreshock"
      else:
        label[k] <- "aftershock"

OUTPUT:
  label[k]:        one of {"single", "mainshock", "foreshock", "aftershock"}
  parent[k]:       index of nearest-neighbor predecessor (or NULL for first event)
  eta[k]:          nearest-neighbor distance
  cluster_id[k]:   cluster membership identifier
```

---

## 10. Optional: Δ-Analysis (Section 2.3 of the paper)

Because the catalog has a lower cutoff `m_c`, an event of magnitude `m_c` cannot have foreshocks or aftershocks below `m_c`, while a large mainshock can have offspring spanning a wide magnitude range. To equalize the magnitude ranges available across mainshocks of different sizes, the paper introduces **Δ-analysis** (paragraph [11]):

1. Pick a fixed `Δ` (the paper uses `Δ = 2`).
2. Consider only mainshocks with `m ≥ m_c + Δ`.
3. Within each such cluster, retain only foreshocks and aftershocks with magnitude within `Δ` units below the mainshock — i.e., `m_event ≥ m_mainshock - Δ`.
4. The retained events are called **Δ-foreshocks** and **Δ-aftershocks**.

Δ-analysis is **optional**. The paper performs both "regular analysis" (all events) and Δ-analysis side by side. Δ-analysis is useful when comparing cluster statistics across mainshocks of very different sizes (e.g., when computing scaling relations between cluster properties and mainshock magnitude).

---

## 11. Outputs

A complete run of the algorithm produces, for each event `k` in the filtered catalog:

| Field | Definition |
|---|---|
| `parent[k]` | Index of the nearest-neighbor predecessor (the "parent"). NULL for the first event. |
| `eta[k]` | The nearest-neighbor distance `η_k` (Equation 1, minimized over all earlier events). |
| `cluster_id[k]` | Identifier of the connected component to which event `k` belongs in the spanning forest. |
| `label[k]` | One of: `single`, `mainshock`, `foreshock`, `aftershock`. |

For diagnostic and validation purposes, also produce:

- The 1-D histogram of `log₁₀ η` (should be bimodal; locate `η₀` in the valley).
- The 2-D scatter or density plot of `(log₁₀ T, log₁₀ R)` using `q = 0.5` in Equation 2 (Figure 4 of the paper).
- A list of the largest detected families with their mainshock magnitude, family size, foreshock count, and aftershock count.

---

## 12. Validation and Sanity Checks

The paper validates the algorithm against (1) synthetic ETAS catalogs with known ground truth (supporting info section D) and (2) stability tests on the observed catalog under perturbations (supporting info section E). For your implementation, the following checks are recommended in the same spirit:

1. **Bimodality check.** The histogram of `log₁₀ η` should show two distinct modes. If it is unimodal, re-check the magnitude cutoff and the parameter values.
2. **Background mode location-invariance.** Per the paper (Figure 4, paragraph [22]): "the location of the upper mode, as well as the vertical location of the lower mode, is independent of the magnitude cutoff." Re-run the algorithm with a higher `m_c` and verify the background mode is in the same place.
3. **Reproduction of known sequences.** Aftershock sequences of large, well-documented earthquakes should appear as single large families rooted at the correct mainshock. The paper's Figure 5c shows the M7.2 El Mayor-Cucapah sequence as one such family.
4. **Magnitude distributions per type.** Per Section 4.1 of the paper, mainshocks/singles and aftershocks should show approximately exponential magnitude distributions with similar b-value, while foreshocks should have a slightly higher b-value. This is a non-trivial validation because it is *not* reproduced by the simplest ETAS models.
5. **Omori-Utsu and Båth laws.** Aftershock intensity should decay as a power law with time since the mainshock (Omori-Utsu, Section 4.4 of the paper). The magnitude difference between mainshock and largest aftershock should center near 1.1–1.2 (Båth, Section 4.5 of the paper).

---

## 13. Quick Implementation Checklist

- [ ] Catalog sorted by time, ascending.
- [ ] Magnitude completeness cutoff `m_c` chosen and applied.
- [ ] `b`, `d_f` estimated (or set to paper defaults: `b=1`, `d_f=1.6`).
- [ ] Pairwise distances computed in log-space.
- [ ] Surface distance (epicentral) used for `r_ij`, depth ignored (per Section 3.1 of the paper).
- [ ] Nearest neighbor (parent) found for each event after the first.
- [ ] Histogram of `log₁₀ η` inspected; bimodality confirmed.
- [ ] `η₀` chosen in the valley (visual or GMM/EM).
- [ ] Weak links removed; spanning forest constructed via union-find.
- [ ] Clusters labeled: singles → "single"; families → mainshock (largest mag, earliest among ties), then foreshocks (before) and aftershocks (after).
- [ ] Diagnostic plots (1-D `log η` histogram, 2-D `(log T, log R)` density) produced.
- [ ] Sanity-check statistics computed and compared with Table 1 of the paper.

---

## 14. Summary of Equations and Defaults

| Symbol | Meaning | Source | Paper default |
|---|---|---|---|
| `t_ij` | `t_j - t_i` in years | Eq. 1 | — |
| `r_ij` | surface distance between epicenters in km | Eq. 1 | — |
| `m_i` | magnitude of earlier event | Eq. 1 | — |
| `b` | Gutenberg-Richter b-value | Eq. 1 | `b = 1` |
| `d_f` | fractal dimension of epicenters | Eq. 1 | `d_f = 1.6` |
| `η_ij` | pairwise space-time-magnitude distance | Eq. 1 | — |
| `η_j` | nearest-neighbor distance of event `j` | Sec. 3.1, paragraph [18] | — |
| `T_ij, R_ij` | rescaled time and space components | Eq. 2 | `q = 0.5` |
| `q` | partition parameter (visualization only) | Eq. 2 | `q = 0.5` |
| `η₀` | cluster threshold | Sec. 3.4 | `η₀ = 10⁻⁵` for SoCal `m_c=2` |
| `Δ` | offset for Δ-analysis | Sec. 2.3 | `Δ = 2` |

---

## 15. Reference

Zaliapin, I., & Ben-Zion, Y. (2013). Earthquake clusters in southern California I: Identification and stability. *Journal of Geophysical Research: Solid Earth*, 118(6), 2847–2864. https://doi.org/10.1002/jgrb.50179
