# Scope month-rollover recovery and exclude Bulletin from worker deployment

**Status**: accepted

Amends the single-run restriction in [ADR 0032](0032-audited-historical-live-prediction-recovery.md).
The operator may explicitly select a succeeded live ingestion run and either
`history_coverage_unavailable` or `history_ends_before_anchor` to recover.
The existing September 24 run and reason remain the command defaults. Candidate
selection is restricted to that exact run and reason; arbitrary revision IDs,
other skip reasons, and failed or backfill source runs are not recovery targets.

All existing model/bootstrap/source verification, history known at original
ingestion, latest unsuperseded revision checks, dry-run default, bounded batches,
atomic job/dispatch/audit writes, idempotent reuse, and automatic-alert suppression
remain in force. Audits preserve the selected original run and skip reason.
Recovery changes no event revision and creates no Redis payload directly.

Worker deployment uses a Git sparse checkout excluding
`apps/quakestrikeph-bulletin/` before switching to the tested main commit.
The worker and Backend source, infrastructure, contracts, and ignored production
configuration stay available. The Bulletin remains tracked in the monorepo and
its local edits remain untouched; its build/hosting is independent of worker CI.
This does not configure or publish a Vercel deployment or change public routes.
