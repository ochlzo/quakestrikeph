# Training Document: How the Zaliapin–Ben-Zion Clustering Algorithm Works
> **Who this is for:** Junior developers on the QuakestrikePH team. No seismology
> or machine learning background assumed. C++ experience helpful but not required
> for reading this document — the code is explained line by line where it matters.
>
> **What you will understand after reading this:** Why we cluster earthquakes, how
> the algorithm decides which earthquakes are related, exactly how the C++ code
> implements each step, and what the final output looks like.

---

## How to Read This Document

This document builds one idea at a time. Read it in order:

1. **The problem** — why we need to cluster earthquakes at all
2. **The big idea** — the concept behind the algorithm in one analogy
3. **The three ingredients** — what goes into the relatedness formula
4. **The formula** — what it means, variable by variable
5. **Step 1: Reading and sorting the data** — code walkthrough
6. **Step 2: Computing the nearest neighbor distance** — the core calculation
7. **Step 3: Picking the threshold** — how we decide what "related" means
8. **Step 4: Building clusters** — grouping events using the threshold
9. **Step 5: Labeling events** — mainshock, foreshock, aftershock, or single
10. **Step 6: Writing the output** — what the final CSV contains
11. **The file map** — which file does what, at a glance

---

## Part 1: The Problem We're Solving

Imagine you are looking at a list of 100,000 earthquakes that happened in the
Philippines between 2018 and 2026. Some of these earthquakes **caused** others.
A large M6 quake cracks the crust, redistributes stress, and triggers smaller
quakes nearby in the hours, days, or weeks that follow. These are called
**aftershocks**, and the M6 that started it is called the **mainshock**.

But not every nearby earthquake is an aftershock. Two unrelated earthquakes can
happen in the same region by coincidence, with no causal link at all.

**The question is: for every earthquake in the catalog, which earlier earthquake
(if any) caused it?**

Answering this question for every event in the catalog is called **cluster
identification**. The output labels each earthquake as one of four roles:

| Label | Meaning |
|---|---|
| `mainshock` | The largest earthquake in a related group (the "parent event" that started the sequence) |
| `aftershock` | An earthquake that happened after the mainshock in the same group |
| `foreshock` | An earthquake that happened before the mainshock in the same group (recognized in hindsight) |
| `single` | A standalone earthquake with no detected relatives — also called a background event |

This labeled dataset is what feeds the machine learning pipeline downstream.
Without it, the ML model has no way to know which events are part of sequences
and which are isolated — a distinction that is critical for aftershock prediction.

---

## Part 2: The Big Idea

Before getting into formulas, here is the core intuition in a single analogy:

> Imagine you're at a crowded party. You want to identify family groups. You
> could use a fixed rule: "anyone standing within 3 feet of each other is family."
> But that fails — family members drift apart, and strangers sometimes stand close.
>
> A smarter approach: for each person, find their **closest companion** — but
> define "closeness" not just by distance, but by a combination of *how far apart
> they are*, *how long they've been separated*, and *how charismatic (influential)*
> the older person is. Then look at the distribution of all these closeness scores.
> You'll see a clear gap between "real family" closeness and "random stranger"
> closeness. Draw the line in the gap.

That is exactly what Zaliapin–Ben-Zion does:

1. For each earthquake, define a **relatedness score** to every earlier earthquake
   (combining time, distance, and magnitude of the earlier quake).
2. Each earthquake keeps only its **single most-related predecessor** (its parent).
3. The **distribution of all these scores** reveals a natural gap between real
   parent-child links and coincidental ones.
4. Cut the weak links in that gap → groups of related earthquakes emerge.

---

## Part 3: The Three Ingredients

The algorithm combines three observations into one number:

### Ingredient 1: Time apart

If earthquake B happens 5 minutes after earthquake A, they are probably related.
If B happens 50 years after A, almost certainly not. **More time = less related.**

### Ingredient 2: Distance apart

If B happens 3 km from A, probably related. If B happens 3,000 km away, probably
not. **More distance = less related.**

### Ingredient 3: The magnitude of the earlier quake

This is the clever part. A magnitude 7 earthquake ruptures hundreds of kilometers
of fault. It can trigger aftershocks hundreds of kilometers away, lasting for
years. A magnitude 3 earthquake might only trigger aftershocks within a few
kilometers, lasting hours.

**Bigger earlier quake = bigger "reach" in both space and time** = the same time
and distance values count as "more related" when the earlier quake was large.

The key insight: **you cannot use fixed time and distance windows.** The window
must scale with the magnitude of the earlier quake.

