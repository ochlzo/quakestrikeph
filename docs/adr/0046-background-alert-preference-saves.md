# Save alert preferences in the background and commit onboarding per form

**Status**: accepted by the user on 6 October 2026.

Replaces ADR 0045 and the final-save workflow in ADRs 0038, 0042 and 0044.
Remove the Alerts page's Save preferences button. Email, SMS and nearby-only
switches optimistically update and save after a 400 ms debounce. The magnitude
field has colored Lucide Check and X icons, with accessible names and no visible
labels. Check or Enter saves a valid magnitude; X or Escape discards the edit.
Use this location saves location and distance. Unsubmitted location edits retain
the existing leave confirmation.

During onboarding, Continue commits email choices and any already verified SMS
choice through the existing preferences endpoint. An unverified SMS selection
is an in-memory explicit opt-in intent, not an enabled database flag. Complete
phone verification first, then save that selected SMS opt-in in a separate
audited preferences transaction. Skipping SMS leaves it off. The preferences
transaction marks onboarding complete; no final omnibus Save is required.

Background saves use an in-memory, session-scoped queue. Writes are serialized,
and later changes supersede earlier changes without stale response rollback.
On failure, restore the last confirmed values for the failed revision and show
an error toast. Unmounting a screen does not cancel submitted saves. Changing
identity cancels queued work and suppresses results from the former identity.
No account data, credentials, drafts or requests enter browser storage.

Astro ClientRouter handles navigation between account pages and the Bulletin.
A persisted global toast island stays mounted across those navigations, so
background failures remain visible after leaving the Alerts page. Reloading,
closing the tab, and leaving the site end the in-memory runtime; no durable
offline queue or service worker is introduced.

Error toasts remain visible until dismissed. Astro 7.3.5 references a missing
JavaScript module containing only transition type declarations. An empty local
shim and dependency-optimizer exclusion allow ClientRouter to run without a
dependency upgrade. Remove that workaround when the installed package fixes it.

The existing Backend remains responsible for ownership, destination verification,
SMS sender support, validation and atomic preference/audit writes. No new
endpoint, database schema, delivery worker or deployment is required.
