# Match forecast persistence to the SEIS 1.0 output contract

**Status**: accepted

The Prediction Worker persists the output names supplied by the registered
`SEIS 1.0` release. Forecasts use `maximum_magnitude_q05_24h`,
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
