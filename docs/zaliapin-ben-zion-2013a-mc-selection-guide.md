# Choosing `m_c` for the Zaliapin & Ben-Zion (2013a) Algorithm

A practical guideline for selecting the magnitude completeness cutoff `m_c` when applying the cluster identification method of Zaliapin & Ben-Zion (2013a) to a real earthquake catalog. This is a companion to the conceptual guide and the end-to-end algorithm document; all three are based strictly on the same 2013a paper.

**Audience:** Research team members (students) and AI coding agents who need to apply the algorithm to a new catalog (e.g., PHIVOLCS) without blindly copying the paper's southern California parameter values.

---

## What `m_c` Is For

`m_c` is the magnitude completeness cutoff. Events below `m_c` are removed from the catalog before the algorithm runs. The point is to avoid feeding the algorithm events that the recording network probably missed — small earthquakes that occurred but never made it into the catalog because not enough seismometers picked them up.

The 2013a paper treats `m_c` as one of three required pre-processing inputs (alongside the b-value `b` and the fractal dimension `d_f`). It is not estimated by the cluster identification step itself; it must be chosen first, by the analyst, from the catalog's magnitude statistics.

---

## What the Paper Actually Says About `m_c`

The 2013a paper is intentionally brief on this topic. It makes four direct claims:

**1. The paper picked `m_c = 2` for southern California, below the formal completeness magnitude.** From paragraph [10]:

> "The employed magnitude threshold `m_c = 2` is lower than the completeness magnitude for southern California, which is estimated to be above 3.0."

The paper deliberately accepted some incompleteness, on the basis that the cluster identification method tolerates it.

**2. Cluster structure is insensitive to the choice.** Also paragraph [10]:

> "The cluster structure of the events is insensitive to the catalog incompleteness as well as to the minimal reported magnitude."

This is the central claim. Within a reasonable range, different `m_c` values produce qualitatively the same clustering result.

**3. The paper tested a higher `m_c` and got similar results.** Continuing paragraph [10]:

> "The results for `m_c = 3` (not shown) are qualitatively similar to the ones reported in this study, yet the number and size of the clusters is insufficient for presenting visually clear results."

A higher `m_c` works; you simply have fewer events to analyze.

**4. The histogram of `log₁₀ η` provides a built-in validation.** Paragraph [22]:

> "The location of the upper mode, as well as the vertical location of the lower mode, is independent of the magnitude cutoff."

After running the algorithm, the bimodal `log₁₀ η` histogram should look the same at different `m_c` values. If it doesn't, the `m_c` choice is suspect.

The paper does not prescribe a specific algorithm for picking `m_c` (e.g., it does not endorse the maximum-curvature method or any other formal estimator). It cites Felzer (2008) and Schorlemmer & Woessner (2008) as references on completeness estimation and otherwise leaves the choice to the analyst.

---

## The Rules, Distilled from the Paper

Three rules emerge directly from the paragraphs above:

1. **Pick `m_c` near or somewhat below the formal completeness magnitude of the catalog.** The paper's example used `m_c = 2` even though formal completeness for southern California was above 3.0. Going slightly below the formal completeness is acceptable because the algorithm tolerates incompleteness.

2. **Do not over-tune the choice.** The paper explicitly states the result is "insensitive" to `m_c` within reasonable limits. A small change in `m_c` should not change the conclusion.

3. **Validate after running, not before.** The bimodal `log₁₀ η` histogram is the actual validation: re-run the algorithm at a higher `m_c` (e.g., `m_c + 0.5` or `m_c + 1.0`) and confirm the histogram's two modes land in the same place. The paper used `m_c = 2` and `m_c = 3` for exactly this comparison.

These three rules are everything 2013a says about the choice. Anything more specific (maximum curvature, b-value stability, CV-of-yearly-counts, etc.) comes from the broader seismology literature, not from 2013a itself, and should be treated as a practical aid that does not override the paper's rules.

---

## Practical Aids the Paper Does Not Mandate

These are commonly used in seismology to *propose* a candidate `m_c`. The paper does not require any of them, but they are useful for narrowing down a sensible value before running the algorithm.

### Aid 1 — Maximum curvature (MAXC)

Plot the non-cumulative histogram of event counts by magnitude bin. The bin with the highest count is the candidate `m_c`. Below this bin, counts drop sharply because the catalog stops detecting events reliably. The Woessner & Wiemer (2005) refinement adds 0.2 to the MAXC value as a correction for known underestimation.

This is referenced indirectly in 2013a via the citations to Felzer (2008) and Schorlemmer & Woessner (2008) but not specified as the method to use.

### Aid 2 — Cumulative count plot

Plot `log₁₀(count of events ≥ m)` against `m`. A complete portion of the catalog should follow Gutenberg-Richter and appear as a straight line. Where the line bends or flattens at low magnitudes is where the catalog becomes incomplete.

### Aid 3 — Yearly-count stability

For each candidate `m_c`, compute event counts per year and the coefficient of variation (CV = standard deviation / mean) of those yearly counts. A more stable `m_c` will have a lower CV. This aid is not in 2013a; it is a practical safeguard against catalogs whose recording network has changed substantially over time.

