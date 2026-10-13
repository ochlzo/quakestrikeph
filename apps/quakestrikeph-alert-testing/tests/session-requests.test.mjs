import assert from "node:assert/strict";
import test from "node:test";
import { SessionRequests } from "../src/features/sessions/session-requests.ts";

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup() {
  const calls = [], results = [], errors = [], pending = [];
  const requests = new SessionRequests((action, owner) => {
    const response = deferred();
    calls.push({ action, owner, ...response });
    return response.promise;
  }, result => results.push(result), error => errors.push(error), action => pending.push(action));
  return { requests, calls, results, errors, pending };
}

for (const action of ["start", "end", "cleanup"]) {
  test(`${action} proceeds during polling; stale success cannot overwrite its result`, async () => {
    const { requests, calls, results, errors, pending } = setup();
    const polling = requests.refresh();
    const mutation = requests.act(action, "owning-session");
    assert.equal(calls.length, 2);
    assert.equal(calls[1].action, action);
    assert.equal(calls[1].owner, "owning-session");
    await requests.act(action, "owning-session");
    await requests.refresh();
    assert.equal(calls.length, 2, "duplicate mutations and polling wait during a mutation");
    calls[1].resolve({ status: action === "start" ? "active" : "ended", session_id: "new-state" });
    await mutation;
    calls[0].resolve({ status: "active", session_id: "old-state" });
    await polling;
    assert.equal(results.length, 1);
    assert.equal(results[0].session_id, "new-state");
    assert.deepEqual(errors, []);
    assert.deepEqual(pending, [action, null]);
  });
}

test("stale polling failure cannot replace a successful mutation", async () => {
  const { requests, calls, results, errors } = setup();
  const polling = requests.refresh();
  const mutation = requests.act("end", "owning-session");
  assert.equal(calls.length, 2);
  calls[1].resolve({ status: "ended" });
  await mutation;
  calls[0].reject(new Error("stale poll failed"));
  await polling;
  assert.deepEqual(results, [{ status: "ended" }]);
  assert.deepEqual(errors, []);
});

test("mutation failure clears pending, ignores old polling, and allows recovery", async () => {
  const { requests, calls, results, errors, pending } = setup();
  const polling = requests.refresh();
  const mutation = requests.act("cleanup", "owning-session");
  assert.equal(calls.length, 2);
  const failure = new Error("cleanup unavailable");
  calls[1].reject(failure);
  await mutation;
  calls[0].resolve({ status: "active" });
  await polling;
  assert.deepEqual(errors, [failure]);
  assert.deepEqual(results, []);
  assert.deepEqual(pending, ["cleanup", null]);
  const recovery = requests.refresh();
  calls[2].resolve({ status: "cleanup-failure" });
  await recovery;
  const retry = requests.act("cleanup", "owning-session");
  calls[3].resolve({ status: "ended" });
  await retry;
  assert.deepEqual(results, [{ status: "cleanup-failure" }, { status: "ended" }]);
});

test("poll finishing first cannot release the mutation lock or apply old state", async () => {
  const { requests, calls, results, pending } = setup();
  const polling = requests.refresh();
  const mutation = requests.act("end", "owning-session");
  calls[0].resolve({ status: "active" });
  await polling;
  await requests.act("end", "owning-session");
  await requests.refresh();
  assert.equal(calls.length, 2);
  assert.deepEqual(results, []);
  assert.deepEqual(pending, ["end"]);
  calls[1].resolve({ status: "ended" });
  await mutation;
  assert.deepEqual(results, [{ status: "ended" }]);
  assert.deepEqual(pending, ["end", null]);
});

test("unmount invalidates pending responses", async () => {
  const { requests, calls, results, errors } = setup();
  const polling = requests.refresh();
  requests.invalidate();
  calls[0].resolve({ status: "active" });
  await polling;
  const mutation = requests.act("end", "owning-session");
  requests.invalidate();
  calls[1].reject(new Error("old page failure"));
  await mutation;
  assert.deepEqual(results, []);
  assert.deepEqual(errors, []);
});
