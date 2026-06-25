# Improving Extreme Earthquake Prediction: A Guide for the Team

> **Status:** Research proposal and modeling roadmap. This is not a validated
> production design yet. The validation checklist near the end of this document
> must be completed before anything here is shipped to production.
>
> **Audience:** Junior developers on the QuakestrikePH team. No machine learning
> background assumed. Technical field names and code references are kept but
> explained in plain language wherever they appear.

---

## How to Read This Document

This document tells a story in five parts:

1. **What we have today** — what the current system does and how it works
2. **What went wrong** — a real failure on a live earthquake sequence
3. **Why it went wrong** — the root causes, explained from first principles
4. **How we fix it** — the recommended plan, plus an alternative approach
5. **How to build it** — the concrete implementation roadmap and validation checklist

Read it in order. Each section builds on the previous one.

---

## Part 1: What We Have Today

### 1.1 The Dataset

Our current model was trained on a dataset of **124,047 earthquake events** from the
Philippine record. The file is at:

```
src/training_set/training_dataset_mc_1_0.csv
```

The `mc_1_0` in the name means **magnitude completeness = 1.0** — we include
earthquakes as small as M1.0, because PHIVOLCS (the Philippine seismic agency)
reliably records them down to that level. The more events the model sees, the
more patterns it can learn.

But here is the problem. Look at how the dataset thins out at the high end:

| Magnitude   | Number of Events |
| ----------- | ---------------: |
| >= 4.0      |            4,888 |
| >= 5.0      |              632 |
| >= 6.0      |               82 |
| >= 7.0      |                **8** |

The largest earthquake in our training data is **M7.4**. We have trained the
model almost entirely on small-to-medium earthquakes, with almost nothing at the
large end. An M7.8 earthquake — bigger than our biggest training example — is
essentially invisible to the model.

### 1.2 What the Model Predicts

Think of the model as an expert guesser. When a new earthquake happens, you feed
it information about the event and it outputs two kinds of answers.

**Probabilities (classification):** *"What are the chances of aftershocks, and
where?"*

The model produces all distance-range probabilities from a single unified
prediction called `aftershock_spatial_zone_24h`. This one internal prediction is
then translated into the public-facing outputs:

```
aftershock_24h                  → probability that any aftershock happens in 24h
aftershock_within_10km_24h      → probability it happens within 10 km
aftershock_within_25km_24h      → probability it happens within 25 km
aftershock_within_50km_24h      → probability it happens within 50 km
aftershock_beyond_50km_24h      → probability it happens beyond 50 km
```

Using a single source for all of these is intentional and important — it keeps
the five probabilities consistent with each other. If each came from its own
independent model, they could contradict each other (e.g., "60% within 10km"
and "20% within 50km" would make no sense).

**Estimates (regression):** *"How bad will it be?"*

```
max_aftershock_mag_24h              → expected maximum aftershock magnitude in 24h
nearest_aftershock_distance_km_24h  → expected distance to the nearest aftershock
median_aftershock_distance_km_24h   → median distance across all aftershocks
p90_aftershock_distance_km_24h      → 90th-percentile distance (how far the outliers go)
```

### 1.3 What the Model Is Built From

The model reads a set of computed features for each event — numbers that describe
the earthquake and its local seismic context. Some of these already encode
known earthquake science:

| Feature | What it means in plain language |
|---|---|
| `rupture_depth_attenuation` | How much the depth of the quake weakens its surface impact |
| `seis_traffic_ratio_30d` | How busy the local area has been seismically in the last 30 days |
| `baths_law_limit` | A quick estimate of the biggest expected aftershock (mainshock magnitude − 1.2). Note: this is computed from the live event, not a confirmed mainshock label. |
| `local_b_value_50km_3y` | A measure of how the earthquake frequency varies with magnitude in the local area over the past 3 years |

The model type is a **tree ensemble** — specifically a combination of
XGBoost, LightGBM, CatBoost, and Random Forest. These are explained further in
Part 3.

---

## Part 2: What Went Wrong

### 2.1 The Sarangani Sequence (June 8, 2026)

