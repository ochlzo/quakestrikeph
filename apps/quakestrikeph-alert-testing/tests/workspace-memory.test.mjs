import assert from "node:assert/strict";
import { test } from "node:test";
import { WorkspaceMemory } from "../src/features/workspace/workspace-memory.ts";

const active = (owner = "owner") => ({ status: "active", session_id: owner,
  expires_at_ms: Date.now() + 14400000, server_time_ms: Date.now() });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const prepared = (owner = "owner", id = "event") => ({ session_id: owner, event_id: id,
  observations: [{ event_id: "observation", latitude: 9, longitude: 125 }],
  forecast: { quantiles: [2, 4, 6] } });
const workspace = () => { const memory = new WorkspaceMemory(); memory.accept(active()); return memory; };

test("submission retries keep the reviewed identity until a deliberate new event", async () => {
  const memory = workspace();
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  await memory.prepare(async () => prepared());
  let original, calls = 0;
  const send = async body => {
    calls++;
    if (calls === 1) { original = body; throw new Error("lost response"); }
    if (calls <= 3) {
      assert.equal(body, original);
      assert.deepEqual(body.selected, ["tester"]);
      return { event_id: "event", queue_status: calls === 2 ? "pending" : "enqueued" };
    }
    assert.notEqual(body, original);
    assert.equal(body.scenario.event_id, "new-event");
    return { event_id: body.scenario.event_id, queue_status: "enqueued" };
  };
  await memory.submit(send);
  assert.equal(memory.state.submissionPending, true);
  assert.equal(memory.state.submissionError, "Could not confirm sending.");
  assert.equal(memory.state.prepared.event_id, "event");
  const reviewed = memory.state.draft;
  memory.edit({ ...reviewed, selected: ["different"] });
  await memory.prepare(async () => prepared("owner", "different"));
  assert.equal(memory.state.draft, reviewed);
  await memory.submit(send);
  assert.equal(memory.state.submission, null);
  assert.equal(memory.state.submissionPending, true);
  assert.equal(memory.state.submissionError, "");
  assert.equal(memory.state.prepared.event_id, "event");
  await memory.submit(send);
  assert.equal(memory.state.submission.event_id, "event");
  assert.equal(memory.state.submissionPending, false);
  assert.equal(memory.state.submissionError, "");
  assert.equal(calls, 3);
  await memory.submit(send);
  assert.equal(calls, 3);
  await memory.prepare(async () => prepared("owner", "new-event"));
  await memory.submit(send);
  assert.equal(calls, 4);
  assert.equal(memory.state.submission.event_id, "new-event");
});

test("replacement clears submission and rejects the delayed response", async () => {
  const memory = workspace();
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  await memory.prepare(async () => prepared());
  const response = deferred();
  const submission = memory.submit(() => response.promise);
  memory.accept(active("replacement"));
  response.resolve({ event_id: "event", queue_status: "enqueued" });
  await submission;
  assert.equal(memory.state.submission, null);
  assert.equal(memory.state.submissionPending, false);
  assert.equal(memory.state.owner, "replacement");
});

test("validation rejection preserves reviewed values and unlocks editing", async () => {
  const memory = workspace();
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  await memory.prepare(async () => prepared());
  const original = memory.state.prepared;
  await memory.submit(async () => { throw { code: "invalid-request" }; });
  assert.equal(memory.state.prepared, original);
  assert.equal(memory.state.submissionPending, false);
  memory.edit({ ...memory.state.draft, selected: ["other"] });
  assert.deepEqual(memory.state.draft.selected, ["other"]);
});

test("tester edits preserve immutable preparation while scenario edits invalidate it", async () => {
  const memory = workspace();
  const result = prepared();
  await memory.prepare(async () => result);
  assert.equal(memory.state.prepared, result);
  assert.throws(() => { result.observations[0].latitude = 0; }, TypeError);
  assert.throws(() => { result.forecast.quantiles.push(7); }, TypeError);
  const listener = () => {};
  memory.listeners.add(listener);
  memory.listeners.delete(listener);
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  assert.equal(memory.state.prepared, result);
  memory.accept(active());
  assert.equal(memory.state.prepared, result);
  memory.edit({ ...memory.state.draft, inputs: { ...memory.state.draft.inputs, radius: "43" } });
  assert.equal(memory.state.prepared, null);
  assert.deepEqual(memory.state.draft.selected, ["tester"]);
});

test("A to B to A edits reject an older response even when values match again", async () => {
  const memory = workspace();
  const draft = memory.state.draft;
  const response = deferred();
  const request = memory.prepare(() => response.promise);
  memory.edit({ ...draft, inputs: { ...draft.inputs, radius: "43" } });
  memory.edit(draft);
  response.resolve(prepared());
  await request;
  assert.equal(memory.state.prepared, null);
  assert.equal(memory.state.preparing, false);
});

test("the newer preparation wins when settings repeat", async () => {
  const memory = workspace();
  const older = deferred();
  const request = memory.prepare(() => older.promise);
  const result = prepared("owner", "newer");
  await memory.prepare(async () => result);
  older.resolve(prepared());
  await request;
  assert.equal(memory.state.prepared, result);
});

for (const status of ["ended", "expired", "replacement"]) {
  test(`${status} clears the workspace and rejects pending preparation`, async () => {
    const memory = workspace();
    memory.edit({ ...memory.state.draft, selected: ["tester"] });
    const response = deferred();
    const request = memory.prepare(() => response.promise);
    memory.accept(status === "replacement" ? active("replacement") : { status });
    response.resolve(prepared());
    await request;
    assert.equal(memory.state.prepared, null);
    assert.deepEqual(memory.state.draft.selected, []);
    assert.equal(memory.state.preparing, false);
  });
}

test("deadline invalidates preparation even without session polling", async () => {
  const memory = workspace();
  const session = active();
  memory.accept(session);
  await memory.prepare(async () => prepared());
  memory.expire(session.expires_at_ms + 1);
  assert.equal(memory.state.ready, false);
  assert.equal(memory.state.prepared, null);
});

test("field errors apply only to the request that still owns the draft", async () => {
  const memory = workspace();
  const response = deferred();
  const request = memory.prepare(() => response.promise);
  memory.edit({ ...memory.state.draft, inputs: { ...memory.state.draft.inputs, radius: "43" } });
  response.reject({ code: "invalid-scenario", fields: { radius: "Old error" } });
  await request;
  assert.deepEqual(memory.state.errors, {});
  await memory.prepare(async () => { throw { code: "invalid-scenario", fields: { radius: "Correct radius" } }; });
  assert.deepEqual(memory.state.errors, { radius: "Correct radius" });
  assert.equal(memory.state.preparationError, "Check the highlighted fields.");
  assert.equal(memory.state.preparing, false);
});

test("session conflict clears selections while dependency failure retains inputs", async () => {
  const memory = workspace();
  memory.edit({ ...memory.state.draft, selected: ["tester"] });
  await memory.prepare(async () => { throw new Error("Unavailable"); });
  assert.deepEqual(memory.state.draft.selected, ["tester"]);
  assert.ok(memory.state.preparationError);
  await memory.prepare(async () => { throw { code: "session-conflict" }; });
  assert.equal(memory.state.ready, false);
  assert.deepEqual(memory.state.draft.selected, []);
});
