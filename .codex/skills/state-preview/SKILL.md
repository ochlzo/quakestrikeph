---
name: state-preview
description: Add a temporary development toolbar for browsing an existing UI's states with sample data. Use for state previews, simulated loading or errors, and removing preview tools. Supports Astro/React first.
---

# State Preview

Build a removable preview of one existing UI target. Preserve the feature's real behavior and visual identity.

For removal requests, go directly to **Remove**. Closing the toolbar is separate from removing its code.

## Start or resume

1. Resolve the actual checkout and app root. Use the directory containing the target app's package and runtime configuration.
2. Read the target component and identify its real states, inputs, and side effects.
3. Run `node <skill-dir>/scripts/state-preview.mjs status --root <app-root>`.
4. If a session exists, resume that target or remove it before starting another. Never overwrite an active session.
5. Run `node <skill-dir>/scripts/state-preview.mjs init --root <app-root>`.

Initialization creates **`<app-root>/.state-preview/`** and adds a rule to the app's `.gitignore`. For QuakeStrike PH Bulletin, use `quakestrikeph/apps/quakestrikeph-bulletin/.state-preview/`. Store every generated adapter, script, patch plan, fixture, and preview artifact in that folder. Keep reusable templates in this skill's `assets/runtime/`. Keep source bridges minimal and journaled.

## Connect the UI

Read [references/astro-react.md](references/astro-react.md) before connecting Astro/React targets. It defines the toolbar shell, event contract, side-effect guards, and cleanup journal.

- Define relevant states and fictional sample data in `.state-preview/adapter.ts`. Forms receive sample inputs in every preview state; loading placeholders may conceal those inputs.
- Use the supplied toolbar shell. Its arrows and dropdown select states; repeatable states get an additional action button.
- Apply permanent feature changes separately from temporary preview edits.
- Write temporary edits as exact `before`/`after` snippets in `.state-preview/edits.json`, with identifiable `state-preview` comments.
- From the app root, run `node .state-preview/state-preview.mjs apply --root . --edits .state-preview/edits.json`.
- Load the session only behind `import.meta.env.DEV`. The app-local runtime uses Vite's existing file allowance.

Preview actions must use local state. Guard every target action that could send requests, persist changes, navigate externally, or mutate credentials. Guard programmatic entry points as well as visible buttons. Initial framework loading and asset requests may continue. Snapshot original values before the first preview and restore them on close. Keep toast IDs and other preview resources separate so restoration affects only preview resources.

The shell has no helper server or polling requirement. Closing **×** restores the live UI and removes the toolbar from the page. It leaves files installed; reloading reopens the development preview.

## Verify and hand off

Check the actual target in the browser: state selection, fictional inputs, action guards, restoration, keyboard operation, and desktop/mobile layout. Run the app's appropriate type/build checks. Confirm the production build excludes the loader, toolbar, and sample fixtures. Show the toolbar and provide the removal command. Leave it installed for the user to browse until removal is requested.

Before committing target source changes, remove the preview or exclude its journaled snippets from the commit. Imports into ignored runtime files must stay local.

## Remove

From the app root, run `node .state-preview/state-preview.mjs remove --root . --check` first. Then run the same command without `--check`.

Removal reverses only journaled preview snippets, removes the generated ignore rule, and deletes `.state-preview/`. It preserves permanent feature changes and unrelated edits. If a journaled snippet changed, the tool refuses before writing. Inspect that snippet and update the journal only after separating preview code from feature work. Never restore whole source files or use Git reset for cleanup. Run the app checks and confirm the toolbar is absent afterward.