On June 8, 2026, an M7.8 earthquake struck Sarangani. Our model was running live.
Here is what it predicted, versus what actually happened:

| Event           | Model Predicted (Max Aftershock) | Actually Observed |
| --------------- | -------------------------------: | ----------------: |
| **M7.8 mainshock**  | **M4.31**                    | **M6.4** ← severe miss |
| M4.1 aftershock |                             M5.70 | M5.5 ✓ (close)    |

The model was **catastrophically wrong on the M7.8 event** — off by more than
2 magnitude units. In terms of energy, that is roughly a 1,000× difference.

The model was **reasonably accurate on the M4.1 aftershock** that came later.

This contrast is the key clue. It tells us exactly where the system breaks down —
and why.

---

## Part 3: Why It Went Wrong

There are three root causes, each building on the previous.

### 3.1 Root Cause #1: The Model Has Never Seen a Quake This Big

An analogy:

> Imagine you teach someone to estimate house prices by showing them thousands of
> homes sold between $50,000 and $500,000. Then you ask them to price a $10 million
> mansion. They have no frame of reference. They will dramatically underestimate it,
> because they have never seen that price range.

Our model has seen 8 earthquakes at M7.0 or above, with the biggest at M7.4.
When it encounters an M7.8, it is being asked to make a judgment call that is
entirely outside its experience.

This directly impacts predictions for:
- Maximum expected aftershock magnitude
- Probability of a damaging aftershock
- Aftershock count / sequence productivity
- Spatial spread of the aftershock zone

### 3.2 Root Cause #2: Tree Models Cannot Extrapolate

The current model family — XGBoost, LightGBM, CatBoost, Random Forest — are all
**tree ensembles**. A decision tree works by splitting data into buckets using
if/else rules learned from training:

```
Is magnitude > 6.5?
  YES → Is depth < 30 km?
         YES → Predicted max aftershock = 5.8
         NO  → Predicted max aftershock = 5.2
  NO  → Is magnitude > 5.0? ...
```

The problem: **the rules only cover what was seen in training.** Once a new
earthquake exceeds the highest magnitude split the model ever learned (M7.4 in
our case), every larger event falls into the same final bucket. The output is
frozen — it cannot grow to reflect a physically more severe event.

```
What the model sees vs. reality:

Training max = M7.4
                     M7.4    M7.8    M8.2
Tree output:  ───────[5.8]───[5.8]───[5.8]───  ← stuck at the last bucket
True pattern: ───────[6.4]───[6.6]───[7.0]───  ← should keep growing
```

This is a fundamental limitation of the tree model family. It is not a bug — it
is how trees are designed. They are excellent at finding patterns *within* the
training range, but they cannot project beyond it.

> **For the record:** Bath's Law — a 200-year-old empirical rule — simply says:
> biggest aftershock ≈ mainshock magnitude − 1.2.
> For M7.8: 7.8 − 1.2 = **M6.6** (actual: **M6.4** ✓).
> Our model predicted M4.31. A simple physics formula significantly outperformed
> the ML model on this event. This is a strong signal that physics should anchor
> our predictions for extreme events.

### 3.3 Root Cause #3: The First Event Has No History to Work With

Many of the model's most useful inputs are backward-looking — they describe what
has already happened nearby:

- How many earthquakes in the last 30 days?
- What was the most recent large nearby event?
- What is the accumulated local seismic energy?

When the **M4.1 aftershock** occurred, the model could see the M7.8 in the recent
history window. That was a powerful signal — it told the model "a massive event
just happened nearby." The M4.1 prediction was decent as a result.

But when the **M7.8 itself** struck, the history window was quiet. Nothing
unusual had happened yet. The model was flying blind, relying only on magnitude,
depth, and static location context. That is not enough for a once-in-a-decade
event.

This is sometimes called the **cold start problem** — the same challenge a
recommendation system faces when a brand-new user has no listening history. There
is simply no data to work with yet.

### 3.4 Root Cause #4: Aggregate Metrics Hide the Problem

