# Allow an optional nearby-only SMS alert rule

**Status**: accepted

[ADR 0038](0038-email-and-sms-alert-preferences.md) extends the shared
magnitude and nearby-only rules below to email alerts and adds an independent
email receive option.

Users may choose whether SMS alerts are enabled, their minimum observed earthquake magnitude, and whether alerts must be near one saved alert location. This amends [ADR 0027](0027-automatic-alerts-without-forecast-review.md), which previously excluded geographic recipient policies. It does not add saved pins, device tracking, or a separate preferences table.

The planned `users` table owns `sms_enabled`, `alert_trigger_magnitude`, `nearby_alerts_only`, `alert_location_latitude`, `alert_location_longitude`, and `alert_trigger_distance_km`. SMS and nearby-only both default to false. SMS becomes enabled only through explicit user opt-in; phone verification alone does not enable it, amending ADR 0027's enrollment rule. Both coordinates and a positive distance are required to enable nearby-only alerts. Users may keep a saved location and distance while the rule is off. The Backend validates setting changes and writes the required success audit in the same transaction.

For each automatic alert, the Alert Worker first applies the existing active-account, verified-number, SMS-enabled, and observed-magnitude rules. If nearby-only is enabled, it compares the saved point with the **observed earthquake epicenter** on the forecast's event revision. A distance equal to the user's limit qualifies. Calculate Haversine distance in kilometres using Earth radius `6371.0088 km`. The forecast's predicted activity radius does not determine proximity. Recheck the current settings and distance before each provider call; a recipient that is no longer eligible is skipped.

The recipient eligibility snapshot records the location and calculated distance when the nearby rule applies, so the selection is explainable. Coordinates and snapshots are private account data and must stay out of public responses and technical logs. The [database design](../system-design/ERD/DATABASE-DESIGN.md) controls exact column types and constraints.