---

## Part 4: The Formula

The algorithm combines all three ingredients into a single number called **η
(eta)**. Small η = closely related. Large η = unrelated.

```
η_ij = t_ij × (r_ij)^d_f × 10^(−b × m_i)
```

Let's decode each piece:

| Symbol | Name | What it is | Effect on η |
|---|---|---|---|
| `t_ij` | Time difference | `t_j - t_i` in **years** | Larger → η grows → less related |
| `r_ij` | Surface distance | Distance in **km** between epicenters (lat/lon only, depth ignored) | Larger → η grows → less related |
| `d_f` | Fractal dimension | A regional constant describing how earthquakes are spatially distributed. Set to `1.6` by default (from the paper). | Shapes how strongly distance affects η |
| `b` | b-value | Describes how earthquake frequency scales with magnitude in your region. Set to `1.0` by default. | Shapes how strongly magnitude affects η |
| `m_i` | Magnitude of the earlier event | The larger event's magnitude | **Larger → η shrinks → more related** (note the minus sign) |

**Why the minus sign on magnitude matters:** The term `10^(−b × m_i)` gets
*smaller* as magnitude increases. So a large earlier quake makes η smaller for
the same time and distance — meaning later events appear "more related" to it.
This is how the algorithm captures the reality that large earthquakes have wider
influence.

### Why we compute in log-space

Direct multiplication of `t_ij`, `r_ij`, and the magnitude term can produce
extremely tiny numbers (like 0.000000001) that are hard for computers to represent
precisely. Instead, we compute:

```
log₁₀(η_ij) = log₁₀(t_ij) + d_f × log₁₀(r_ij) − b × m_i
```

This is mathematically identical (because `log(A × B) = log(A) + log(B)`) but
numerically safer. The C++ code works in log-space throughout.

### The three parameters

| Parameter | Default value | How it's chosen |
|---|---|---|
| `b` (b-value) | `1.0` | Estimated from the magnitude distribution of your catalog |
| `d_f` (fractal dimension) | `1.6` | Estimated from the spatial distribution of epicenters |
| `η₀` (threshold) | Determined per run | Chosen by inspecting the histogram of all η values (explained in Part 7) |

---

## Part 5: Step 1 — Reading and Sorting the Data

**Files involved:** [`diagnostics.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/diagnostics.hpp), [`diagnostics.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/diagnostics.cpp)

### What the Event struct holds

Before reading any code, understand what a single earthquake record looks like
inside the program:

```cpp
// diagnostics.hpp
struct Event {
    std::size_t event_id{};    // unique ID assigned as we read rows
    std::string origin_time;   // the raw date-time string from the CSV
    double latitude{};         // degrees north
    double longitude{};        // degrees east
    double depth_km{};         // depth below surface (not used in η formula, stored for output)
    double magnitude{};        // Richter magnitude
    std::string location_text; // human-readable location description
    std::string month;         // month name string
    int year{};                // calendar year
    long long sort_time{};     // the origin time converted to integer seconds since epoch
                               // This is what the code uses for ALL time comparisons
};
```

`sort_time` is the most important field. It is the date and time of the
earthquake converted into a single big integer (seconds since a fixed reference
point). This makes time comparisons simple: `t_j - t_i` is just
`events[j].sort_time - events[i].sort_time`.

### Parsing the date-time

The PHIVOLCS CSV stores dates like `"8 June 2026 - 10:30 AM"`. The function
`parse_origin_time()` converts this into `sort_time`:

```cpp
// diagnostics.cpp — simplified explanation of what parse_origin_time does:
// 1. Reads day, month name, year, and HH:MM AM/PM from the string
// 2. Converts the month name ("June") to a number (6)
// 3. Converts AM/PM 12-hour time to 24-hour time
// 4. Uses days_from_civil() — a well-known algorithm — to get a day count
//    from the calendar date
// 5. Multiplies by 86400 (seconds per day) and adds hours and minutes
// Result: sort_time in seconds, comparable across any two events
```

### Sorting by time

After parsing, all events are sorted by `sort_time` in ascending order:

```cpp
// diagnostics.cpp
std::sort(catalog.events.begin(), catalog.events.end(),
          [](const Event& lhs, const Event& rhs) {
              return lhs.sort_time < rhs.sort_time;
          });
```

**Why this matters:** The algorithm requires that for any pair `(i, j)`, event `i`
happened before event `j`. Sorting upfront guarantees this — and lets the inner
loop for each event `j` only scan `i < j`, cutting the work in half.

### Filtering by magnitude cutoff

