import type { Account, Preferences } from './api';

export const accountPreferences = (account: Account): Preferences => ({
  emailEnabled: account.emailEnabled, smsEnabled: account.smsEnabled,
  magnitude: account.magnitude, nearbyOnly: account.nearbyOnly,
  latitude: account.latitude, longitude: account.longitude, distanceKm: account.distanceKm,
});
type Patch = Partial<Preferences>;
type Snapshot = { account: Account; preferences: Preferences };

// Tab-memory only. Serialized writes prevent full preference payloads from
// overwriting newer changes. Subscribers may unmount without canceling a save.
export class PreferenceSaves {
  private confirmed: Account;
  private patch: Patch = {};
  private revision = 0;
  private versions = new Map<keyof Preferences, number>();
  private listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private writing = false;
  private cancelled = false;
  private write: (preferences: Preferences) => Promise<Account>;
  private failed: (message: string) => void;
  snapshot: Snapshot;
  constructor(account: Account, write: (preferences: Preferences) => Promise<Account>, failed: (message: string) => void) {
    this.write = write;
    this.failed = failed;
    this.confirmed = account;
    this.snapshot = { account, preferences: accountPreferences(account) };
  }
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  refresh(account: Account) {
    this.confirmed = this.writing || this.versions.size
      ? { ...account, ...accountPreferences(this.confirmed) } : account;
    this.publish();
  }
  private publish() {
    this.snapshot = { account: this.confirmed, preferences: { ...accountPreferences(this.confirmed), ...this.patch } };
    this.listeners.forEach(listener => listener());
  }
  save(patch: Patch, delay = 400) {
    if (this.cancelled) return;
    const revision = ++this.revision;
    for (const key of Object.keys(patch) as (keyof Preferences)[]) this.versions.set(key, revision);
    Object.assign(this.patch, patch);
    this.publish();
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = undefined; void this.flush(); }, delay);
  }
  private async flush() {
    if (this.cancelled || this.writing || !this.versions.size) return;
    const versions = new Map(this.versions);
    const requested = { ...accountPreferences(this.confirmed), ...this.patch };
    this.writing = true;
    try {
      this.confirmed = await this.write(requested);
    } catch (error) {
      if (!this.cancelled) this.failed(error instanceof Error ? error.message : 'Your alert settings could not be saved. Try again.');
    } finally {
      // Roll back only the failed revision; keep newer user edits queued.
      for (const [key, version] of versions) {
        if (this.versions.get(key) === version) {
          this.versions.delete(key);
          delete this.patch[key];
        }
      }
      this.writing = false;
      this.publish();
      if (!this.timer) void this.flush();
    }
  }
  cancel() {
    this.cancelled = true;
    clearTimeout(this.timer);
    this.listeners.clear();
    this.versions.clear();
    this.patch = {};
  }
}

const queues = new Map<string, PreferenceSaves>();
export function preferenceSaves(identity: string, account: Account,
  write: (preferences: Preferences) => Promise<Account>, failed: (message: string) => void) {
  for (const [key, queue] of queues) {
    if (key !== identity) { queue.cancel(); queues.delete(key); }
  }
  let queue = queues.get(identity);
  if (!queue) { queue = new PreferenceSaves(account, write, failed); queues.set(identity, queue); }
  else queue.refresh(account);
  return queue;
}
export function clearPreferenceSaves() { queues.forEach(queue => queue.cancel()); queues.clear(); }
