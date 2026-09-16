# Keep ingestion as an idempotent vertical slice

**Status**: accepted

The first implementation slice will cover PHIVOLCS retrieval, validation and
reconciliation, earthquake persistence, ingestion-run processing, and
publishing eligible prediction work. Prediction execution and alert delivery
remain separate workers. The previous backend is reference material only; the
proposed architecture and schema documents are the target. Ingestion uses
at-least-once delivery, so retries and later polls must safely repeat source
reconciliation instead of promising that every missed polling interval is
replayed exactly once.