In [`nn_main.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nn_main.cpp) and [`cluster_main.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/cluster_main.cpp), the first thing that happens after reading
the catalog is filtering:

```cpp
// nn_main.cpp and cluster_main.cpp
const auto filtered = nearest_neighbor::filter_by_magnitude(
    catalog.events, minimum_magnitude);  // default: m_c = 1.0 (why: see below)
```

The `filter_by_magnitude` function (in `nearest_neighbor.cpp`) is straightforward:

```cpp
// nearest_neighbor.cpp
std::vector<diagnostics::Event> filter_by_magnitude(
    const std::vector<diagnostics::Event>& events,
    double minimum_magnitude) {
    std::vector<diagnostics::Event> filtered;
    for (const auto& event : events) {
        if (event.magnitude >= minimum_magnitude) {
            filtered.push_back(event);
        }
    }
    return filtered;
}
```

Only events with `magnitude >= m_c` continue to the next step.

**Why mc_1_0 and not mc_2_0 (like the paper)?** We ran the histogram at three
thresholds — mc_1_0, mc_2_0, and mc_3_0 — and the shape of the `log₁₀(η)`
distribution did not change meaningfully across all three runs. This directly
confirms the algorithm's stability claim from the paper. Since the result is
identical and mc_1_0 retains the most events (giving the model more training
data), we chose mc_1_0. See Part 7 for details on what the histogram showed.

---

## Part 6: Step 2 — Computing the Nearest-Neighbor Distance

**Files involved:** [`nearest_neighbor.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor.hpp), [`nearest_neighbor.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor.cpp)

This is the heart of the algorithm. For every event `j`, we compute η to every
earlier event `i`, and keep the smallest one. The earlier event that gives the
smallest η is `j`'s **parent** (nearest neighbor).

### Pre-computing expensive values

Before the main loop begins, the code pre-computes values that will be needed
repeatedly — specifically, the latitude and longitude converted to radians (for
the distance formula), and the magnitude term `b × m_i`:

```cpp
// nearest_neighbor.cpp
struct EventTerms {
    double lat_rad{};         // latitude in radians (pre-converted from degrees)
    double lon_rad{};         // longitude in radians
    double cos_lat{};         // cosine of latitude (used in the distance formula)
    double magnitude_term{};  // b_value × event.magnitude (the part of η from magnitude)
};
```

Pre-computing these saves recalculating them inside the inner loop, which runs
millions of times.

### The main nested loop

```cpp
// nearest_neighbor.cpp — compute_nearest_neighbors()
for (std::size_t j = 0; j < events.size(); ++j) {
    results[j].event_id = events[j].event_id;
    if (j == 0) {
        continue;  // The very first event has no predecessors — skip it.
    }

    double best_log_eta = std::numeric_limits<double>::infinity(); // start at "infinitely unrelated"
    std::optional<std::size_t> best_parent;

    for (std::size_t i = 0; i < j; ++i) {  // check every earlier event
        // Step A: compute time difference in seconds
        const long long seconds = events[j].sort_time - events[i].sort_time;
        if (seconds <= 0) {
            continue;  // same time or in wrong order — skip (η would be infinity)
        }
        const double years = seconds_to_years(seconds);  // convert to years

        // Step B: compute surface distance in km
        const double distance = surface_distance_km(terms[i], terms[j]);
        if (distance <= 0.0) {
            continue;  // co-located events — skip (log(0) is undefined)
        }

        // Step C: compute log₁₀(η) using the formula
        // log₁₀(η) = log₁₀(t) + d_f × log₁₀(r) − b × m_i
        const double log_eta = std::log10(years) +
                               fractal_dimension * std::log10(distance) -
                               terms[i].magnitude_term;  // terms[i].magnitude_term = b × m_i

        // Step D: keep the smallest η seen so far
        if (log_eta < best_log_eta) {
            best_log_eta = log_eta;
            best_parent = events[i].event_id;
        }
    }

    // Store the result: which event is j's parent, and what was the η?
    results[j].parent_id = best_parent;
    if (best_parent.has_value()) {
        results[j].log10_eta = best_log_eta;
        results[j].eta = std::pow(10.0, best_log_eta); // convert back from log-space
    }
}
```

**Walk through what happens for one event `j`:**

1. We start assuming `j` has no parent and its best η is infinity.
2. For each earlier event `i`, we compute the time gap and surface distance.
3. We compute `log₁₀(η_ij)` using the formula.
4. If this η is smaller than the best we've seen so far, we update our best.
5. After checking every earlier event, whoever gave the smallest η becomes `j`'s parent.