Our evaluation scores (MAE, RMSE, R², AUC) look at average performance across all
events. With 124,047 events, 8 large earthquakes are a rounding error.
A perfect score on 124,039 common events can completely hide a catastrophic failure
on the 8 rare ones.

We need **stratified evaluation** — separate performance metrics per magnitude
bucket — to see the true failure mode.

---

## Part 4: How We Fix It

The root cause is clear: the model has not seen enough large earthquakes. The fix
is to show it more of them — from the global record.

### 4.1 Recommended Fix: Bring In Global Training Data

Large earthquakes are rare in the Philippines, but they happen regularly elsewhere.
Japan, Chile, and Sumatra experience M7+ and M8+ events far more often. Their
seismic records give us what the Philippine-only dataset cannot: **real examples of
what a massive earthquake sequence looks like.**

The goal is not to replace Philippine data. It is to supplement it specifically
for the high-magnitude range where our local data is too thin.

#### 4.1.1 Which Regions to Use

We should prioritize regions with the same **tectonic setting** as the Philippines.
The Philippines sits on a subduction zone — where one tectonic plate dives under
another. The same physics governs aftershock behavior in comparable zones:

| Candidate Region | Why It's Relevant |
|---|---|
| Japan | Same subduction-zone setting; excellent data quality and density |
| Sumatra | Very similar tectonic environment to the Philippines |
| Chile | Subduction zone with some of the largest recorded earthquakes |
| Mariana / Tonga / Kuril | Pacific Ring of Fire, same plate boundary dynamics |

We should also test continental regions but not assume they are comparable. The
right approach is to run **ablation studies** — train with and without each region,
measure the impact on Philippine prediction quality, and let the numbers decide.

#### 4.1.2 The Catalog Completeness Problem

There is a critical data compatibility issue to solve first.

PHIVOLCS records earthquakes down to **M1.0+** reliably. The global USGS catalog
is generally only reliable at **M4.0+** across all regions and time periods.

If we naively merge both catalogs, we break features like rolling event counts:

- The Philippine model "knows" that 50 earthquakes happened nearby last month
  (counting everything M1.0+).
- The global model only "sees" 3 of those (the ones above M4.0).
- The model thinks the area was nearly silent, when it wasn't.

**The fix:** apply a **magnitude completeness threshold of M4.0** to the global
data path. All features that count events, compute rates, or estimate local energy
must be recalculated using only M4.0+ events for the global model. This model
path is called `mc_4_0` (magnitude completeness = 4.0) to distinguish it from the
existing `mc_1_0` (Philippine) path.

#### 4.1.3 The Two-Model Architecture

This leads to running two model pipelines:

```
Any earthquake is reported
         │
         ▼
      ROUTER
  "Is magnitude >= 4.0?"
         │
    YES  │  NO
         │
  ┌──────┴──────────────────────────────┐
  │                                     │
  ▼                                     ▼
mc_4_0 path                         mc_1_0 path
(global-compatible model)           (local Philippine model)
  - Only counts M4.0+ events           - Counts all M1.0+ events
  - Trained on Philippines             - Trained on Philippines only
    + global similar regions           - Strong on common small quakes
  - Better for rare large quakes
  │                                     │
  └──────────────┬──────────────────────┘
                 │
                 ▼
        Calibrated output
     → served to public / operators
```

The router runs first and is essentially free to compute — it is just a magnitude
threshold check. Only one model runs per prediction.

**Important:** the threshold of M4.0 creates a boundary. An M3.9 and an M4.1 are
physically almost identical but would get routed to different models. To avoid
jarring discontinuities, use a conservative transition band (e.g., route anything
≥ M3.8 to `mc_4_0` as well), or keep the local `mc_1_0` path running in parallel
for comparison until validation confirms a clean cutoff point.

> **Keep calibration separate per path.** Calibration means making the model's
> confidence scores honest and trustworthy — if the model says "70% chance of a
> damaging aftershock," we want that to mean 7 in 10 similar events actually had
> one. Each model path has different biases and needs its own calibration
> correction step.

#### 4.1.4 Training Strategies to Test

