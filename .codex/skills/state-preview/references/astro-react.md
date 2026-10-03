# Astro/React adapter

The maintained runtime lives in `assets/runtime/`. Initialization copies it into the app-root `.state-preview/` folder.

## Runtime files

- `toolbar.ts` and `toolbar.css`: dependency-free toolbar shell.
- `session.ts`: connects the shell to one target and waits for readiness.
- `adapter.ts`: target selector, state labels, sample data, and optional repeat actions.
- `state-preview.mjs`: copied CLI for applying and removing journaled source edits.
- `manifest.json`: app root and applied preview snippets. The adapter holds the target identity.

The app supplies the React bridge because the shell cannot safely infer component state or mutation entry points from the DOM.

## Events

All event details include the adapter's `target` ID. Ignore events for other targets.

| Event | Direction | Detail |
| --- | --- | --- |
| `state-preview:connect` | Session → component | `{ target }` |
| `state-preview:ready` | Component → session | `{ target, available: boolean }` |
| `state-preview:select` | Toolbar → component | `{ target, state }`; `state` is an adapter state or `null` |

The component installs listeners only in development and on its supported screen. It reports readiness after its state is usable. If real work is pending, report `available: false`; the toolbar waits instead of replacing an in-flight request.

For selection, validate the target and expected state shape. Snapshot existing values once, then render the supplied sample state through the existing components. Use a separate preview value rather than replacing the real request's status or error result. Keep preview samples in the runtime adapter, not in production components.

For `state: null`, restore the snapshot, clear preview status, and dismiss only preview-created notifications. Handle repeat selection of the same state, particularly stacked toasts. Clean listeners on unmount and notify readiness again when the target screen becomes available.

## Development loader

Inject a marked block into the layout that renders the target. Calculate the relative import from that layout to the app-root runtime:

```astro
<!-- state-preview:start loader -->
<script>
  if (import.meta.env.DEV) {
    import('../../.state-preview/session').then(({ startPreview }) => startPreview());
  }
</script>
<!-- state-preview:end loader -->
```

That relative path is an example for `<app-root>/src/layouts/`. Calculate it for the actual layout. Preserve existing loaders and CSP. Keep the runtime inside the app root so Vite's existing file allowance serves it.

## Patch plan

Create an array of edits. Paths are relative to the app root:

```json
[
  {
    "file": "src/Example.tsx",
    "before": "const pending = busy;",
    "after": "const pending = busy || preview?.submitting; // state-preview:pending"
  }
]
```

Use enough context to make each `before` snippet unique. Insertions also need a unique existing anchor. Apply preserves the anchor inside `after`. A bridge block, loader, rendering overrides, and action guards each need journal entries. Edits apply in order and remove in reverse order, so nested edits are supported.

Preserve the source file's line endings when building snippets. Preview artifacts, including screenshots and adapter-generation scripts, belong inside `.state-preview/`.

Run the CLI's `apply` command rather than editing temporary snippets outside the journal. Keep permanent UI changes outside those snippets. If a snippet later changes, removal stops and names the conflict instead of deleting that work.

## Account example

`adapter.ts` ships with account-auth examples for normal, loading, submitting, field errors, and repeated error toasts. Replace the ID, selector, states, and data for another UI target. These are adapter examples, not a universal state list.

An account bridge uses sample `inputs`, `errors`, `loading`, `submitting`, and `toast` data from the selected state. It guards Clerk/API actions while any preview is active. Errors render through the existing `Field`/`Input` and toast components; the preview tool does not supply product styles.
