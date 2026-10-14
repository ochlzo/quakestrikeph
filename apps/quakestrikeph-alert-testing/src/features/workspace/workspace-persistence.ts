import type { PreparedScenario } from "../../../../../packages/contracts/alert-testing/scenarios-v1.ts";
import type { Inputs, WorkspaceMemory } from "./workspace-memory.ts";

export type SavedWorkspace = { revision: number; missing?: boolean; inputs: Inputs; selected: string[];
  prepared: PreparedScenario | null; preview_url: string | null };
export type WorkspaceSave = { session_id: string; workspace_id: string; revision: number;
  inputs: Inputs; selected: string[]; scenario: PreparedScenario | null };

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonical(item)]));
  }
  return value;
}

const fingerprint = (inputs: Inputs, selected: string[], scenario: PreparedScenario | null) =>
  JSON.stringify(canonical({ inputs, selected, scenario }));

export class WorkspacePersistence {
  private owner = "";
  private revision = 0;
  private restored = false;
  private epoch = 0;
  private saved = "";
  private stored = "";
  private attempted = "";
  private unconfirmed: { revision: number; snapshot: string } | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private inFlight = false;
  private memory: WorkspaceMemory;
  private workspaceId: string;
  private read: (owner: string, workspace: string) => Promise<SavedWorkspace>;
  private write: (body: WorkspaceSave) => Promise<{ revision: number; preview_url: string | null }>;

  constructor(memory: WorkspaceMemory, workspaceId: string,
    read: (owner: string, workspace: string) => Promise<SavedWorkspace>,
    write: (body: WorkspaceSave) => Promise<{ revision: number; preview_url: string | null }>) {
    this.memory = memory;
    this.workspaceId = workspaceId;
    this.read = read;
    this.write = write;
    memory.listeners.add(() => this.changed());
  }

  private snapshot() {
    return fingerprint(this.memory.state.draft.inputs, this.memory.state.draft.selected, this.memory.state.prepared);
  }

  private changed() {
    const owner = this.memory.state.owner;
    if (owner !== this.owner) {
      this.owner = owner;
      this.epoch++;
      this.restored = false;
      this.inFlight = false;
      clearTimeout(this.timer);
      this.saved = this.stored = this.attempted = "";
      this.unconfirmed = null;
      if (owner) void this.restore();
      else this.memory.persistence({ restoring: false, restoreError: "", saveError: "", saving: false });
      return;
    }
    if (!owner || !this.restored || this.inFlight) return;
    const snapshot = this.snapshot();
    if (snapshot === this.saved || snapshot === this.attempted) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.save(), 300);
  }

  async restore() {
    const owner = this.owner, epoch = this.epoch;
    this.restored = false;
    this.memory.persistence({ restoring: true, restoreError: "", saveError: "", saving: false });
    try {
      const record = await this.read(owner, this.workspaceId);
      if (epoch !== this.epoch || owner !== this.memory.state.owner) return;
      this.revision = record.revision;
      this.stored = record.missing ? "" : fingerprint(record.inputs, record.selected, record.prepared);
      if (!record.missing) this.memory.recover(record);
      this.saved = record.missing ? "" : this.snapshot();
      this.attempted = "";
      this.restored = true;
      this.memory.persistence({ restoring: false });
    } catch {
      if (epoch === this.epoch) this.memory.persistence({ restoring: false,
        restoreError: "Could not load your saved changes." });
    }
  }

  async save() {
    if (!this.restored || this.inFlight || !this.owner) return;
    const epoch = this.epoch, owner = this.owner, snapshot = this.snapshot();
    this.attempted = snapshot;
    this.inFlight = true;
    const data = JSON.parse(snapshot) as Omit<WorkspaceSave, "session_id" | "workspace_id" | "revision">;
    this.memory.persistence({ saving: true, saveError: "" });
    try {
      if (this.unconfirmed) {
        await this.reconcile(owner, epoch);
        if (epoch !== this.epoch) return;
        if (this.unconfirmed) throw new Error("Workspace revision is unresolved.");
      }
      this.unconfirmed = { revision: this.revision, snapshot };
      const result = await this.write({ ...data, session_id: owner, workspace_id: this.workspaceId, revision: this.revision });
      if (epoch !== this.epoch) return;
      this.unconfirmed = null;
      this.revision = result.revision;
      this.saved = snapshot;
      this.stored = snapshot;
      this.memory.persistence({ previewUrl: data.scenario?.event_id === this.memory.state.prepared?.event_id ? result.preview_url : null });
    } catch {
      let confirmed = false;
      try {
        confirmed = await this.reconcile(owner, epoch) && this.saved === snapshot;
      } catch { /* Retain local edits while storage is unavailable. */ }
      if (epoch === this.epoch && !confirmed) this.memory.persistence({ saveError: "Could not save your changes." });
    } finally {
      if (epoch === this.epoch) {
        this.inFlight = false;
        this.memory.persistence({ saving: false });
      }
    }
  }

  private async reconcile(owner: string, epoch: number) {
    const pending = this.unconfirmed;
    if (!pending) return false;
    const record = await this.read(owner, this.workspaceId);
    if (epoch !== this.epoch) return false;
    const stored = record.missing ? "" : fingerprint(record.inputs, record.selected, record.prepared);
    // Only our exact next revision confirms a lost write; unrelated changes remain conflicts.
    if (!record.missing && record.revision === pending.revision + 1 && stored === pending.snapshot) {
      this.revision = record.revision;
      this.saved = stored;
      this.stored = stored;
      this.unconfirmed = null;
      this.memory.persistence({ previewUrl: record.prepared?.event_id === this.memory.state.prepared?.event_id ? record.preview_url : null });
      return true;
    }
    if (record.revision === pending.revision && stored === this.stored) this.unconfirmed = null;
    return false;
  }

  retry() {
    if (!this.restored) return this.restore();
    this.attempted = "";
    return this.save();
  }
}