We should not assume that simply mixing global data with Philippine data produces
the best result. We need to test multiple strategies and pick the one that
improves Philippine predictions the most:

| Strategy | How It Works | When It Wins |
|---|---|---|
| **Local-only `mc_4_0`** | Retrain Philippine-only model at M4.0+ threshold | Baseline comparison |
| **Global-only `mc_4_0`** | Train entirely on global data | Unlikely to win overall, but useful as a component |
| **Global + local joint** | Mix both datasets; add a `tectonic_region` feature so the model knows where data comes from | Likely strong starting point |
| **Global pretrain → PH fine-tune** | Train on global data first, then re-specialize on Philippine data | Best conceptual fit; like how LLMs learn general language then specialize |
| **Global + local with PH weighting** | Mix both but give Philippine events higher importance during training | Simpler alternative to fine-tuning |

The **global pretrain → Philippine fine-tune** approach is conceptually the most
robust. Think of it like how a language model learns general English from all of
the internet, then gets specialized on a specific domain. The model first learns
"what does an M7.8 sequence look like globally?" and then "how does the Philippines
specifically behave?"

#### 4.1.5 New Prediction Targets

While the global data approach improves the *accuracy* of existing predictions, we
should also add new targets that more directly answer "how bad is this sequence?"

**Tier 1 — Add these first:**

| Target | What it predicts |
|---|---|
| `aftershock_count_24h` | How many aftershocks in the next 24 hours? |
| `aftershock_count_72h` | How many in 72 hours? |
| `max_aftershock_mag_72h` | Biggest aftershock in 3 days? |
| `m5_plus_aftershock_24h` | Will there be a damaging M5+ aftershock? |
| `m5_plus_aftershock_72h` | Same, but 72-hour window |

**Tier 2 — Add when Tier 1 is stable:**

| Target | What it predicts |
|---|---|
| `stronger_aftershock_24h` | Will the next quake be *bigger* than this one? |
| `stronger_aftershock_72h` | Same, 72-hour window |
| `time_to_first_aftershock_if_any` | How soon will the first aftershock arrive? |
| `nearest_aftershock_distance_band_if_any` | Rough distance band to the nearest aftershock |

> **Note on count targets:** Earthquake counts are not evenly distributed — they
> are **count data**, heavily skewed (many sequences with 0–2 aftershocks, very
> few with 50+). Standard regression is not the right tool for this. Use
> **Poisson regression** or **Tweedie regression** for count targets, or at
> minimum apply a `log1p(count)` transformation. Using the wrong method here
> systematically underestimates high-count sequences.

---

### 4.2 Alternative Fix: Neural Networks for Better Extrapolation

> **Status:** Alternative option. Not the current focus. Captured here for
> awareness and future consideration. The global data plan (Section 4.1) is the
> recommended path.

