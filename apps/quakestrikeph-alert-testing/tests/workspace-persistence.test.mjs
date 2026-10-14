import assert from "node:assert/strict";
import { test } from "node:test";
import { WorkspaceMemory, initialInputs } from "../src/features/workspace/workspace-memory.ts";
import { WorkspacePersistence } from "../src/features/workspace/workspace-persistence.ts";

const active = owner => ({ status: "active", session_id: owner,
  expires_at_ms: Date.now() + 14400000, server_time_ms: Date.now() });
const tick = () => new Promise(resolve => setImmediate(resolve));
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const record = (inputs = initialInputs()) => ({ revision: 3, inputs, selected: [], prepared: null, preview_url: null });

test("restoration preserves empty values and selections without saving defaults", async () => {
  const memory = new WorkspaceMemory(), loading = deferred();
  let writes = 0;
  new WorkspacePersistence(memory, "tab", () => loading.promise, async () => { writes++; });
  memory.accept(active("one"));
  assert.equal(memory.state.restoring, true);
  const inputs = { ...initialInputs(), location: "", magnitude: "" };
  loading.resolve(record(inputs));
  await tick();
  assert.deepEqual(memory.state.draft, { inputs, selected: [] });
  assert.equal(writes, 0);
  assert.equal(memory.state.restoring, false);
  memory.accept(active("one"));
  assert.deepEqual(memory.state.draft.inputs, inputs);
});

test("a late restore cannot overwrite a replacement session", async () => {
  const memory = new WorkspaceMemory(), old = deferred();
  new WorkspacePersistence(memory, "tab", owner => owner === "old" ? old.promise : Promise.resolve(record()), async () => {});
  memory.accept(active("old"));
  memory.accept(active("new"));
  await tick();
  old.resolve(record({ ...initialInputs(), location: "obsolete" }));
  await tick();
  assert.notEqual(memory.state.draft.inputs.location, "obsolete");
  assert.equal(memory.state.owner, "new");
});

test("serialized saves retain newer selection changes and only expose the matching preview", async () => {
  const memory = new WorkspaceMemory(), first = deferred(), calls = [];
  const persistence = new WorkspacePersistence(memory, "tab", async () => record(), body => {
    calls.push(body);
    return calls.length === 1 ? first.promise : Promise.resolve({ revision: 5, preview_url: null });
  });
  memory.accept(active("one")); await tick();
  memory.edit({ ...memory.state.draft, selected: ["first"] });
  const saving = persistence.save();
  memory.edit({ ...memory.state.draft, selected: ["second"] });
  await persistence.save();
  assert.equal(calls.length, 1);
  first.resolve({ revision: 4, preview_url: null }); await saving;
  await persistence.save();
  assert.equal(calls[1].revision, 4);
  assert.deepEqual(calls[1].selected, ["second"]);
  memory.accept({ status: "inactive" });
});

test("failed restoration blocks autosave and can be retried", async () => {
  const memory = new WorkspaceMemory(); let attempts = 0, writes = 0;
  const persistence = new WorkspacePersistence(memory, "tab", async () => {
    if (++attempts === 1) throw new Error("offline"); return record();
  }, async () => { writes++; });
  memory.accept(active("one")); await tick();
  assert.equal(memory.state.restoreError, "Could not load your saved changes.");
  await persistence.save(); assert.equal(writes, 0);
  await persistence.retry(); assert.equal(memory.state.restoreError, "");
});

test("a lost save response reconciles the stored revision before saving newer edits", async () => {
  const memory = new WorkspaceMemory(); let stored = record(), calls = [];
  const persistence = new WorkspacePersistence(memory, "tab", async () => stored, async body => {
    calls.push(body);
    stored = { revision: body.revision + 1, inputs: body.inputs, selected: body.selected,
      prepared: body.scenario, preview_url: null };
    if (calls.length === 1) throw new Error("lost response");
    return { revision: stored.revision, preview_url: null };
  });
  memory.accept(active("one")); await tick();
  memory.edit({ ...memory.state.draft, selected: ["first"] });
  await persistence.save();
  assert.equal(memory.state.saveError, "");
  memory.edit({ ...memory.state.draft, selected: ["second"] });
  await persistence.save();
  assert.equal(calls[1].revision, 4);
  memory.accept({ status: "inactive" });
});

