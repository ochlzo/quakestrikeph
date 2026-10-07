# Browser clustering for forecast playback

Recorded: 8 October 2026, Asia/Manila.
Status: sample-catalog experiment completed; production data scope remains unresolved.

## Result

The TypeScript implementation matches the corrected C++ implementation on six synthetic cases.
The Chromium module Web Worker also matches the reference on those cases.
The comparison checks parent choices, strict link classification, group membership, group sizes, distances, scores, and playback membership.
Reversing the input preserves the results after chronological sorting.

Removing earlier history can change the playback count.
The explicit counterexample changes from three qualifying events to zero after removing the earlier connecting earthquake.
Therefore, a download containing only the selected earthquake and its succeeding observations cannot reproduce the accepted groups in general.

These results establish sample parity, not physical earthquake relationships, model accuracy, full-catalog parity, or phone performance.

## Run the experiment

From `apps/quakestrikeph-bulletin`, run:

```powershell
pnpm prototype:forecast-clustering
```

Open <http://127.0.0.1:4340/> and choose a sample case.
The development harness lists each earthquake's selected parent, link status, sample group, and playback inclusion.
The harness is a separate Vite entry; the Bulletin's public routes do not import it.
No live API, database, model inference, source scraping, or provider calls are involved.

Run the native comparison from the same directory:

```powershell
pnpm check:forecast-clustering
```

Requirements: Node 22.19 or later with type stripping, a C++17 `g++` compiler, and the neighboring corrected clustering checkout.
The comparator builds a small reference executable in a fresh OS temporary directory.
It links the original `diagnose.cpp` and `cluster.cpp`; the bridge contains no copied scoring implementation.
The corrected checkout remains a read-only input.

For another source location or compiler, use `--reference-project` or `--compiler` with an explicit path.
The reference input uses epoch seconds directly, so this comparison does not test the original CSV timestamp parser.

With the harness running and Playwright available, also run:

```powershell
pnpm check:forecast-clustering --browser-url http://127.0.0.1:4340/
```

If Playwright is supplied by an external runtime, pass its absolute module directory with `--playwright-module`.
No new Playwright dependency was added to the Bulletin.
The browser check exercises a real module worker, error replies, and harness controls at desktop and mobile-sized viewports.
A mobile-sized Chromium viewport is not a physical phone test.

The comparator prints its temporary evidence directory.
It preserves native CSV assignments and `report.json` there.
Use `--evidence ../../docs/research/forecast-clustering-evidence.json` to refresh the portable report deliberately.

## Files and interface

- [Clustering module](../../apps/quakestrikeph-bulletin/src/features/forecast-prototype/clustering.ts): pure scoring, grouping, and playback selection.
- [Worker](../../apps/quakestrikeph-bulletin/src/features/forecast-prototype/clustering.worker.ts): requests, replies, and computation timing.
- [Harness](../../apps/quakestrikeph-bulletin/src/features/forecast-prototype/index.html): standalone development entry.
- [Harness controls](../../apps/quakestrikeph-bulletin/src/features/forecast-prototype/experiment.ts): worker lifetime and sample results.
- [Synthetic catalog](../../apps/quakestrikeph-bulletin/src/features/forecast-prototype/fixtures/sample-catalog.json): fixed examples and a seeded 128-event case.
- [Comparator](../../apps/quakestrikeph-bulletin/scripts/forecast-clustering/compare-reference.mjs): native, Node, and optional browser comparisons.
- [Native bridge](../../apps/quakestrikeph-bulletin/scripts/forecast-clustering/reference.cpp): calls the existing C++ functions.
- [Recorded evidence](forecast-clustering-evidence.json): input and source hashes, engine versions, counts, and sample timings.

`clusterCatalog(events, settings)` validates, sorts, filters, and assigns the supplied observations.
The search considers every eligible earlier event; it has no arbitrary distance or lookback pruning.
Parent search has quadratic growth. Group construction follows each retained parent's root.
One strictly earlier parent forms a forest, so root inheritance reproduces the connected components for a fresh batch.

`windowEvents(result, anchorId, elapsedHours)` selects later M1+ members of the anchor's group through the supplied playback hour.
The playback hour ranges from zero to 24; the upper endpoint is inclusive.
The selector applies the timestamp-precision rule when establishing whether an observation follows the anchor.
It applies neither a forecast-radius filter nor a retrospective aftershock-role filter.

Inputs use UTC epoch seconds and explicit minute/second precision.
IDs must be unique ASCII identifiers, including ordinary event UUIDs.
ASCII comparison preserves the reference implementation's tie order without locale-dependent sorting.
Duplicate identities are rejected; callers must reconcile revisions before constructing a catalog snapshot.
Group numbers and roots describe one calculation, not durable public group identities.

## Contract and provenance