This aid matters more for some catalogs than others. The southern California network used in 2013a was relatively stable across the 1981–2011 period analyzed. A network that has expanded substantially during the catalog window will show high CV at low `m_c` even after MAXC says "complete," because the *measured* completeness magnitude has changed over the years even if no single year is incomplete relative to its own network.

---

## Worked Example: PHIVOLCS 2018–2026

For the PHIVOLCS catalog used by our team, the three aids above produced the following:

**MAXC.** The magnitude bin histogram peaks at the 2.0–2.1 bin (8,880 events). MAXC suggests `m_c = 2.0`; with the Woessner-Wiemer correction, `m_c = 2.2`.

**Cumulative count plot.** Linear (Gutenberg-Richter behavior) from approximately `m = 2.0` to `m = 5.5`. Below 2.0, the line flattens, confirming incompleteness in that range.

**Yearly-count stability.** The CV of yearly counts (excluding the partial-year 2026) is:

| `m_c` | Total events | CV (2018–2025) | Growth ratio 2025/2018 |
|---|---|---|---|
| 1.5 | 119,726 | 0.282 | 3.32× |
| 2.0 | 96,315 | 0.218 | 2.57× |
| 2.2 | — | 0.208 | 2.43× |
| 2.4 | — | 0.195 | 2.25× |
| **2.5** | **55,342** | **0.192** | **2.18×** |
| 2.6 | — | 0.191 | 2.15× |
| 2.8 | — | 0.195 | 2.13× |
| 3.0 | 27,169 | 0.204 | 2.20× |
| 3.5 | 11,799 | 0.225 | 2.31× |
| 4.0 | 4,836 | 0.264 | 2.53× |

The CV reaches its minimum at `m_c = 2.5–2.6`. Below that, the network-evolution trend dominates; above that, small-N sampling noise dominates.

**Decision.** `m_c = 2.5` was chosen because it satisfies all three of the paper's rules:

- It is at or above the formal incompleteness cutoff suggested by MAXC and the cumulative-count plot. Rule 1 satisfied.
- It is the most temporally stable value. Choosing 2.0 instead would change the yearly CV from 0.192 to 0.218 — a small change that, per Rule 2, should not meaningfully change the clustering result. The choice is robust.
- The paper's validation gate (Rule 3) will be applied by re-running the algorithm at `m_c = 3.0`. If the `log₁₀ η` bimodal histogram lands its two modes in the same locations at both `m_c = 2.5` and `m_c = 3.0`, the choice is confirmed. If not, raise `m_c` and try again.

**Catalog size at `m_c = 2.5`:** 55,342 events. For comparison, the 2013a paper used 111,981 events at `m_c = 2` and noted that 12,105 events at `m_c = 3` was sufficient for the analysis to work but produced visually less clear figures. PHIVOLCS at `m_c = 2.5` is well within the workable range.

---

## Caveats and Things to Document

**Network evolution is real and visible in PHIVOLCS data.** Even at the most stable cutoff (`m_c = 2.5`), event counts roughly double from 2018 to 2025. The 2013a algorithm's stability claim (paragraph [10]) covers this kind of inhomogeneity, so the clustering result is still trustworthy. But interpretation of *cluster counts over time* must account for it: a finding of "more clustering in recent years" could reflect more events being detected, not more clustering occurring.

**The 2026 partial year inflates CV uniformly.** It was excluded from the table above for the `m_c` decision. It should still be included in the catalog passed to the clustering algorithm — more data is always better for nearest-neighbor analysis.

**If you eventually estimate a PHIVOLCS-specific `b`-value** (rather than using the 2013a default `b = 1`), do it on the magnitude range and time window where the catalog is most stable — for our data that is approximately 2021–2025 with `m ≥ 3.0`. This is a separate decision from `m_c` and does not affect the `m_c` choice.

---

## Quick Decision Checklist

- [ ] Magnitude bin histogram produced; MAXC peak identified.
- [ ] Cumulative count plot produced; Gutenberg-Richter linearity checked.
- [ ] Yearly-count CV table produced for candidate `m_c` values, partial years excluded.
- [ ] Candidate `m_c` chosen at or above MAXC, near the CV minimum.
- [ ] Catalog size at chosen `m_c` is large enough for nearest-neighbor analysis (the 2013a paper's `m_c = 3` analysis at ~12,000 events worked).
- [ ] Plan to validate via Rule 3: re-run at a higher `m_c` (typically `+0.5` or `+1.0`) and compare `log₁₀ η` histogram modes.

---

## Reference

Zaliapin, I., & Ben-Zion, Y. (2013). Earthquake clusters in southern California I: Identification and stability. *Journal of Geophysical Research: Solid Earth*, 118(6), 2847–2864. https://doi.org/10.1002/jgrb.50179

Supporting references (cited by 2013a, not authored by it):

- Felzer, K. R. (2008). Calculating California seismicity rates. USGS Open-File Report 2007-1437I.
- Schorlemmer, D., & Woessner, J. (2008). Probability of detecting an earthquake. *Bulletin of the Seismological Society of America*, 98(5), 2103–2117.
- Woessner, J., & Wiemer, S. (2005). Assessing the quality of earthquake catalogues: Estimating the magnitude of completeness and its uncertainty. *Bulletin of the Seismological Society of America*, 95(2), 684–698.