test("newer edits recover after both the save response and its confirmation read are lost", async () => {
  const memory = new WorkspaceMemory(); let stored = record(), reads = 0;
  const revisions = [];
  const persistence = new WorkspacePersistence(memory, "tab", async () => {
    if (++reads === 2) throw new Error("confirmation unavailable");
    return stored;
  }, async body => {
    revisions.push(body.revision);
    assert.equal(body.revision, stored.revision);
    stored = { revision: body.revision + 1, inputs: body.inputs, selected: body.selected,
      prepared: body.scenario, preview_url: null };
    if (revisions.length === 1) throw new Error("response lost");
    return { revision: stored.revision, preview_url: null };
  });
  memory.accept(active("one")); await tick();
  memory.edit({ ...memory.state.draft, selected: ["first"] });
  await persistence.save();
  assert.ok(memory.state.saveError);
  memory.edit({ ...memory.state.draft, selected: ["newer"] });
  await persistence.retry();
  assert.deepEqual(revisions, [3, 4]);
  assert.equal(stored.revision, 5);
  assert.deepEqual(stored.selected, ["newer"]);
  assert.deepEqual(memory.state.draft.selected, ["newer"]);
  assert.equal(memory.state.saveError, "");
  memory.accept({ status: "inactive" });
});

test("an unrelated stored revision cannot be overwritten during lost-save recovery", async () => {
  const memory = new WorkspaceMemory(); let stored = record(), reads = 0, writes = 0;
  const persistence = new WorkspacePersistence(memory, "tab", async () => {
    if (++reads === 2) throw new Error("confirmation unavailable");
    return stored;
  }, async body => {
    writes++;
    stored = { revision: 4, inputs: body.inputs, selected: ["other-writer"], prepared: null, preview_url: null };
    throw new Error("response lost");
  });
  memory.accept(active("one")); await tick();
  memory.edit({ ...memory.state.draft, selected: ["first"] });
  await persistence.save();
  memory.edit({ ...memory.state.draft, selected: ["newer"] });
  await persistence.retry();
  assert.equal(writes, 1);
  assert.deepEqual(stored.selected, ["other-writer"]);
  assert.deepEqual(memory.state.draft.selected, ["newer"]);
  assert.ok(memory.state.saveError);
  memory.accept({ status: "inactive" });
});

test("expired preparation restoration can retry a write that did not commit", async () => {
  const memory = new WorkspaceMemory();
  let stored = { ...record(), prepared: { event_id: "expired", forecast: { window_end_ms: 0 } },
    preview_url: "https://example.invalid/forecasts/expired?test=true" };
  const revisions = [];
  const persistence = new WorkspacePersistence(memory, "tab", async () => stored, async body => {
    revisions.push(body.revision);
    if (revisions.length === 1) throw new Error("write unavailable");
    assert.equal(body.revision, stored.revision);
    stored = { revision: body.revision + 1, inputs: body.inputs, selected: body.selected,
      prepared: body.scenario, preview_url: null };
    return { revision: stored.revision, preview_url: null };
  });
  memory.accept(active("one")); await tick();
  assert.equal(memory.state.prepared, null);
  assert.equal(memory.state.previewUrl, null);
  memory.edit({ ...memory.state.draft, selected: ["first"] });
  await persistence.save();
  assert.ok(memory.state.saveError);
  memory.edit({ ...memory.state.draft, selected: ["newer"] });
  await persistence.retry();
  assert.deepEqual(revisions, [3, 3]);
  assert.equal(stored.revision, 4);
  assert.equal(stored.prepared, null);
  assert.deepEqual(stored.selected, ["newer"]);
  assert.deepEqual(memory.state.draft.selected, ["newer"]);
  assert.equal(memory.state.saveError, "");
  memory.accept({ status: "inactive" });
});
