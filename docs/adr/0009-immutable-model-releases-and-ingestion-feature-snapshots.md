# Keep model releases immutable and build feature snapshots in ingestion

**Status**: accepted for project v1

The `model_releases` registry keeps its current seven columns: release ID,
unique version label, manifest URI and hash, input and output schema versions,
and creation time. A release row is immutable. The manifest is authoritative
for exact model routes, target mappings, feature lists, artifact hashes,
provenance, and runtime metadata. Deployment configuration selects the
configured release ID; the database does not use a mutable active flag.

The selected `balanced-selection-anchor-exploratory-01` package may be
integrated as the project's provisional v1 model package because its target
definitions are final, its manifest is complete, and its local metadata and
weights verify successfully. It remains a development/provisional model claim
until its runtime release bundle is explicitly authorized; deadline pressure
does not change that distinction.

The Data Ingestor builds the versioned v1 feature contract from PostgreSQL
earthquake history and the validated event revision. It stores one canonical
immutable feature snapshot and its SHA-256 hash in each prediction job. The
Prediction Worker, when implemented, selects the exact model routes from the
release manifest and composes the final target outputs. Placeholder snapshots
and model-specific schema columns are not allowed.

For the project deadline, the selected model package may be copied into a
local `model-artifacts/` directory inside the application workspace for
development and demonstration. The directory must be ignored by Git, excluded
from Docker build contexts, mounted read-only, and checked against the release
manifest hashes. Copying the weights into the workspace does not authorize
committing them to the repository or changing the package's provisional status.

## Amendment: project production release

For this project, the selected package is the production runtime target under
the human-facing release label `SEIS 1.0`. The earlier provisional/development
approval language does not block its operational use in the first slice. The
release row and runtime bundle remain immutable; manifest and artifact hashes
must still be verified; model files remain local, Git-ignored, excluded from
build contexts, and mounted read-only. This amendment changes the operational
status for the project, not the selected targets or the artifact-integrity
requirements.