The sample settings come from the [recorded primary experiment](../../../quakestrikeph-zaliapin-clustering-corrected/docs/phivolcs-phase-1/decisions.md#current-decision).
Read that decision and the [algorithm policies](../../../quakestrikeph-zaliapin-clustering-corrected/docs/algorithm.md) for exact parameters and their scientific limitations.
The raw-distance fixture and generated comparison use the recorded raw variant.
The threshold-equality fixture deliberately overrides eta0 to test the strict boundary; it is not a newly calibrated policy.

The runtime manifest identifies `SEIS 1.0.1` and the source package `balanced-selection-anchor-exploratory-01`.
The referenced package and current training contracts were unavailable in the expected neighboring training checkout during this experiment.
The training README points to reorganized paths, including `docs/current/dataset-contract.md`, which were also absent.
The exact deployed-release-to-clustering lineage is therefore unverified.
The sample defaults must not be presented as a verified production relationship policy.

Use [ADR 0009 and its amendments](../adr/0009-immutable-model-releases-and-ingestion-feature-snapshots.md) for runtime release authority.
The manifest's historical provisional fields do not supersede the later operational approval in that ADR.
Use [ADR 0026](../adr/0026-forecast-output-contract.md) for corrected median-radius and magnitude-quantile identities.
The older [target agreement](../../../quakestrikeph-zaliapin-clustering-corrected/docs/phivolcs-phase-1/training/agreed_forecast_outputs.md) supplies membership context but contains superseded output examples.

## Verification and observations

| Case | Property checked | Included events | Window events |
| --- | --- | ---: | ---: |
| Branches and boundaries | Shared earlier parent, later larger event, M1 cutoff, inclusive end, separate nearby group | 7 | 3 |
| Mixed precision and ties | Same-minute exclusions, equal times, deterministic score ties | 6 | 2 |
| Raw zero distance | Negative-infinite log score and first-candidate tie handling | 3 | 2 |
| Threshold equality | Equality produces a weak link | 2 | 0 |
| Empty window | No qualifying recorded group members | 2 | 0 |
| Seeded catalog | All assignments in a geographically varied synthetic sample | 128 | 10 |

Additional native comparisons passed for the generated raw variant, a late arrival, and a corrected observation.
Fresh batch recomputation handles the late arrival and correction; no incremental production updater was implemented.
An append check confirms that adding strictly later observations preserves earlier parent choices, retained links, and roots in this sample.

The maximum observed difference between JavaScript and native log scores was approximately `1.78e-15`.
Discrete parent and group decisions matched exactly on the tested inputs.
Near-tied candidates and near-threshold real observations still require investigation on a larger reference catalog.

The recorded desktop Chromium worker computation for the 128-event sample was approximately 8.4 ms in one run.
This excludes download, worker startup, message copying, and rendering; it is not a statistically repeated benchmark.
The complete fixture file is 43,619 bytes before compression and contains multiple overlapping synthetic scenarios.
Neither measurement estimates the cost of downloading or processing the full historical catalog.

Checks completed:

- Native/Node sample comparisons and the stated edge checks passed.
- Chromium worker comparisons, duplicate-error reply, and desktop/mobile-sized harness controls passed.
- Bulletin `pnpm check` passed with zero errors and existing unrelated hints.
- Bulletin `pnpm build` passed with a large-chunk warning.
- The production output contains no harness or sample-catalog entry.

PostgreSQL, Redis, ingestion, and dispatch behavior were not changed, so the integration suite was outside this experiment's scope.

## Remaining decisions

1. Recover the exact training lineage for the deployed SEIS release.
2. Compare browser results with C++ on an identified real catalog and near-boundary examples.
3. Establish acceptable download, memory, and latency limits for representative phones.
4. Compare full-catalog download, precomputed historical links, and precomputed membership delivery.
5. Measure cold load, updates, source corrections, and responsiveness on physical devices.
6. Choose browser JavaScript, WebAssembly, or server-prepared assignments from that evidence.

The forecast map and timeline UI remain a later phase.
The public page should distinguish estimated 24-hour summaries from recorded observations and use the wording **possibly related earthquakes**.
Future hours and missing data require separate states from observed hours with no qualifying records.
These relationship results do not establish confirmed aftershocks, exact future earthquakes, or community safety boundaries.

## Documentation references

- [Vite module workers](https://vite.dev/guide/features.html#web-workers): constructor-based module worker loading, consulted through Context7.
- [MDN Web Workers](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Using_web_workers): separate browser execution context.
- [Zaliapin and Ben-Zion, 2013](https://zaliapin.github.io/pubs/ZBZ_JGR13a.pdf): nearest-parent network and statistical grouping.
- [USGS forecast terminology](https://www.usgs.gov/faqs/can-you-predict-earthquakes): forecasts and exact predictions.
