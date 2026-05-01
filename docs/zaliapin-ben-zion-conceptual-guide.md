# Zaliapin & Ben-Zion (2013a): A Conceptual Deep Dive

A plain-language guide to the cluster identification method of Zaliapin & Ben-Zion (2013a) for finding mainshock-aftershock sequences in earthquake catalogs. This is the conceptual companion to the end-to-end algorithm document; both are based strictly on the same 2013a paper.

---

## The Core Question

Imagine you have thousands of earthquakes scattered across space and time. Some of them are related — a big quake triggered smaller ones nearby. Others are unrelated — they just happened to occur in the same region by coincidence over decades.

**How do you tell which is which?**

Your gut says: "Earthquakes that are close together in space *and* close in time are probably related." That's correct, but it's incomplete. Zaliapin-Ben-Zion makes this intuition precise by adding a third ingredient: **magnitude**.

---

## The Three Ingredients

Think about what makes two earthquakes "related":

**1. Time proximity.** If quake B happens 5 minutes after quake A, they're probably related. If B happens 50 years after A, probably not.

**2. Space proximity.** If B happens 2 km from A, probably related. If B happens 2,000 km away, probably not.

**3. The size of the earlier quake.** This is the clever part. A magnitude 7 earthquake can trigger aftershocks hundreds of kilometers away, lasting for years. A magnitude 4 earthquake might only trigger aftershocks within a few kilometers, lasting days. **Big earthquakes have big "reach" in both space and time.**

So when you ask "are these two quakes related?", you can't use fixed thresholds like "within 10 km and 1 week." The threshold should *scale* with the magnitude of the earlier quake.

---

## The Distance Formula (Plain English Version)

Zaliapin-Ben-Zion combines these three ingredients into a single number that measures the "distance" between any two earthquakes — not physical distance, but a **relatedness distance**. Small number = closely related. Big number = unrelated.

The formula (Equation 1 of the paper):

```
η_ij = t_ij · (r_ij)^d_f · 10^(-b · m_i)
```

Translation of each piece:

