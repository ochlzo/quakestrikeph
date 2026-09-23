# Match forecast persistence to the corrected SEIS output contract

**Status**: accepted

The Prediction Worker persists the output names supplied by the registered
`SEIS 1.0.1` release. Forecasts use `maximum_magnitude_q05_24h`,
`maximum_magnitude_q50_24h`, `maximum_magnitude_q95_24h`, and
`activity_radius_median_km_24h`. The previous q10/q90 and p90 names are not
aliases and are not retained as parallel columns.

The database stores model outputs as finite double-precision values. It checks
probability bounds and monotonic conditional composition, non-negative counts
and radius, and quantile ordering. A forecast window starts at the linked
revision event time and ends exactly 24 elapsed hours later. Prediction
attempts, forecasts, automatic alert jobs, their durable dispatch, and the
required system audit are separate durable records. Completion code must write
them in one transaction; this migration only establishes their storage and
constraints.

The target correction is an immutable patch release, not an edit to the
registered `SEIS 1.0` identity. `SEIS 1.0.1` uses a new release ID and output
schema v2 while retaining the verified model artifacts.