### How surface distance is calculated

The code uses the **Haversine formula** — a standard method for computing the
shortest distance along the surface of a sphere between two latitude/longitude
points. This is more accurate than a flat-map distance calculation for points
far apart.

```cpp
// nearest_neighbor.cpp (internal helper)
double surface_distance_km(const EventTerms& first, const EventTerms& second) {
    const double dlat = second.lat_rad - first.lat_rad;    // difference in latitude
    const double dlon = second.lon_rad - first.lon_rad;    // difference in longitude
    const double sin_lat = std::sin(dlat / 2.0);
    const double sin_lon = std::sin(dlon / 2.0);
    // Haversine formula: computes the great-circle distance
    const double a = sin_lat * sin_lat +
                     first.cos_lat * second.cos_lat * sin_lon * sin_lon;
    const double clamped = std::min(1.0, std::max(0.0, a)); // numerical safety
    return 2.0 * kEarthRadiusKm * std::asin(std::sqrt(clamped));
    // kEarthRadiusKm = 6371.0088 km
}
```

Note: **depth is ignored.** Only latitude and longitude are used, consistent with
the original paper's specification.

### What this step produces

After this step, every event (except the first) has:
- A **parent** — the earlier event that is most relatedly "close" to it
- A **nearest-neighbor distance η** (and its log₁₀ value)

At this point, every event in the catalog is connected to exactly one predecessor.
This forms one giant connected graph called the **spanning tree** — like a family
tree where every person has exactly one parent (except the very oldest ancestor).

---

## Part 7: Step 3 — Picking the Threshold (η₀)

**Files involved:** [`nearest_neighbor.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor.cpp) (histogram), [`nearest_neighbor_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor_output.cpp) (written to file)

This step is done **by the researcher, not automatically by the code.** The code
produces the data you need to make this decision; you make the decision.

### What you should see: the bimodal distribution

Take all the η values computed in Step 2 and plot a histogram of `log₁₀(η)`.
For a real seismicity catalog with genuine clustering (like PHIVOLCS data), you
will see **two humps separated by a valley**:

```
Number
of events
  │
  │                            ╭──────────╮
  │                            │          │
  │                            │          │
  │                       ╭───╯          ╰──╮
  │   ╭──╮                │                 │
  │   │  ╰──╮        ╭───╯                  ╰───
  │   │     ╰────────╯
  └───┴──────────────────────────────────────── log₁₀(η)
              ↑
       valley = where you set η₀

Left hump  = real parent-child links (clustered events, small η)  ← smaller
Right hump = coincidental nearest neighbors (background events, large η) ← dominant
```

> [!IMPORTANT]
> **What our Philippine catalog actually showed:** The histogram was **heavily
> right-skewed** — the right hump (background events) was significantly taller
> and wider than the left hump (clustered events). This tells us that in the
> Philippine catalog, most earthquakes are standalone background events rather
> than members of aftershock sequences. The two humps were still clearly
> separated by a valley, confirming the algorithm works — but the right side
> dominates.
>
> This is different from the California paper, where the two humps were more
> balanced. Philippine seismicity has proportionally more background activity
> relative to clustered sequences.
>
> **Downstream implication for ML:** Because background events (singles)
> outnumber clustered events, the labeled dataset is **class-imbalanced**.
> The ML pipeline will need to account for this (e.g., class weighting or
> resampling strategies) when training classifiers that distinguish sequence
> types.

If you see two humps (even if one dominates), the algorithm is working correctly.
If you see only one hump with no valley at all, re-examine the magnitude cutoff
and parameters.

### The code that builds the histogram

```cpp
// nearest_neighbor.cpp — log_eta_histogram()
// This groups all log₁₀(η) values into bins of width `bin_width` (default 0.1)
// and counts how many events fall in each bin.

std::map<double, std::size_t> counts;
for (const auto& result : results) {
    if (!result.parent_id.has_value()) {
        continue;  // skip the first event (no parent)
    }
    // Calculate which bin this log₁₀(η) falls into
    const auto index = static_cast<long long>(
        std::floor((result.log10_eta + 1e-9) / bin_width));
    const double lower = std::round(index * bin_width * 1000.0) / 1000.0;
    counts[lower]++;
}
```

The histogram is written to:
```
outputs/nn_diagnostics_mc_1_0/log10_eta_histogram.csv
```

You then visualize it externally (Python, Excel, etc.) and identify the valley.

### How we validated the magnitude cutoff choice

Before settling on mc_1_0, we ran `nn_main` three times with different cutoffs
and compared the histograms side by side:

