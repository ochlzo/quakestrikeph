# Save alert channel switches immediately after onboarding

**Status**: accepted by the user on 6 October 2026.

Onboarding channel selections preselect the corresponding switches on the final
preferences screen. SMS selection requires phone verification; continuing
without SMS clears that draft opt-in. The final Save remains the explicit
onboarding opt-in and stores both channel settings through the existing Backend
preferences endpoint. Verification alone does not enable a channel.

After onboarding, changing an email or SMS switch immediately saves that channel
through the same endpoint. This amends ADRs 0042 and 0044 for channel switches
only. Magnitude, nearby-only, and location edits still require Save preferences.
A channel save uses the other saved preferences and preserves unrelated draft
edits. The switch reflects the confirmed response; failure retains the previous
saved value and shows an error. Channel switches are disabled during a save.

The Backend remains the owner of audited `email_enabled` and `sms_enabled`
changes. Existing destination verification and SMS support checks still apply.
No schema, new endpoint, delivery worker, or deployment change is required.
