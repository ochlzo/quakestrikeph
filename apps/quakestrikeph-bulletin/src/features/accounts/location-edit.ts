import type { Preferences } from './api';

export type AlertLocation = Pick<Preferences, 'latitude' | 'longitude' | 'distanceKm'>;
type Point = [number, number];
type DeviceLocation = (success: (point: Point) => void, failure: (message: string) => void) => void;
type Errors = { pin: string; distance: string; focus: 'pin' | 'distance' | null };
type Snapshot = {
  editing: boolean; point: Point | null; distance: string; dirty: boolean;
  locating: boolean; committing: boolean; errors: Errors;
};
const emptyErrors = (): Errors => ({ pin: '', distance: '', focus: null });
const savedPoint = (saved: AlertLocation): Point | null =>
  saved.latitude === null || saved.longitude === null ? null : [saved.latitude, saved.longitude];

export const browserLocation: DeviceLocation = (success, failure) => {
  if (!navigator.geolocation) {
    failure('Location is unavailable on this device. Search or choose a map pin.');
    return;
  }
  navigator.geolocation.getCurrentPosition(
    position => success([position.coords.latitude, position.coords.longitude]),
    () => failure('Your location could not be used. Search for a place or choose a map pin.'),
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
  );
};

// One screen edit; saved settings may refresh without replacing unfinished input.
export class LocationEdit {
  private saved: AlertLocation;
  private device: DeviceLocation;
  private request = 0;
  private listeners = new Set<() => void>();
  snapshot: Snapshot;

  constructor(saved: AlertLocation, device: DeviceLocation) {
    this.saved = { ...saved };
    this.device = device;
    this.snapshot = {
      editing: false, point: savedPoint(saved), distance: String(saved.distanceKm ?? 50),
      dirty: false, locating: false, committing: false, errors: emptyErrors(),
    };
  }
  getSnapshot = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };
  private publish(patch: Partial<Snapshot>) {
    const next = { ...this.snapshot, ...patch };
    next.dirty = next.editing && (next.point?.[0] !== (this.saved.latitude ?? undefined) ||
      next.point?.[1] !== (this.saved.longitude ?? undefined) || Number(next.distance) !== (this.saved.distanceKm ?? 50));
    this.snapshot = next;
    this.listeners.forEach(listener => listener());
  }
  refresh(saved: AlertLocation) {
    this.saved = { ...saved };
    this.publish(this.snapshot.editing ? {} : {
      point: savedPoint(saved), distance: String(saved.distanceKm ?? 50),
    });
  }
  begin() { this.publish({ editing: true }); }
  choose(point: Point) {
    if (!this.snapshot.editing || this.snapshot.committing) return;
    this.request++;
    this.publish({ point: [...point], locating: false,
      errors: { ...this.snapshot.errors, pin: '', focus: null } });
  }
  setDistance(distance: string) {
    if (!this.snapshot.editing || this.snapshot.committing || !/^\d*$/.test(distance)) return;
    this.publish({ distance, errors: { ...this.snapshot.errors, distance: '', focus: null } });
  }
  cancel() {
    this.request++;
    this.publish({ editing: false, point: savedPoint(this.saved), distance: String(this.saved.distanceKm ?? 50),
      locating: false, committing: false, errors: emptyErrors() });
  }
  commit(mode: 'immediate' | 'confirmed'): AlertLocation | null {
    if (!this.snapshot.editing || this.snapshot.committing) return null;
    const { point, distance } = this.snapshot;
    const km = Number(distance);
    const missingPin = !point;
    const invalidDistance = !Number.isInteger(km) || km < 1 || km > 1000;
    if (missingPin || invalidDistance) {
      this.publish({ errors: {
        pin: missingPin ? 'Choose a location using search or the map.' : '',
        distance: invalidDistance ? 'Enter a whole-kilometre distance from 1 to 1,000 km.' : '',
        focus: missingPin ? 'pin' : 'distance',
      } });
      return null;
    }
    this.request++;
    this.publish({ editing: mode === 'confirmed', committing: mode === 'confirmed',
      locating: false, errors: emptyErrors() });
    return { latitude: point![0], longitude: point![1], distanceKm: km };
  }
  complete(saved: boolean) {
    if (!this.snapshot.committing) return;
    if (saved) this.cancel();
    else this.publish({ committing: false });
  }
  locate(failed: (message: string) => void) {
    if (!this.snapshot.editing || this.snapshot.committing || this.snapshot.locating) return;
    const request = ++this.request;
    this.publish({ locating: true, errors: emptyErrors() });
    const eligible = () => request === this.request && this.snapshot.editing && !this.snapshot.committing;
    this.device(point => {
      if (eligible()) this.choose(point);
    }, message => {
      if (!eligible()) return;
      this.publish({ locating: false });
      failed(message);
    });
  }
  dispose() { this.cancel(); }
}
