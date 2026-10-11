# Simplify forecast-alert copy and use provider SMS branding

**Status**: accepted by the user on 11 October 2026.

This amends the rendering contract in [ADR 0047](0047-forecast-alert-content-and-delivery-evidence.md) for newly created snapshots. Remove the entire `Original 24-hour forecast window:` line from general and nearby SMS/email. Keep the original 24-hour window for expiry and preserve every stored forecast output.

Email displays the median activity radius under `Possible further activity radius:` and only q50 under `Possible maximum magnitude:`. Missing optional values remain `Unavailable`. The radius and maximum-magnitude fields remain email-only, with the existing limitations and full event-ID forecast link.

Remove the `QuakeStrike PH` header from both SMS variants because the provider template adds branding. Retain email branding. Record `forecast-alert-v2` rendering provenance for new content. Preserve frozen older snapshots without a migration, backfill, or grant change. Controlled provider-send verification remains a separate rollout check.
