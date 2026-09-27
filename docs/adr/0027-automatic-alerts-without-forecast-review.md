# Remove forecast review and use automatic per-user alerts

**Status**: accepted

The phone-verification enrollment sentence and exclusion of geographic rules
below record the original decision. [ADR 0030](0030-optional-nearby-sms-alerts.md)
replaces them with explicit SMS opt-in and optional nearby-only alerts.
[ADR 0036](0036-google-accounts-and-independent-phone-verification.md)
records the original Google sign-in and separate alert-phone verification flow.
[ADR 0037](0037-clerk-free-bulletin-authentication.md) replaces that
Google-only sign-in rule; [ADR 0038](0038-email-and-sms-alert-preferences.md)
extends automatic delivery and user preferences to email.

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