| Run | Cutoff | Events included | Histogram shape |
|---|---|---|---|
| Run 1 | mc_1_0 (M ≥ 1.0) | All events | Right-skewed bimodal — background hump dominates |
| Run 2 | mc_2_0 (M ≥ 2.0) | M2.0+ only | **Identical shape** to Run 1 |
| Run 3 | mc_3_0 (M ≥ 3.0) | M3.0+ only | **Identical shape** to Runs 1 and 2 |

The shape did not change. This confirms the paper's stability claim: the cluster
structure revealed by the algorithm is not an artifact of which small events are
included. It is a real property of the catalog. Since all three choices give the
same result, we chose **mc_1_0** to retain the maximum number of events for
downstream ML training.

### Choosing η₀

| Method | How |
|---|---|
| **Visual inspection** | Plot the histogram; pick a value in the valley between the two humps. |
| **Gaussian Mixture Model (GMM)** | Fit a two-component statistical model to the `log₁₀(η)` values. The crossover point between the two components is η₀. |

The paper found `η₀ ≈ 10⁻⁵` for southern California. **Do not assume this value
applies to the Philippines.** Our catalog found a different value:

```cpp
// cluster_main.cpp — the default η₀ hard-coded from our analysis
const double eta0 = argc >= 7 ? std::stod(argv[6]) : 3.4245690866683006e-6;
//                                                    ↑ approximately 10^-5.47
//                              This was determined by analyzing the Philippine
//                              catalog histogram (mc_1_0 run). Do NOT change
//                              this without re-examining the histogram.
```

---

## Part 8: Step 4 — Building Clusters (Cutting Weak Links)

**Files involved:** [`clustering.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering.hpp), [`clustering.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering.cpp)

Once η₀ is chosen, each parent link is classified:

- **Strong link:** `η < η₀` — the event is genuinely close to its parent. The
  connection is kept. This pair is in the same cluster.
- **Weak link:** `η ≥ η₀` — the connection is coincidental. The link is cut.

Cutting weak links breaks the one giant spanning tree into many smaller trees.
Each small tree is a **cluster**. This is called the **spanning forest**.

### How the code groups events: DisjointSet

The code uses a data structure called a **DisjointSet** (also called union-find).
Think of it as a way to track which events belong to the same group, where merging
two groups is very fast.

```cpp
// clustering.cpp
class DisjointSet {
public:
    // Initialize: each event starts in its own group (group = itself)
    explicit DisjointSet(std::size_t size) : parent_(size), size_(size, 1) {
        std::iota(parent_.begin(), parent_.end(), 0); // parent[0]=0, parent[1]=1, ...
    }

    // find(): returns the "root" representative of the group containing `value`
    // Uses path compression — a trick that makes future lookups faster
    std::size_t find(std::size_t value) {
        if (parent_[value] != value) {
            parent_[value] = find(parent_[value]); // path compression
        }
        return parent_[value];
    }

    // unite(): merges the two groups containing `left` and `right`
    // If they're already in the same group, nothing happens
    void unite(std::size_t left, std::size_t right) {
        left = find(left);
        right = find(right);
        if (left == right) return; // already the same group
        // Always attach the smaller group under the larger group (union by size)
        if (size_[left] < size_[right]) std::swap(left, right);
        parent_[right] = left;
        size_[left] += size_[right];
    }
};
```

### Applying the threshold

```cpp
// clustering.cpp — cluster_events()
DisjointSet sets(events.size());

for (std::size_t i = 0; i < events.size(); ++i) {
    const auto& neighbor = neighbors[i];
    const bool strong =
        neighbor.parent_id.has_value() && neighbor.eta < eta0;  // strong link?

    rows[i].is_strong_link = strong;
    rows[i].link_type = strong ? "strong" : "weak";

    if (strong) {
        // Merge this event's group with its parent's group
        const auto parent = index_by_id.find(neighbor.parent_id.value());
        sets.unite(i, parent->second);
        // After this, events i and its parent are in the same cluster
    }
    // If weak: do nothing — the link is cut; they stay in separate groups
}
```

After looping through all events, `sets` contains the complete cluster membership
information. Events connected by chains of strong links are in the same cluster.

---

## Part 9: Step 5 — Labeling Events

