# Phase 6 implementation handoff

## Review target

- Worktree: `C:\Projects\quakestrikeph\redo\quakestrikeph-phase6`
- Branch: `codex/phase-6-feature-snapshots`
- Implementation commit: `aab54eef4d7fe14fa50ffb73d5d097e4c48ea18a`
- Base commit: `5505c137`

Phase 5 is not integrated into this branch. The Phase 5 work remains on
`codex/phase-5-reconciliation` at commit `65088fb`. The original checkout and
the Phase 6 worktree were both clean when this report was written.

## What was implemented

Phase 6 adds the feature-snapshot and prediction-dispatch slice described by
the implementation plan and ADRs 0009, 0016, 0021, and 0022.

### Feature contract

`workers/src/quakestrike/domain/features.py` now owns the pure feature rules:

- The snapshot contains exactly these ten fields:
  `anchor_magnitude`, `anchor_depth_km`, `anchor_latitude`,
  `anchor_longitude`, `anchor_time_is_minute_precision`,
  `catalog_m1_plus_count_past_1h`, `catalog_m1_plus_count_past_24h`,
  `catalog_m1_plus_count_past_7d`,
  `local_m1_plus_count_past_24h_within_50km`, and
  `local_m1_plus_count_past_24h_within_100km`.
- Only prior M1+ events contribute to history features.
- The seven-day history window is lower-inclusive and anchor-exclusive.
- The anchor event, future events, equal timestamps, and uncertain events in
  the same minute are excluded.
- Local counts use the Haversine formula with Earth radius `6371.0088` km.
  The 50 km and 100 km boundaries are inclusive.
- Feature values are normalized and validated before persistence. Missing,
  unknown, non-finite, negative, and malformed values are rejected.

`HistoryCoverage` is explicit input to the readiness decision. The query does
not treat the oldest stored event as proof that the complete seven-day source
history is available. Missing or incomplete coverage produces a skip decision.

The canonical snapshot is compact, sorted JSON encoded as UTF-8. Its SHA-256
hash covers both the normalized feature values and the input schema version
`quakestrike.prediction-input.v1`. The stored JSON object contains only the ten
feature fields.

### Transaction and idempotency behavior

`SqlAlchemyIngestionTransactions.process_event_with_features` performs the
revision, feature decision, snapshot validation, prediction job, and dispatch
record work in one database transaction.

- Below-M1 events persist the valid event revision with
  `magnitude_below_m1` and create no prediction job or dispatch.
- Missing or incomplete seven-day history persists an explicit skip reason and
  creates no prediction job or dispatch.
- An eligible revision uses the configured verified model release and stores
  the canonical snapshot and hash before prediction work is inserted.
- The unique revision, release, and snapshot-hash key makes a logical replay
  return the existing prediction work instead of creating duplicates.
- A later source revision gets its own prediction work even when its feature
  values match an earlier revision.
- The new nullable `prediction_skip_reason` column and its allowed-value check
  are added by migration `20260917_03`.

The migration currently descends from `20260916_01`, matching the isolated
Phase 6 base. If Phase 5 is later accepted, the migration graph and the
overlapping persistence, repository, table, and transaction tests need a
deliberate reconciliation with Phase 5 migration `20260917_02`.

### Post-commit prediction dispatch

`workers/src/quakestrike/application/prediction_dispatch.py` separates durable
database work from queue publication. The publisher runs only after the
transaction returns successfully and sends the IDs-only
`prediction-command.v1` message to the `prediction` queue. A queue failure
does not roll back the durable prediction job or dispatch record.

This slice does not execute the Python model or add the prediction task
consumer. It establishes the committed work record and the queue command
boundary for that later worker behavior.

## Main files for review

- `workers/src/quakestrike/domain/features.py`: feature rules, readiness, and
  canonical snapshot hashing.
- `workers/src/quakestrike/application/features.py`: feature-history query and
  snapshot decision seams.
- `workers/src/quakestrike/infrastructure/database/feature_history.py`:
  latest-revision history query and observation mapping.
- `workers/src/quakestrike/infrastructure/database/repositories.py`: atomic
  persistence, release validation, and prediction-work idempotency.
- `workers/src/quakestrike/application/prediction_dispatch.py`: post-commit
  publication boundary.
- `workers/src/quakestrike/infrastructure/queues/prediction_publisher.py`:
  Celery adapter for the IDs-only command.
- `workers/migrations/versions/20260917_03_feature_snapshot_contract.py`:
  skip-reason column, constraint, and event-time index.
- `workers/tests/unit/test_features.py` and
  `workers/tests/integration/test_feature_snapshots.py`: focused contract and
  database behavior tests.

## Verification

The following checks passed on the Phase 6 branch:

```text
uv run --project workers ruff check workers
All checks passed.

uv run --project workers ruff format --check workers
79 files already formatted.

git diff --check
Passed.

uv run --project workers pytest --config-file workers/pyproject.toml workers/tests/unit/test_features.py workers/tests/unit/test_feature_application.py workers/tests/unit/test_prediction_dispatch.py
13 passed.

docker compose -f infrastructure/compose.integration.yml -p quakestrike-phase6-tests run --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration/test_feature_snapshots.py
5 passed.

Full containerized regression suite before the final focused edge-case additions:
210 passed, 1 skipped. The skipped test requires Docker CLI access inside the test container.

uv run alembic -c workers/alembic.ini upgrade head --sql
Passed. The isolated migration chain reaches 20260917_03.
```

## Suggested review order

1. Read `domain/features.py` and its unit tests to verify the feature windows,
   precision rule, coverage gate, normalization, and hash envelope.
2. Read the repository transaction path and the integration tests together.
   Check that skip decisions and eligible prediction work share the intended
   transaction boundary.
3. Read `prediction_dispatch.py` and its tests to verify that publication is
   post-commit and carries IDs only.
4. Review the migration and ERD update, keeping the isolated Phase 6 migration
   parent in mind.

## Review questions

- Is explicit `HistoryCoverage` the right interface for proving seven-day
  source completeness before feature construction?
- Is storing skip evidence on `earthquake_event_revisions` sufficient, or
  should the project use a separate prediction-decision record?
- Does the repository transaction expose the right seam for the later Phase 5
  reconciliation workflow?
- Is the post-commit publisher contract ready for the prediction worker
  consumer planned in a later phase?
