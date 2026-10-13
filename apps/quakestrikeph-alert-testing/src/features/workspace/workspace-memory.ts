import type { SessionState } from "../../../../../packages/contracts/alert-testing/session-v1.ts";
import type { PreparedScenario, ScenarioInputs } from "../../../../../packages/contracts/alert-testing/scenarios-v1.ts";
import type { ScenarioResult, SubmissionRequest } from "../../../../../packages/contracts/alert-testing/delivery-v1.ts";

export type Inputs = ScenarioInputs;
export type Draft = { inputs: Inputs; selected: string[] };
export const initialInputs = (): Inputs => ({
  location: "12 km NE of Surigao City, Surigao del Norte", magnitude: "5.2", depth: "18",
  latitude: "9.86", longitude: "125.55",
  time: new Date(Date.now() + 7 * 3600000).toISOString().slice(0, 16),
  p1: "82", p4: "28", p5: "8", count: "12.4", radius: "42",
  q05: "2.8", q50: "4.2", q95: "5.6", local: "18", background: "4", spread: "20",
  spillover: "2", preset: "moderate",
});

function freeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// One instance per tab; no storage or server-side draft records.
export class WorkspaceMemory {
  state = {
    draft: { inputs: initialInputs(), selected: [] } as Draft,
    owner: "", ready: false, revision: 0, prepared: null as PreparedScenario | null,
    preparing: false, errors: {} as Record<string, string>, preparationError: "",
    submitting: false, submissionError: "", submission: null as ScenarioResult | null,
    submissionPending: false,
  };
  listeners = new Set<() => void>();
  private request = 0;
  private deadline = 0;
  private submissionBody: SubmissionRequest | null = null;
  private notify() { this.listeners.forEach(listener => listener()); }

  accept(session: SessionState, now = Date.now()) {
    const owner = session.status === "active" ? session.session_id ?? "" : "";
    const deadline = now + Math.max(0, (session.expires_at_ms ?? 0) - (session.server_time_ms ?? 0));
    this.deadline = owner && owner === this.state.owner ? Math.min(this.deadline, deadline) : deadline;
    if (owner !== this.state.owner || !owner) {
      this.submissionBody = null;
      this.request++;
      this.state = { ...this.state, draft: { inputs: initialInputs(), selected: [] },
        owner, ready: !!owner, revision: this.state.revision + 1, prepared: null,
        preparing: false, errors: {}, preparationError: "", submitting: false,
        submissionPending: false, submissionError: "", submission: null };
    } else this.state = { ...this.state, ready: true };
    this.expire(now);
    this.notify();
  }

  expire(now = Date.now()) {
    if (this.state.ready && now >= this.deadline) {
      this.submissionBody = null;
      this.request++;
      this.state = { ...this.state, owner: "", ready: false,
        draft: { inputs: initialInputs(), selected: [] }, revision: this.state.revision + 1,
        prepared: null, preparing: false, errors: {}, preparationError: "", submitting: false,
        submissionPending: false, submissionError: "", submission: null };
      this.notify();
    }
  }

  edit(draft: Draft) {
    this.expire();
    if (!this.state.ready || this.state.submitting || this.state.submissionPending) return;
    const changed = JSON.stringify(draft.inputs) !== JSON.stringify(this.state.draft.inputs);
    if (changed) this.request++;
    this.state = { ...this.state, draft: { inputs: { ...draft.inputs }, selected: [...draft.selected] },
      ...(changed ? { revision: this.state.revision + 1, prepared: null, preparing: false,
        errors: {}, preparationError: "", submission: null } : {}) };
    this.notify();
  }

  async prepare(send: (owner: string, inputs: Inputs) => Promise<PreparedScenario>) {
    this.expire();
    if (!this.state.ready || this.state.submitting || this.state.submissionPending) return;
    this.submissionBody = null;
    const { owner, revision } = this.state;
    const request = ++this.request;
    this.state = { ...this.state, prepared: null, preparing: true, errors: {}, preparationError: "",
      submission: null, submissionError: "" };
    this.notify();
    const valid = () => {
      this.expire();
      return this.state.ready && this.state.owner === owner && this.state.revision === revision && this.request === request;
    };
    try {
      const prepared = await send(owner, { ...this.state.draft.inputs });
      if (!valid()) return;
      if (prepared.session_id !== owner) throw new Error("Invalid preparation owner.");
      this.state = { ...this.state, prepared: freeze(prepared), preparing: false };
    } catch (reason) {
      if (!valid()) return;
      const error = reason as { code?: string; fields?: Record<string, string> };
      if (error.code === "session-conflict") {
        this.accept({ status: "inactive" });
        return;
      }
      this.state = { ...this.state, preparing: false, errors: error.fields ?? {},
        preparationError: error.code === "invalid-scenario" ? "Correct the marked fields, then prepare again."
          : "Preparation failed. Check the session and try again." };
    }
    this.notify();
  }

  async submit(send: (body: SubmissionRequest) => Promise<ScenarioResult>) {
    this.expire();
    if (!this.state.ready || !this.state.prepared || this.state.submitting || this.state.submission) return;
    if (!this.state.draft.selected.length) return;
    const owner = this.state.owner;
    const body = this.submissionBody ?? freeze({ session_id: owner,
      inputs: { ...this.state.draft.inputs }, scenario: this.state.prepared,
      selected: [...this.state.draft.selected] });
    this.submissionBody = body;
    this.state = { ...this.state, submitting: true, submissionPending: true, submissionError: "" };
    this.notify();
    try {
      const result = await send(body);
      this.expire();
      if (this.state.owner !== owner || this.submissionBody !== body) return;
      this.state = { ...this.state, submitting: false,
        submissionPending: result.queue_status === "pending",
        submission: result.queue_status === "enqueued" ? result : null,
        submissionError: result.queue_status === "pending" ? "The scenario is saved, but queue publication is pending. Retry the same submission." : "" };
    } catch (reason) {
      this.expire();
      if (this.state.owner !== owner || this.submissionBody !== body) return;
      const error = reason as { code?: string; fields?: Record<string, string> };
      if (error.code === "session-conflict") { this.accept({ status: "inactive" }); return; }
      const invalid = error.code === "invalid-request" || error.code === "invalid-scenario";
      if (invalid) this.submissionBody = null;
      this.state = { ...this.state, submitting: false, submissionPending: !invalid,
        errors: error.fields ?? {}, submissionError: invalid
          ? "Submission was rejected. Review the inputs and prepare again."
          : "Submission could not be confirmed. Retry to check the same scenario." };
    }
    this.notify();
  }
}
