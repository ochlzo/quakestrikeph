# Use the schema specification as the database contract

**Status**: accepted

When the proposed database design conflicts with the earlier architecture
handoff or a diagram, the schema specification in
`C:\Projects\SAM_Capstone\capstone\docs\07-erd-schema-specification.md`
controls table names, columns, constraints, transaction rules, and ownership.
The architecture documentation and diagrams must be brought into alignment
when implementation adopts a schema rule; code must not silently invent a
compromise between conflicting documents.

## Amendment: consolidated implementation contract

`docs/system-design/ERD/DATABASE-DESIGN.md` is the repository's authoritative
implementation contract. It consolidates the source schema specification and
table guide, incorporates accepted ADR amendments, and controls table names,
columns, PostgreSQL types, constraints, transactions, and ownership. The files
under `C:\Projects\SAM_Capstone\capstone` remain design provenance. When they
differ from the consolidated contract, implementation follows the repository
contract and the accepted ADRs.

## Amendment: use PostgreSQL enums for lifecycle status

Lifecycle status columns use the named PostgreSQL enum types specified in
`docs/system-design/ERD/DATABASE-DESIGN.md`. Migrations create each enum before
the first table that uses it. New values require a reviewed forward migration;
renaming or removing values requires a compatibility plan for stored rows and
running application versions. Other bounded categorical text remains governed
by named checks unless the database contract assigns another explicit type.