- **`t_ij`** — time between the two quakes (in years). Bigger = less related.
- **`(r_ij)^d_f`** — spatial distance, raised to a power. Bigger = less related. The exponent `d_f` is the **fractal dimension** — basically a number (`d_f = 1.6` in the paper's main analysis) that captures how earthquakes are geometrically distributed in your region. It's a regional constant you estimate once.
- **`10^(-b · m_i)`** — this is the magnitude adjustment. The minus sign is crucial: **bigger magnitude makes this term smaller, which makes `η` smaller, which means "more related."** With the paper's default `b = 1`, a magnitude 7 quake gets a much bigger "relatedness reach" than a magnitude 4.

So `η` is essentially: *(time apart) × (space apart) ÷ (reach of the parent quake)*.

A small `η` means: "these two quakes are close in time, close in space, and the earlier one was big enough that this proximity is meaningful." A large `η` means: "these two quakes are far apart relative to what the earlier one could plausibly influence."

---

## The Nearest-Neighbor Step

Now here's the algorithmic move. For every earthquake in your catalog, you compute `η` to **every earlier earthquake**, and you keep only the smallest one. That smallest-`η` earlier earthquake is its **nearest neighbor** — also called its **parent**.

Every earthquake (except the very first) gets exactly one parent. This builds one big graph connecting your entire catalog — what the paper calls the **spanning tree**.

But wait — at this point, *every* earthquake has a parent, even unrelated background events. We haven't separated clustered from background yet. That's the next step.

---

## The Magic: The Bimodal Distribution

Here's where it gets beautiful. When you take all those nearest-neighbor `η` values and plot their distribution (specifically `log₁₀ η`, since they span many orders of magnitude), you don't see one smooth bell curve. **You see two bumps.**

- One bump at small `η` = genuinely related event pairs (real parent-child links).
- One bump at large `η` = coincidental nearest neighbors among unrelated events.

This bimodality is the empirical fingerprint of clustering. If earthquakes were purely random (Poisson process), you'd get one bump. The fact that you see two means clustering is real, and the valley between the bumps tells you exactly where to draw the line.

You pick a threshold `η₀` in that valley. The paper classifies each parent link by comparing it to `η₀`:

- **Strong link**: `η_j < η₀` — a real cluster connection (kept).
- **Weak link**: `η_j ≥ η₀` — coincidental (cut).

For southern California with a magnitude cutoff of 2, the paper finds `η₀ ≈ 10⁻⁵`, confirmed both by visual inspection of the `log₁₀ η` histogram and by formally fitting a 2-component Gaussian Mixture Model. For other regions, you have to look at your own histogram — the bimodality is a general feature, but where the valley sits depends on the catalog.

---

## What You're Left With: A Forest

After cutting the weak links, your giant spanning tree breaks into many smaller trees. The paper calls this the **spanning forest**. Each tree in the forest is a **cluster**, and there are exactly two kinds:

- **Family** — a tree containing two or more events, all connected by strong links.
- **Single** — a tree containing exactly one event. The paper characterizes singles as "mainshocks with no offspring": their own parent link was weak (so they weren't pulled into a family above them), and no later event formed a strong link down to them.

Within each family, events get classified by their role:

- **Mainshock** = the event with the **largest magnitude** in the family. If multiple events share the largest magnitude, the **first one in time** is the mainshock — so each family has exactly one.
- **Foreshocks** = events in the family that occurred *before* the mainshock.
- **Aftershocks** = events in the family that occurred *after* the mainshock.

For the four-class labeling task (mainshock / foreshock / aftershock / background-standalone), **singles fill the "background-standalone" class.**

---

## Why This Works So Well

Step back and notice what just happened. We didn't have to assume:

- A specific time window (like "aftershocks last 1 year")
- A specific space window (like "aftershocks occur within 50 km")
- A specific triggering model (like ETAS)

The algorithm *discovered* the clustering structure from the data itself by finding that valley in the `log₁₀ η` distribution. The only assumptions were the three intuitive ingredients (time, space, magnitude) combined in a physically reasonable way.

The 2013a paper goes further and stress-tests the algorithm in two ways: against synthetic ETAS catalogs (where the ground truth is known, so you can measure how well the method recovers the right clusters), and against perturbations of the observed southern California catalog. The paper concludes that "variations of the parameters within wide limits, largely exceeding their statistical variability, do not seriously affect the cluster identification" (paragraph [54]). That stability is a major part of why the algorithm is trusted.

Compare this to Gardner-Knopoff (1974), which says "an aftershock to a magnitude 6 quake is anything within X km and Y days, where X and Y come from a 1974 lookup table." That works, but it's rigid and the table doesn't know about your specific region. Zaliapin-Ben-Zion adapts to your data.

---

## A Visual Analogy

Imagine you're at a crowded party and want to identify family groups. You could:

**Gardner-Knopoff approach:** "Anyone standing within 3 feet of each other for more than 5 minutes is family." Works okay, but misses families that drift apart and lumps together strangers who happen to chat.

**Zaliapin-Ben-Zion approach:** "For each person, find their closest companion accounting for how far they've moved, how long they've been near each other, and how 'magnetic' (charismatic = big magnitude) the older person is. Then look at the distribution of all these closeness scores — you'll see a clear gap between 'real family' closeness and 'random stranger' closeness. Draw the line in the gap."

The second approach finds families of any size, accounting for the fact that charismatic people draw bigger crowds.

---

## The Bottom Line

Zaliapin-Ben-Zion (2013a) is essentially three ideas stacked:

1. **Define a smart "relatedness distance"** combining time, space, and parent magnitude.
2. **Link every event to its single most-related predecessor** (build a spanning tree).
3. **Trust the data to reveal** — through the bimodal distribution of `log₁₀ η` — which links are real and which are coincidental (cut the weak ones to get a spanning forest of clusters).

The output is a complete labeling of your catalog: every event is either a **single** (background/standalone), or a member of a **family** playing the role of **mainshock**, **foreshock**, or **aftershock**.

---

## Note on Terminology: "Cluster Identification" vs. "Declustering"

You may sometimes see nearest-neighbor methods described as "declustering" algorithms. The 2013a paper itself is careful to draw a distinction (paragraph [13]):

> "The problem considered in this study is **different** from catalog declustering, which is formulated as removing some events from a catalog in order to obtain a homogeneous remaining point field. We focus, instead, on identifying individual statistically significant clusters and analyzing (1) the properties of the clusters and (2) the properties of the point field represented by the single maximal event of each cluster, whether or not this field is Poissonian."

In short: declustering throws away the clusters and keeps the background; cluster identification (this paper) keeps everything and labels each event by its role. For our task — labeling each event as mainshock, foreshock, aftershock, or background/standalone — **cluster identification (2013a) is the algorithm that directly answers the question.** Pure declustering would be the wrong tool because it discards the very mainshock-aftershock structure we want to identify.

A follow-up paper by the same authors (Zaliapin & Ben-Zion, 2020) builds a separate declustering algorithm using the same nearest-neighbor distance idea but with different parameters (it sets the magnitude weight `w = 0` instead of `w = b`) and adds Monte Carlo reshuffling and probabilistic thinning. That is a different algorithm for a different purpose, and it is not what we're using here.

---

## Reference

Zaliapin, I., & Ben-Zion, Y. (2013). Earthquake clusters in southern California I: Identification and stability. *Journal of Geophysical Research: Solid Earth*, 118(6), 2847–2864. https://doi.org/10.1002/jgrb.50179
