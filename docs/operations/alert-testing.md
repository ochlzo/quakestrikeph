# Private alert-testing session controls

Issue [57](https://github.com/ochlzo/quakestrikeph/issues/57) implements the
shared session only. Starting creates no scenario, queue command, or provider
request. No account connection, consumer, provider credentials, public control
route, or production deployment is included.

Container packaging and release-readiness work belong to
[issue 63](https://github.com/ochlzo/quakestrikeph/issues/63).

The private UI has separate Scenario, Testers, and History pages, one shared
Astro layout, and the accepted prototype's shell and session presentation.
The shell receives page content and never switches between screens.
Later-ticket features remain
explicitly unavailable. The tool reuses the Bulletin theme and React Aria
controls from `packages/ui`; the Bulletin retains its existing import paths.

Architecture and runtime boundaries are recorded in
[ADR 0050](../adr/0050-private-alert-testing-session-runtime.md).
The [private HTTP contract](../../packages/contracts/alert-testing/README.md)
defines request headers, responses, ownership, and errors.

## Local browser acceptance with disposable Redis

Run these commands from the repository root. Do not source the production or
development `.env`. This example creates an independent, disposable Redis
container with persistence disabled. It does not start the full worker stack.
If Docker is unavailable, stop at the Docker command and report the error.

1. Install the locked private UI dependencies.

   ```powershell
   pnpm --dir apps/quakestrikeph-alert-testing install --frozen-lockfile
   ```

2. Build the private UI.

   ```powershell
   pnpm --dir apps/quakestrikeph-alert-testing build
   ```

3. Create the disposable Redis container.

   ```powershell
   docker run --rm --detach --name quakestrike-alert-testing-preview --publish 127.0.0.1:6387:6379 redis:7.4.11-bookworm redis-server --save "" --appendonly no
   ```

4. Select that disposable Redis instance.

   ```powershell
   $env:ALERT_TEST_REDIS_URL = 'redis://127.0.0.1:6387/0'
   ```

5. Start the private control server.

   ```powershell
   uv run --project workers --frozen quakestrike-alert-testing
   ```

6. Open [the loopback tool](http://127.0.0.1:4341/).

The server binds only to `127.0.0.1:4341` and serves the built app. Rebuild the
private app after UI edits. `--port` changes the loopback port;
`--static-directory` selects another build directory. The server requires an
explicit `ALERT_TEST_REDIS_URL` and never reads root `.env` itself.

## Manual acceptance steps

1. Confirm the inactive state and use keyboard navigation to reach Start Test.
2. Start Test and confirm the active state and deadline in Philippine time.
3. Open a second browser tab and confirm the same session and deadline.
4. Navigate between Scenario, Testers, and History and confirm the shared header.
5. Use End Test, confirm the dialog, and check closure and completed cleanup.
6. Start another session and confirm its new identity through the private API.
7. Stop the disposable Redis container and confirm dependency-unavailable, rather than inactive or successful cleanup.
8. Check the layout at desktop and mobile widths.

The API integration tests cover concurrent starts, repeated starts, forced
expiry, cleanup failure/retry, closure before deletion, recovery of a lost
cleanup lease, stale UUID rejection, origin checks, and unrelated-key
preservation. These cases require real disposable Redis. The browser does not
offer fake success, forced-expiry, or failure-injection controls.

After acceptance, press Ctrl+C in the server terminal. Remove the disposable
container and process-scoped setting:

```powershell
docker stop quakestrike-alert-testing-preview
Remove-Item Env:ALERT_TEST_REDIS_URL
```

## Tailscale boundary

A configured `--origin https://<machine>.<tailnet>.ts.net` accepts that exact
Host and browser Origin while preserving the loopback bind. Authorized
Tailscale Serve configuration must forward that Host to the control server.
Use Serve only; Funnel would expose controls publicly and is prohibited.
Tailnet policy admits test operators; Bulletin and Console identity do not.
No Serve, Funnel, Traefik, Cloudflare, account, or target-environment changes
are performed by the launch command. Target-environment activation remains
an explicit operator action under existing runtime gates.

## Contributor verification

Run the exact disposable integration procedure in `CONTRIBUTING.md`:

```powershell
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml up -d --wait postgres-test redis-test
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml run --build --rm test-runner pytest --config-file workers/pyproject.toml workers/tests/integration
docker compose -p quakestrike-data-ingestion-test -f infrastructure/compose.integration.yml down -v
```

Confirm that integration cases execute. Host pytest without the test URLs
skips integration cases; those skips are not verification. Never supply a
development or production database URL to these fixtures.

Affected checks also include the worker suite and Ruff, private Astro check
and build, Bulletin check/build and affected tests, Backend unit tests and
typecheck, and Git whitespace checks.

## Lifecycle and recovery

One Redis control hash coordinates one shared active session. Redis time
determines the fixed four-hour deadline; repeated starts do not extend it.
End requires the owning UUID and closes access before deleting children.
Expiry closes access independently of physical cleanup.

Cleanup scans only the owning UUID's tool prefix, in at most ten scan batches
per pass. The server advances pending cleanup every five seconds. Failed
cleanup keeps the session closed and exposes Retry cleanup. A ten-second
lease recovers a lost cleanup process; a token fences stale completions.
Start refuses a closed session whose cleanup has not completed.

The control tombstone contains only bounded lifecycle metadata. It expires
24 hours after the original deadline, without extending retention on polling
or retry. Future business records must expire at the original deadline and
enforce the atomic active-session gate. No provider-call coordination is
implemented or needed until a later ticket adds a consumer.

## Ticket 57 review record — 13 October 2026

Starting HEAD: `46356db3fef9b0a17c03d3525366bce43c6159da`.
The implementation uses `main` in
`C:/Projects/quakestrikeph/redo/quakestrikeph`. The initial handoff left changes
uncommitted for review. The user subsequently authorized a local commit.
No worktree, implementation branch, push, merge, ticket closure, or deployment
was performed.

The changed areas are:

- `workers/src/quakestrike/alert_testing/`: private HTTP mapping, Application
  workflows, Domain session values, Redis coordination, and explicit runtime
  wiring. Existing production worker implementations remain unchanged.
- `apps/quakestrikeph-alert-testing/`: separate Astro pages, the accepted
  prototype's sidebar/header/session/dialog presentation, and real private
  HTTP actions. Prototype simulation actions are excluded.
- `packages/ui/`: eight existing controls, their existing mobile hook, theme,
  and mobile-sidebar CSS. Bulletin source paths become compatible re-exports.
  An exact comparison against starting HEAD confirmed unchanged control
  implementations, apart from internal import paths.
- Bulletin package/lockfile, Dockerfile, and local Compose mount: shared UI
  packaging. This adds no private-tool route to the public application.
- `packages/contracts/alert-testing/`: private version-1 response type and
  HTTP contract; `workers/pyproject.toml` and lockfile: explicit Redis dependency
  and isolated CLI entry point. Redis remains at the already locked 6.4.0.
- Nine private HTTP integration cases and ten origin-validation unit cases.
- ADR 0050, architecture source map, glossary, and this operations guide.

Verification performed:

| Command/check | Result |
| --- | --- |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests/unit` | 407 passed, 11 platform skips. |
| `uv run --project workers pytest --config-file workers/pyproject.toml workers/tests` | 416 passed, 328 skipped. All integration cases skipped without test URLs; this is not Redis verification. |
| New integration file with `--collect-only -q` | Nine cases collected successfully. |
| Exact Compose integration procedure above | 315 passed, two expected real-model skips. All nine private session workflow cases executed and passed. |
| Private session regression file through disposable Compose | Nine passed, including a synchronized connection burst. |
| Private origin unit tests through disposable Compose | Ten passed. |
| Documented `prediction-smoke-runner` command with `-k test_real_seis -s` | One passed, one failed, 24 deselected. The persisted-forecast check passed; the existing replica benchmark failed its 30-second worker readiness deadline. No tests skipped. |
| Bulletin Docker image build | Passed with the shared UI package included; existing hints and large-chunk warning remain. |
| `uv run --project workers ruff check workers database` | Passed. |
| `uv run --project workers ruff format --check workers database` | Passed, 206 files. |
| Private Astro `check` and `build` | Passed, zero diagnostics; three static pages. |
| Bulletin Astro `check` and `build` | Passed; zero errors/warnings, 11 existing hints, existing large-chunk build warning. |
| Bulletin identity, SMS enrollment, location edit, event-results, and forecast-replay scripts | Passed. |
| Backend TypeScript build and four existing unit files via `node --test` | 29 passed. `npm` is absent from this shell; equivalent build/test commands used pnpm and Node. |
| `pnpm --dir apps/backend-api run typecheck` | Passed. |
| `git diff --check` and `git diff --cached --check` | Passed. |
| Shared control provenance comparison | Eight controls and mobile hook match starting HEAD, with import-path changes only. |

Docker was unavailable during the initial handoff. The original error was:

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

The initial Windows worker invocation emitted a WMI resource exception but
continued to the passing unit summary. The later full host suite also passed
its executable cases. Existing platform skips cover unavailable symlink
creation and Linux-only provider deadlines. Bulletin's existing
`openapi-typescript@7.13.0` peer constraint requests TypeScript 5, while the
repository pins TypeScript 6.0.2; its checks and build passed without changing
those versions.

Docker became available before the authorized commit. The integration run
verified Redis concurrency, fixed expiry, closure before deletion, cleanup
failure/recovery, stale ownership, and isolation. Its first run exposed an
intermittent connection reset during concurrent starts. A synchronized burst
reproduced the failure while acceptance paused briefly. Setting the private
server's connection backlog to 16 fixed the regression; handler concurrency
remains bounded at 16. The full integration rerun passed.

The separate real-model runner mounted the approved local bundle read-only.
Its forecast check passed. The replica benchmark reported
`Prediction Worker replicas did not become ready.` at its existing 30-second
deadline. That benchmark remains failed; production prediction code and its
timeout were not changed for this session-control ticket.

Browser inspection established presentation and dependency-unavailable
behavior during the initial Redis outage; the manual
Start/End, active sidebar, and confirmation-dialog checks remain for the user.

No specification deviation is intended. The prototype's simulated queue,
provider activity, and completion buttons are excluded because issue 57 adds
only real session controls. Text identifies later-ticket features as
unavailable. Tailscale Serve admission and target activation remain explicit
operator actions. No real SMS/email submission or production data write occurs
in this slice.
