/** Research prototype: statistical groups within the supplied catalog, not confirmed aftershocks. */
export interface CatalogEvent {
  eventId: string;
  /** UTC epoch seconds. Minute-precision observations must start on a minute boundary. */
  timeSeconds: number;
  timePrecision: "minute" | "second";
  latitude: number;
  longitude: number;
  depthKm: number;
  magnitude: number;
}

export interface ClusteringSettings {
  minimumMagnitude: number;
  b: number;
  fractalDimension: number;
  distanceFloorKm: number;
  eta0: number;
}

// Recorded PHIVOLCS primary experiment. Exact SEIS training provenance remains to be verified.
export const SAMPLE_SETTINGS: Readonly<ClusteringSettings> = Object.freeze({
  minimumMagnitude: 1,
  b: 0.8,
  fractalDimension: 1.58,
  distanceFloorKm: 1,
  eta0: 8.132167353718293e-5,
});

export interface Assignment {
  event: CatalogEvent;
  parentId: string | null;
  log10Eta: number | null;
  measuredDistanceKm: number | null;
  effectiveDistanceKm: number | null;
  linkType: "none" | "weak" | "strong";
  /** Local to this computation; never a durable public identifier. */
  groupId: number;
  rootEventId: string;
  groupSize: number;
}

export interface ClusteringResult {
  settings: ClusteringSettings;
  inputCount: number;
  assignments: Assignment[];
}

const EARTH_RADIUS_KM = 6371.0088;
const SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60;

function validateSettings(settings: ClusteringSettings): void {
  if (![settings.minimumMagnitude, settings.b, settings.fractalDimension,
    settings.distanceFloorKm, settings.eta0].every(Number.isFinite) ||
      settings.b <= 0 || settings.fractalDimension <= 0 ||
      settings.distanceFloorKm < 0 || settings.eta0 <= 0) {
    throw new Error("Clustering settings must be finite, with positive b, dimension, and threshold, and a nonnegative floor.");
  }
}

function validateEvent(event: CatalogEvent): void {
  // ASCII IDs preserve C++ byte ordering and JavaScript ordering, without locale-dependent comparisons.
  if (typeof event.eventId !== "string" || !/^[A-Za-z0-9_.:-]+$/.test(event.eventId) ||
      !Number.isSafeInteger(event.timeSeconds) || Math.abs(event.timeSeconds) > 8640000000000 ||
      ![event.latitude, event.longitude, event.depthKm, event.magnitude].every(Number.isFinite) ||
      Math.abs(event.latitude) > 90 || Math.abs(event.longitude) > 180 ||
      !["minute", "second"].includes(event.timePrecision) ||
      (event.timePrecision === "minute" && event.timeSeconds % 60 !== 0)) {
    throw new Error(`Invalid catalog event: ${event.eventId}`);
  }
}

function knownEarlier(parent: CatalogEvent, child: CatalogEvent): boolean {
  return parent.timeSeconds < child.timeSeconds &&
    ((parent.timePrecision === "second" && child.timePrecision === "second") ||
      Math.floor(parent.timeSeconds / 60) !== Math.floor(child.timeSeconds / 60));
}

/** Exact all-earlier search: no distance or lookback pruning. Work grows quadratically. */
export function clusterCatalog(
  input: readonly CatalogEvent[],
  settings: ClusteringSettings = SAMPLE_SETTINGS,
): ClusteringResult {
  validateSettings(settings);
  const ids = new Set<string>();
  for (const event of input) {
    validateEvent(event);
    if (ids.has(event.eventId)) throw new Error(`Duplicate event identity: ${event.eventId}`);
    ids.add(event.eventId);
  }

  const events = input.filter(event => event.magnitude >= settings.minimumMagnitude)
    .map(event => ({ ...event }))
    .sort((a, b) => a.timeSeconds - b.timeSeconds ||
      (a.eventId < b.eventId ? -1 : a.eventId > b.eventId ? 1 : 0));
  const terms = events.map(event => ({
    latitude: event.latitude * Math.PI / 180,
    longitude: event.longitude * Math.PI / 180,
    cosineLatitude: Math.cos(event.latitude * Math.PI / 180),
    magnitudeTerm: settings.b * event.magnitude,
  }));
  const threshold = Math.log10(settings.eta0);
  const assignments: Assignment[] = [];
  const groups = new Map<string, { id: number; size: number }>();

  for (let child = 0; child < events.length; child++) {
    let bestParent = -1;
    let bestScore = Infinity;
    let bestDistance: number | null = null;
    let bestEffective: number | null = null;
    for (let candidate = 0; candidate < child; candidate++) {
      if (!knownEarlier(events[candidate], events[child])) continue;
      const sineLatitude = Math.sin((terms[child].latitude - terms[candidate].latitude) / 2);
      const sineLongitude = Math.sin((terms[child].longitude - terms[candidate].longitude) / 2);
      const haversine = sineLatitude * sineLatitude +
        terms[candidate].cosineLatitude * terms[child].cosineLatitude * sineLongitude * sineLongitude;
      const measured = 2 * EARTH_RADIUS_KM * Math.asin(Math.sqrt(Math.max(0, Math.min(1, haversine))));
      const effective = Math.max(measured, settings.distanceFloorKm);
      const years = (events[child].timeSeconds - events[candidate].timeSeconds) / SECONDS_PER_YEAR;
      const score = effective === 0 ? -Infinity :
        Math.log10(years) + settings.fractalDimension * Math.log10(effective) - terms[candidate].magnitudeTerm;
      // Keep the first candidate on an exact tie, as the corrected C++ implementation does.
      if (score < bestScore) {
        bestParent = candidate;
        bestScore = score;
        bestDistance = measured;
        bestEffective = effective;
      }
    }

    const retained = bestParent >= 0 && bestScore < threshold;
    // One strictly earlier parent forms a forest. Inheriting its root reproduces connected components.
    const root = retained ? assignments[bestParent].rootEventId : events[child].eventId;
    let group = groups.get(root);
    if (!group) {
      group = { id: groups.size + 1, size: 0 };
      groups.set(root, group);
    }
    group.size++;
    assignments.push({
      event: events[child], parentId: bestParent < 0 ? null : events[bestParent].eventId,
      log10Eta: bestParent < 0 ? null : bestScore,
      measuredDistanceKm: bestDistance, effectiveDistanceKm: bestEffective,
      linkType: bestParent < 0 ? "none" : retained ? "strong" : "weak",
      groupId: group.id, rootEventId: root, groupSize: 0,
    });
  }
  for (const assignment of assignments) assignment.groupSize = groups.get(assignment.rootEventId)!.size;
  return { settings: { ...settings }, inputCount: input.length, assignments };
}

/** Later M1+ members of the anchor's group; end inclusive. No radius or retrospective-role filter. */
export function windowEvents(result: ClusteringResult, anchorId: string, elapsedHours = 24): Assignment[] {
  if (!Number.isFinite(elapsedHours) || elapsedHours < 0 || elapsedHours > 24) {
    throw new Error("Playback hours must be between 0 and 24.");
  }
  const anchor = result.assignments.find(row => row.event.eventId === anchorId);
  if (!anchor) throw new Error(`Anchor is absent from the supplied M1+ catalog: ${anchorId}`);
  return result.assignments.filter(row => row.rootEventId === anchor.rootEventId && row.event.magnitude >= 1 &&
    knownEarlier(anchor.event, row.event) && row.event.timeSeconds <= anchor.event.timeSeconds + elapsedHours * 3600);
}
