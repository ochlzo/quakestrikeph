import type { sessionRequest, SessionState } from "../../lib/api";

type Action = "start" | "end" | "cleanup";

export class SessionRequests {
  private refreshing = false;
  private mutating = false;
  private revision = 0;
  private request: typeof sessionRequest;
  private accept: (result: SessionState) => void;
  private fail: (reason: unknown) => void;
  private pending: (action: Action | null) => void;

  constructor(
    request: typeof sessionRequest,
    accept: (result: SessionState) => void,
    fail: (reason: unknown) => void,
    pending: (action: Action | null) => void,
  ) {
    this.request = request;
    this.accept = accept;
    this.fail = fail;
    this.pending = pending;
  }

  async refresh() {
    if (this.refreshing || this.mutating) return;
    this.refreshing = true;
    const revision = this.revision;
    try {
      const result = await this.request();
      if (revision === this.revision) this.accept(result);
    } catch (reason) {
      if (revision === this.revision) this.fail(reason);
    } finally { this.refreshing = false; }
  }

  async act(action: Action, owner?: string) {
    if (this.mutating) return;
    this.mutating = true;
    // An operator action supersedes every poll that started before it.
    const revision = ++this.revision;
    this.pending(action);
    try {
      const result = await this.request(action, owner);
      if (revision === this.revision) this.accept(result);
    } catch (reason) {
      if (revision === this.revision) this.fail(reason);
    } finally {
      this.mutating = false;
      if (revision === this.revision) this.pending(null);
    }
  }

  invalidate() { ++this.revision; }
}
