# Seed PostgreSQL once and defer prediction execution

**Status**: accepted for the current implementation

The live earthquake source of truth is PostgreSQL. CSV files are deferred from
the intended runtime workflow and must not be dual-written as a second live
store. Raw or enriched PHIVOLCS records with bulletin identifiers and source
URLs will be used once as the input to a finite bootstrap/import operation,
after which the imported records are read from PostgreSQL. The initial window
covers the minimum August lookback before the intended September anchors and
the latest available September records. The bootstrap must seed enough valid
history for the versioned feature contract, including at least seven days
before the first prediction anchor; prediction creation is gated until that
prerequisite is satisfied.

The regular five-minute scheduler does not replay an entire month. Each poll
reconciles only the bulletins visible on the current PHIVOLCS page. Historical
September rows therefore enter the database through the bootstrap or a future
archive/backfill command. The bootstrap is recorded as a backfill run and is
not part of the recurring scheduler loop. Migrations run first, the bootstrap
completes and passes its coverage checks, and only then is the five-minute Beat
schedule enabled.

The current implementation ends with the Scheduler, Data Ingestor, feature
builder, immutable prediction snapshots, prediction-job records, and Redis
dispatch messages. Prediction messages are published even while the Prediction
Worker is not implemented, so the queue contract can be tested end to end. The
Prediction Worker itself is not implemented in this slice; its input and output
contracts are defined so it can be added later without changing the ingestor's
ownership boundary.

The selected `balanced-selection-anchor-exploratory-01` package is the
provisional project v1 model package. Its model files may be copied into a
local ignored `model-artifacts/` directory in the application workspace for
development and demonstration, mounted read-only, and verified against the
release manifest. The files must not be committed to Git or silently relabeled
as scientifically authorized production artifacts.

## Amendment: project production posture

The project treats the selected package and `SEIS 1.0` release as the
production runtime target for these implementation tasks. The earlier
provisional/approval distinction is not an implementation gate for this
project. The package must still be registered explicitly, verified against its
immutable manifest and artifact hashes, and kept out of Git. Prediction
execution and alert delivery remain deferred according to this ADR's scope.
