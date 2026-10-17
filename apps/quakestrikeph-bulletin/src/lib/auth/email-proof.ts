// This in-memory UX gate supplements Clerk's authoritative verification checks.
export class EmailProof {
  private verifiedAt: number | null = null;
  private marker: string | null = null;

  recent(marker: string, now = Date.now()) {
    if (this.marker !== marker || this.verifiedAt === null) return false;
    const age = now - this.verifiedAt;
    return age >= 0 && age < 5 * 60_000;
  }

  record(marker: string, now = Date.now()) {
    this.marker = marker;
    this.verifiedAt = now;
  }

  clear() {
    this.marker = null;
    this.verifiedAt = null;
  }
}
