---
name: contract-first-implementation
description: Use when implementing or reviewing code that changes persisted state, event or revision semantics, concurrency, retries, migrations, external side effects, or runtime wiring. Derive the contract, turn edge cases into tests, and prove the real integration path before calling the work complete.
metadata:
  short-description: Implement and review stateful code by contract
---

# Contract-first implementation

Use this skill when a change crosses a state, persistence, concurrency, retry, migration, external I/O, or production-wiring boundary. The recurring failure mode is locally plausible code that violates an invariant owned by another layer.

For a small pure-function edit with no state or I/O boundary, use the normal coding workflow.

## Establish authority

Read the repository instructions, task or issue, ADRs, relevant code, tests, configuration, and the project's canonical test commands. Follow the repository's documented authority order when sources disagree.

Keep a decision ledger in your working notes:

- decision
- source or authority
- consequence for the implementation

Search the ledger and repository decisions before asking a question. Reuse decisions that already exist. Ask only when two plausible choices would change behavior, safety, or scope, and record the answer once.

Completion means every acceptance criterion has a source, an explicit decision, or a clearly marked gap.

## Bound the phase

Separate the guarantees required now from later hardening or integration work. Inspect every public entry point, including specialized and generic paths, background workers, bootstrap code, and test-only constructors.

For each path, answer:

- Which policy does it enforce?
- Which state transition does it own?
- Which configuration or verifier does it require?
- What happens when that dependency is missing?

Keep deferred work visible, but keep it out of the current implementation unless the task requires it. A callable future path must fail clearly or remain unwired rather than silently bypassing current policy.

Completion means the in-scope guarantees, deferred capabilities, and production wiring status are written down.

## Build the contract matrix

Before coding, make a compact matrix. Each applicable row needs an invariant, a failure result, an enforcement owner, and a proof test.

| Area | Questions to answer |
| --- | --- |
| Identity and replay | What makes two deliveries the same? What counts as a new revision, a delayed delivery, a legitimate revert, or a conflict? |
| State and terminal outcomes | Which transitions are allowed? Which outcomes are terminal? Can a retry reopen or mutate a terminal state? |
| Ownership and concurrency | Who owns the work? What token, lease, lock, or uniqueness rule protects it? What happens when the row does not exist yet? |
| Attempts and time | Which clock, anchor, timezone, precision, and inclusive or exclusive bound apply? How are expired leases and attempt limits handled? |
| Persistence and atomicity | Which writes commit together? What does a crash between commit, checkpoint, acknowledgement, and publish leave behind? |
| External effects | Can a publish, notification, or HTTP call repeat? What makes the effect idempotent, observable, and safe after a database commit? |
| Values and canonical form | How are missing, nonfinite, out-of-range, rounded, decimal, JSON, and hash values normalized? |
| Schema and migration | Does a clean database work? Does an existing database upgrade safely? Are constraints, indexes, foreign keys, downgrade behavior, and migration history correct? |
| Diagnostics and wiring | Does the error preserve its stable code and context? Is the configured release, verifier, worker, or bootstrap path actually constructed in production? |

Completion means each applicable row has a named owner and an observable assertion or a written reason why it is out of scope.

## Sweep the edge cases

Turn the matrix into tests before implementing the fix. Select the cases that apply to the change.

- Replay: first delivery, exact duplicate, delayed historical delivery, new revision, conflicting identity, and a valid revert to older content.
- Concurrency: two first inserts, duplicate mapping writes, stale ownership, expired lease, wrong token, retry after the limit, and rollback during a competing transaction.
- Atomicity: crash after the database commit but before the external effect, after the effect but before the checkpoint, and after a successful retry that repeats the effect.
- Values: missing input, malformed input, `NaN`, infinity, negative zero, values outside a bound before rounding, values that round to a bound, decimal scale, canonical JSON, and hash stability.
- Time: stale fixed dates, timezone conversion, timestamp precision, anchor inclusion or exclusion, and clock selection.
- Migrations: clean install, upgrade from the previous head, one current head, already-applied history, live-table metadata imports, missing indexes, foreign-key cleanup, and fixtures that still assume the old schema.
- Wiring: specialized and generic entry points, absent configuration, a verifier that exists only in tests, a release that is schema-compatible but not approved, and a worker or bootstrap path that is defined but never constructed.

When a reviewer identifies a missed case, convert it into three artifacts: the invariant, a minimal reproducer, and a regression test. This closes the loop instead of adding another one-off patch.

Completion means every applicable edge case is covered by a failing test, a passing regression test, or an explicit scope decision.

## Test at the real seam

Start with the smallest failing test at the public boundary that owns the behavior. Use unit tests for pure rules. Use the real database, transaction, queue, cache, HTTP, or migration boundary when the risk involves isolation, locks, serialization, leases, commit order, or external effects.

Prefer the repository's own integration runner and Compose or container setup. Inspect its scripts when a host-level command is unavailable. A skipped or stalled integration suite is evidence about verification status, not a green result.

Run in this order when the project supports it:

1. Focused red test for the missing invariant.
2. Focused green test after the change.
3. Full unit and contract suite.
4. Real integration suite through the repository's canonical runner.
5. Lint, formatting, type checks, migration checks, and whitespace checks that the project uses.
6. Diff, call-site, and migration review.

Record the exact command, result, count, and skipped or unrun work. Report a container or environment failure separately from a code failure.

Completion means every changed boundary has proof from the strongest available test, and the report distinguishes passed, skipped, stalled, and unrun checks.

## Implement the smallest complete change

Enforce each invariant once at its real owner. Keep orchestration shared rather than copying it across generic and specialized paths. Use explicit named arguments and result types when a call has several similar values. Preserve structured diagnostics and stable error codes across layers.

For concurrency, make the lock or lease scope, owner token, expiry rule, and attempt counter explicit. For transactions, define which state and checkpoint changes commit together. For external effects, define the retry and idempotency rule. For migrations, preserve existing data and support the repository's upgrade path.

Keep the patch inside the current phase. Add a seam, test, or clear failure for future wiring instead of inventing production behavior that the task does not authorize.

Completion means the implementation satisfies the matrix without a second path that can bypass it.

## Review with a fresh model

After the tests pass, reread the task and inspect the diff as if someone else wrote it. Trace callers, constructors, migrations, configuration, and the real runtime path. Ask concrete failure questions:

- What if this is the first row and two workers arrive together?
- What if the same delivery arrives again after a partial commit?
- What if the owner expires or the token is stale?
- What if the process dies between two side effects?
- What if the value is valid after rounding but invalid before it?
- What if the database already has the previous migration?
- What if the test-only verifier or configuration is absent in production?

Classify findings as P1 correctness, P2 specification or standards, or P3 follow-up. A P1 or P2 remains open until fixed or explicitly accepted by the user. If an independent reviewer is available, use one after the implementor's pass, especially for transaction, migration, and concurrency changes.

Completion means no unresolved P1 or P2 remains, and every P3 has an owner or a reason to defer it.

## Handoff with proof

Finish with a short report containing:

- what changed and which invariants it enforces
- the exact validation commands and results
- skipped, stalled, or unrun checks and why
- deferred behavior and remaining risks
- the relevant commit, branch, or worktree when the repository uses them

Use "complete" only when the contract matrix and its proof are complete. Otherwise label the work as partial and name the missing proof.