**File:** [`clustering.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering.cpp)

Now that clusters are identified, each event gets a role. The logic is:

```cpp
// clustering.cpp — continued in cluster_events()

// Collect all members of each cluster
std::unordered_map<std::size_t, std::vector<std::size_t>> components;
for (std::size_t i = 0; i < events.size(); ++i) {
    components[sets.find(i)].push_back(i); // group events by their root
}

// Process each cluster
for (std::size_t cid = 0; cid < ordered_components.size(); ++cid) {
    const auto& members = ordered_components[cid];
    const bool single = members.size() == 1;  // is this cluster just one event?
```

### Singles

```cpp
    if (single) {
        row.event_role = "single";
        // A single is a standalone event. It had a weak link to its nearest
        // neighbor, and no later event formed a strong link TO it.
        continue;
    }
```

### Finding the mainshock

```cpp
// clustering.cpp — choose_mainshock()
// The mainshock is the event with the LARGEST magnitude in the cluster.
// If there's a tie, the EARLIEST one in time wins.
std::size_t choose_mainshock(
    const std::vector<std::size_t>& members,
    const std::vector<diagnostics::Event>& events) {
    return *std::max_element(
        members.begin(), members.end(),
        [&](std::size_t left, std::size_t right) {
            if (events[left].magnitude != events[right].magnitude) {
                return events[left].magnitude < events[right].magnitude; // higher mag wins
            }
            return events[left].sort_time > events[right].sort_time; // earlier time wins
        });
}
```

### Labeling the rest of the family

```cpp
    for (const auto member : members) {
        if (member == mainshock_idx) {
            row.event_role = "mainshock";
        } else if (events[member].sort_time < events[mainshock_idx].sort_time) {
            row.event_role = "foreshock";   // happened before mainshock
        } else {
            row.event_role = "aftershock";  // happened after mainshock
        }
    }
```

**The complete labeling rules, summarized:**

| Condition | Role |
|---|---|
| Cluster has 1 event | `single` |
| Cluster has 2+ events AND this event has the largest magnitude (earliest if tied) | `mainshock` |
| Cluster has 2+ events AND this event occurred before the mainshock | `foreshock` |
| Cluster has 2+ events AND this event occurred after the mainshock | `aftershock` |

---

## Part 10: Step 6 — Writing the Output

**Files involved:** [`clustering_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering_output.cpp), [`nearest_neighbor_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor_output.cpp)

### The main output: the clustered dataset CSV

The final output file is a CSV where each row is one earthquake, with all the
original fields plus the clustering results attached:

```
outputs/clustered_ml_ready_mc_2_0.csv
```

**Columns written by `write_clustered_dataset()`:**

| Column | What it contains |
|---|---|
| `event_id` | Unique earthquake ID |
| `origin_time` | Original date-time string from PHIVOLCS |
| `origin_time_years` | Decimal year (e.g., 2026.44 for June 2026) — used in seismic analysis |
| `latitude`, `longitude` | Epicenter coordinates |
| `depth_km` | Depth below surface |
| `magnitude` | Richter magnitude |
| `location_text`, `month`, `year` | Human-readable location and date fields |
| `parent_id` | Event ID of the nearest neighbor (parent). Empty if this is the first event. |
| `eta` | The nearest-neighbor distance η |
| `log10_eta` | `log₁₀(η)` — the value used for threshold comparison |
| `is_strong_link` | `true` if `η < η₀` (real connection), `false` if weak (coincidental) |
| `link_type` | `"strong"` or `"weak"` |
| `cluster_id` | Which cluster this event belongs to (integer ID, starting at 1) |
| `cluster_type` | `"single"` or `"family"` |
| `cluster_size` | How many events are in this cluster |
| `event_role` | **`"single"`, `"mainshock"`, `"foreshock"`, or `"aftershock"`** |
| `is_single` | `true`/`false` — shortcut flag |
| `is_family_member` | `true`/`false` — shortcut flag |
| `mainshock_id` | Event ID of the mainshock for this cluster (empty for singles) |
| `mainshock_time` | Date-time string of the mainshock (empty for singles) |
| `mainshock_magnitude` | Magnitude of the mainshock (empty for singles) |
| `foreshock_count_in_family` | How many foreshocks are in this family |
| `aftershock_count_in_family` | How many aftershocks are in this family |

### Diagnostic outputs from the nearest-neighbor step

When you run `nn_main` (the diagnostic executable), you get:

| File | What it contains |
|---|---|
| `nearest_neighbor_diagnostics.csv` | One row per event with its parent, η, and log₁₀(η) — used to inspect which event is paired to which |
| `log10_eta_histogram.csv` | The histogram of `log₁₀(η)` values — **the primary tool for choosing η₀** |

---

## Part 11: The Full End-to-End Flow

Here is the complete picture in one diagram:

```
PHIVOLCS CSV
(phivolcs_earthquake_2018_2026.csv)
         │
         ▼
[diagnostics::read_catalog()]          diagnostics.cpp
  - Parse each row                     ─────────────────
  - Validate date, lat, lon, depth,
    magnitude, year
  - Convert date-time → sort_time
    (integer seconds)
  - Sort all events by sort_time
  - Return: vector of Event structs
         │
         ▼
[nearest_neighbor::filter_by_magnitude()]   nearest_neighbor.cpp
  - Keep only events with               ─────────────────────────
    magnitude >= m_c (default 2.0)
  - Return: filtered event list
         │
         ▼
[nearest_neighbor::compute_nearest_neighbors()]    nearest_neighbor.cpp
  - Pre-compute lat/lon in radians,     ───────────────────────────────────
    cos(lat), and b × magnitude
    for each event
  - For each event j:
      For each earlier event i:
        - Compute time gap (seconds → years)
        - Compute surface distance (Haversine)
        - Compute log₁₀(η_ij) = log₁₀(t) + d_f×log₁₀(r) − b×m_i
        - Keep track of the smallest η and which i gave it
  - Return: NeighborResult per event
    (parent_id, eta, log10_eta)
         │
         ▼
[Inspect log₁₀(η) histogram]           Human decision step
  - Run nn_main to produce              ────────────────────
    log10_eta_histogram.csv
  - Plot the histogram
  - Identify the valley between
    the two humps
  - Choose η₀ (our value: ~3.42×10⁻⁶)
         │
         ▼
[clustering::cluster_events()]          clustering.cpp
  - For each event: is η < η₀?          ─────────────────
      YES → strong link → unite(j, parent)
      NO  → weak link  → leave separate
  - DisjointSet groups all strongly
    linked events into clusters
  - For each cluster:
      1 event  → single
      2+ events:
        - Find largest magnitude event
          (earliest if tied) → mainshock
        - Events before mainshock → foreshock
        - Events after mainshock → aftershock
  - Return: ClusteredEvent per event
         │
         ▼
[clustering::write_clustered_dataset()]   clustering_output.cpp
  - Write all ClusteredEvent fields        ──────────────────────
    to the output CSV
  - One row per earthquake
  - Each row includes original fields
    + parent, eta, cluster_id,
    cluster_type, event_role, etc.
         │
         ▼
outputs/clustered_ml_ready_mc_2_0.csv
  (the ML-ready labeled dataset)
```

---

## Part 12: The File Map

| File | Namespace | What it does |
|---|---|---|
| [`diagnostics.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/diagnostics.hpp) | `diagnostics` | Defines the `Event` struct and function signatures for catalog reading |
| [`diagnostics.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/diagnostics.cpp) | `diagnostics` | Reads and parses the PHIVOLCS CSV; sorts events by time; computes magnitude bins and statistics |
| [`diagnostics_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/diagnostics_output.cpp) | `diagnostics` | Writes diagnostic CSV files (magnitude bins, cutoff counts) and the validation report |
| [`nearest_neighbor.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor.hpp) | `nearest_neighbor` | Defines `NeighborResult`, `LogEtaBin`, and function signatures |
| [`nearest_neighbor.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor.cpp) | `nearest_neighbor` | Implements the η formula (Haversine distance + log-space computation); finds each event's parent; builds the histogram |
| [`nearest_neighbor_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nearest_neighbor_output.cpp) | `nearest_neighbor` | Writes `nearest_neighbor_diagnostics.csv` and `log10_eta_histogram.csv` |
| [`clustering.hpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering.hpp) | `clustering` | Defines `ClusteredEvent` struct (the full output record per earthquake) |
| [`clustering.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering.cpp) | `clustering` | DisjointSet implementation; applies η₀ threshold; labels events as mainshock/foreshock/aftershock/single |
| [`clustering_output.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/clustering_output.cpp) | `clustering` | Writes the final clustered CSV; handles optional fields and date formatting |
| [`main.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/main.cpp) | — | Entry point for the **diagnostics executable** — runs catalog reading and magnitude analysis only |
| [`nn_main.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/nn_main.cpp) | — | Entry point for the **nearest-neighbor diagnostic executable** — runs Steps 1–2 and writes η diagnostics and the histogram. Run this to determine η₀. |
| [`cluster_main.cpp`](file:///C:/Projects/quakestrikeph-zaliapin-clustering/src/zaliapin-ben-zion-clustering/cluster_main.cpp) | — | Entry point for the **full clustering executable** — runs the complete pipeline Steps 1–6. This produces the ML-ready output. |

### Which executable to run when

```
Run main          → just want catalog statistics and magnitude distribution
Run nn_main       → want to see η values and the histogram to choose η₀
Run cluster_main  → want the full clustered output (the ML-ready CSV)
```

---

## Part 13: Quick Reference — Parameters and Defaults

| Parameter | Code argument | Default | Meaning | When to change |
|---|---|---|---|---|
| `m_c` | `[m_c]` (3rd arg) | `2.0` | Minimum magnitude to include | When studying a different magnitude range |
| `b` | `[b]` (4th arg) | `1.0` | Gutenberg-Richter b-value | After estimating b from the Philippine catalog |
| `d_f` | `[d_f]` (5th arg) | `1.6` | Fractal dimension of epicenters | After estimating d_f from the Philippine spatial distribution |
| `η₀` | `[eta_0]` (6th arg, cluster_main only) | `3.4245690866683006e-6` | Cluster threshold | Only after re-examining the log₁₀(η) histogram |

> [!WARNING]
> **Never change η₀ without looking at the histogram first.** The default value
> was carefully determined from the Philippine catalog's bimodal distribution.
> Changing it blindly will silently mislabel thousands of events.

---

## Part 14: Sanity Checks After Running

After a full run, check these things to know the algorithm is working correctly:

- [ ] **Two humps in the histogram.** Open `log10_eta_histogram.csv` and verify
  the distribution has two distinct peaks with a valley between them. If it's
  one peak, something is wrong with the parameters or magnitude cutoff.

- [ ] **Known sequences are intact.** Pick a well-known Philippine earthquake
  sequence (e.g., the 2019 Cotabato sequence, the 2022 Abra earthquake). Find
  its mainshock in the output. Check that the known aftershocks appear in the
  same cluster with `event_role = "aftershock"`.

- [ ] **Rough label proportions.** The paper's southern California reference has
  roughly 31% singles, 6% mainshocks, 56% aftershocks, 7% foreshocks at m ≥ 2.
  **Philippine proportions are different:** our histogram was heavily
  right-skewed (background-dominant), so expect a significantly higher singles
  percentage than California's 31%. This is normal and expected — it reflects
  genuine Philippine seismicity characteristics, not a bug. What to watch for:
  if you see **virtually 0% singles**, η₀ is probably too large (cutting too
  few links). If singles are **above ~90%**, η₀ may be too small (cutting too
  many links) — but verify against the histogram valley before adjusting.

- [ ] **Every event has a cluster_id.** No row in the output CSV should have an
  empty `cluster_id`. Singles get their own cluster of size 1.

- [ ] **Every cluster has exactly one mainshock.** If you group the output by
  `cluster_id` and count rows with `event_role = "mainshock"`, every `cluster_id`
  with `cluster_type = "family"` should count exactly 1.

---

## Appendix: Key Terms at a Glance

| Term | Plain meaning |
|---|---|
| **η (eta)** | The "relatedness score" between two earthquakes. Small = closely related. Large = unrelated. |
| **η₀ (eta-zero)** | The threshold that separates "related" from "unrelated." Determined by inspecting the histogram. |
| **Nearest neighbor / parent** | For each earthquake, the single earlier earthquake that gives the smallest η. |
| **Strong link** | A parent-child connection where η < η₀. Kept. |
| **Weak link** | A parent-child connection where η ≥ η₀. Cut. |
| **Spanning tree** | The full connected graph before any links are cut — every event connected to one parent. |
| **Spanning forest** | The collection of smaller trees after weak links are cut. Each tree = one cluster. |
| **Single** | A cluster of one event. A standalone earthquake with no relatives. |
| **Family** | A cluster of two or more events connected by strong links. |
| **Mainshock** | The largest-magnitude event in a family (earliest if tied). |
| **Foreshock** | A family event that occurred before the mainshock. |
| **Aftershock** | A family event that occurred after the mainshock. |
| **DisjointSet (union-find)** | A data structure that efficiently tracks which events belong to the same group. |
| **Haversine formula** | A trigonometry formula for computing the surface distance between two lat/lon points on a sphere. |
| **b-value** | A number describing how earthquake frequency scales with magnitude in your region. Typically close to 1.0. |
| **Fractal dimension (d_f)** | A number describing the geometric pattern of earthquake epicenters. Typically 1.6. |
| **log-space computation** | Computing `log₁₀(η)` instead of η directly, to avoid numbers too tiny for the computer to represent accurately. |
| **Bimodal distribution** | A histogram with two distinct humps — the visual signature that clustering is real and detectable. |
