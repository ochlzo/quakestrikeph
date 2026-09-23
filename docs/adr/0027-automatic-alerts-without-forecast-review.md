# Remove forecast review and use automatic per-user alerts

**Status**: accepted

QuakeStrike PH has two web applications: the Bulletin and Operations Console.
The PHIVOLCS Monitoring application, forecast-review workflow, operator-created
alerts, and saved-pin matching are outside the product scope. A valid current
forecast is available to the Bulletin without approval, and every current,
unexpired live M1+ forecast creates exactly one automatic SMS alert job. Backfill,
historical, and expired forecasts create none.

The Alert Worker determines recipients from active accounts with verified
mobile numbers, `sms_enabled = true`, and an observed anchor magnitude at or
above each user's `alert_trigger_magnitude`. These two settings belong on the
one-to-one `users` row; the default trigger is M4.5 and successful phone
verification is the SMS enrollment action. The separate preferences table,
saved pins, consent timestamp, PHIVOLCS-only flag, and near-pin flag are
removed. Review, cancellation, additional delivery channels, and geographic
recipient policies require later reviewed schema changes rather than reserved
columns or states now.