The extrapolation problem (Root Cause #2) can also be partially addressed by
switching model families. Tree ensembles freeze at the training boundary. Neural
networks learn smooth continuous functions that can extend beyond it.

```
Training max = M7.4

Tree output:    ───────[5.8]───[5.8]───[5.8]───  ← frozen
Neural net:     ───────[6.3]───[6.7]───[7.1]───  ← continues the curve
```

**Important caveat:** a neural network extrapolates in whatever direction its
learned curve was heading — not necessarily the physically correct direction. If
the curve was flattening off at M7.0, the extrapolation will follow that flatten.
Extrapolation is not automatically *correct* extrapolation.

The most robust version of this idea is a **Physics-Informed approach**:

1. Compute a physics-based baseline (e.g., Bath's Law: max aftershock ≈ mainshock − 1.2)
2. Train a neural network to predict the *residual* — how much does this specific
   event deviate from the physics baseline?
3. Final prediction = physics baseline + neural network residual

This constrains the extrapolation to follow known seismic laws rather than
whatever the data happened to suggest. Architecture options for tabular data
include **TabNet** and **FT-Transformer** — neural network designs purpose-built
for structured/tabular input like ours.

**Why this is secondary to the global data plan:**

- Global data gives the model *real observed examples* of M7.8+ sequences.
  Neural network extrapolation is still a mathematical approximation.
- Real data beats mathematical extrapolation. If we can bring in enough global
  M7+ events, the model no longer needs to extrapolate at all — it is
  interpolating from seen examples.
- Neural networks are also harder to tune, interpret, and maintain for a team
  without deep ML experience. Tree ensembles are more debuggable and well
  understood by the existing pipeline.

This path should be revisited if the global data plan does not close the gap on
M7+ prediction quality.

---

## Part 5: How to Build It

### 5.1 Implementation Roadmap

#### Stage 1: Collect and Clean Global Catalog

1. Download global earthquake catalog data (USGS Earthquake Catalog, ISC catalog).
2. Filter by tectonic region — prioritize subduction zones (Japan, Sumatra, Chile,
   Mariana, Tonga, Kuril).
3. Normalize schema to match the local pipeline core fields:
   ```
   origin_time
   latitude
   longitude
   depth_km
   magnitude
   catalog_source
   tectonic_region
   ```
4. Apply and document the `mc_4_0` completeness threshold. Record the threshold
   per catalog, region, and time range. Do not assume M4.0 is universally correct
   everywhere — verify where possible.

#### Stage 2: Rebuild Sequence Labels from Scratch

Do **not** import sequence labels from foreign catalogs. Different catalogs define
"aftershock sequences" differently. Recompute all labels using the same
forward-window labeling logic already used by the local pipeline, applied to the
global event records.

Labels to recompute:
```
aftershock_spatial_zone_24h
aftershock_24h
max_aftershock_mag_24h
nearest/median/p90_aftershock_distance_km_24h
```

Then extend with the new Tier 1 count and escalation labels.

#### Stage 3: Rebuild Features for the mc_4_0 Path

All rolling window features must be recomputed using only M4.0+ events for the
global path. A feature that was previously computed as "count of all earthquakes
in 30 days" must become "count of M4.0+ earthquakes in 30 days" in the `mc_4_0`
path. This is not optional — mixing incompatible feature definitions across paths
will silently corrupt model inputs.

Recommended additions to the feature set:

| Feature | Why it helps |
|---|---|
| Cumulative seismic moment over recent windows | Captures total energy release, not just event count |
| Maximum recent magnitude over wider spatial windows | Gives the model awareness of the largest recent event in the region |
| `tectonic_region` label | Lets the model distinguish subduction-zone from transform-fault behavior |
| Slab depth, trench distance (where available) | Physically motivated for subduction-zone depth patterns |

**Save a feature manifest for each model path.** A feature manifest is a saved
list of every feature, how it is computed, and what parameters it uses. This is
required for reproducing results and for ensuring training and serving use
identical feature definitions. Two paths = two manifests.

#### Stage 4: Train and Compare Candidate Models

Train all five strategies listed in Section 4.1.4. Track metrics for:
- Classification targets (zone, aftershock probability)
- Regression targets (max magnitude, distances)
- Count targets (aftershock counts, M5+ escalation)

Do not limit evaluation to only the magnitude regressor. The count and escalation
targets matter equally for public risk communication.

#### Stage 5: Evaluate on Philippine Events Only

All evaluation for production decisions must use a **Philippine-only temporal
holdout** — a time period of Philippine events not seen during training.

Required breakdowns:
- Metrics per magnitude bucket: `M < 4`, `M4–M5`, `M5–M6`, `M6–M7`, `M >= 7`
- Metrics split by: initiating event vs. event with known large-event history
- Calibration curves for each model path's probability outputs
- Stress-test results for major known Philippine sequences (Sarangani required)

> **Do not tune on Sarangani.** Reserve it as a pure stress test — the same
> way you would not train a model on your test data. If you tune parameters to
> fit Sarangani, you will not know how the model performs on the *next* unknown
> large event.

---

### 5.2 Feature Engineering Notes

Some features already exist and should be preserved exactly:

```
rupture_depth_attenuation
seis_traffic_ratio_30d
baths_law_limit
local_b_value_50km_3y
```

One clarification: `baths_law_limit` is computed as `event_magnitude - 1.2`. This
is a live-event proxy, not a confirmed mainshock feature. A live event is not
guaranteed to be the final mainshock of its sequence (a larger event may follow).
The field name can stay, but the team should document this nuance in comments.

---

## Part 6: Validation Checklist

Complete all items below before treating any part of this roadmap as a production
model design. Until then, the existing `mc_1_0` Philippine model remains the
serving model.

- [ ] **Reproduce the Sarangani failure.** Rerun the June 8 prediction using saved
  inputs and record the output JSON as an official artifact. Right now it is
  operator-observed only — it needs to be a reproducible benchmark.

- [ ] **Build a stress-test folder.** Create a folder of handpicked major Philippine
  sequences with saved prediction inputs and expected outputs. This becomes the
  permanent regression test suite for large-event behavior.

- [ ] **Add stratified magnitude metrics.** Report separate performance numbers for
  `M < 4`, `M4–M5`, `M5–M6`, `M6–M7`, and `M >= 7`. Aggregate metrics
  (overall MAE, R², AUC) are not sufficient to catch tail failures.

- [ ] **Compare mc_1_0 vs mc_4_0 on Philippine holdout.** Measure both paths on the
  same Philippine events. Do not ship `mc_4_0` unless it meaningfully improves
  M6+/M7+ predictions without degrading common-event accuracy.

- [ ] **Validate that global data improves max-aftershock prediction.** Specifically
  check that `max_aftershock_mag_*` improves for M6+ initiating events, and
  that `aftershock_24h` calibration is not degraded on common M2–M4 events.

- [ ] **Evaluate count and M5+ escalation targets.** Do not evaluate only the
  magnitude regressor. Count and escalation targets are operationally critical
  and must be measured separately.

- [ ] **Audit all features for data leakage.** Every feature used in training must
  be computable from information available at prediction time — before the
  aftershock window opens. Any feature that depends on what happens after the
  event is leakage and will silently inflate evaluation metrics while
  producing garbage in production.

- [ ] **Save all artifacts.** For every stress-test case: save the model version,
  feature manifest, input features, and prediction output JSON. Without these,
  results cannot be reproduced or compared across model versions.

---

## Appendix: Key Terms Reference

| Term | Plain meaning |
|---|---|
| **mc_1_0** | Magnitude completeness = 1.0. The Philippine model that uses all events down to M1.0. |
| **mc_4_0** | Magnitude completeness = 4.0. The global-compatible model that only uses M4.0+ events. |
| **Extrapolation** | Predicting beyond the range of values seen in training. Tree models cannot do this. |
| **Calibration** | Making the model's probability scores honest — "70% confidence" should mean true 70% of the time. |
| **Cold start** | When a new event has no local history to draw on, weakening the model's feature signal. |
| **Data leakage** | Accidentally using future information as a training input, making the model look better than it really is. |
| **Tree ensemble** | A model family (XGBoost, LightGBM, etc.) that learns if/else rules. Accurate inside training range; cannot extrapolate. |
| **Neural network (tabular)** | A model family that learns smooth functions. Can extrapolate beyond training range, but may not extrapolate correctly without physics constraints. |
| **Poisson regression** | A regression method designed for count data (how many aftershocks?). More appropriate than standard regression for skewed count targets. |
| **Bath's Law** | Empirical rule: the largest aftershock is typically ~1.2 magnitude units smaller than the mainshock. A useful physics anchor for large events. |
| **Fine-tuning** | Train on global data first to learn general patterns, then continue training on Philippine data to specialize. Like learning a skill generally before mastering the local version. |
| **Feature manifest** | A saved document describing every feature, how it is computed, and what parameters it uses. Required for reproducibility and consistent training/serving behavior. |
| **Stratified evaluation** | Evaluating model performance separately per subgroup (e.g., per magnitude bucket) rather than as a single aggregate score. |
| **Ablation study** | Testing with one thing removed to measure its isolated contribution. E.g., train without Japan data to see how much Japan data actually helps. |
