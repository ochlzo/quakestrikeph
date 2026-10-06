import { useEffect, useMemo, useRef, useState } from "react";
import type { Map, Marker } from "maplibre-gl";
import { Label } from "react-aria-components";
import { CircleX, Earth, MapPinSearch, MapPin, Pencil, Search } from "lucide-react";
import { Empty, EmptyHeader, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent } from "../../components/ui/empty";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "../../components/ui/input-group";
import { Field, FieldLabel, FieldError } from "../../components/ui/field";
import { toast } from "../../components/ui/toast";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxItem,
  ComboboxList,
  ComboboxTrigger,
} from "../../components/ui/combobox";
import { loadMapRuntime } from "../../lib/map-runtime";
import type { Preferences } from "./api";
import "maplibre-gl/dist/maplibre-gl.css";

type Place = [string, string, number, number, string];
const normalized = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
let placeRequest: Promise<Place[]> | undefined;
function places() {
  return (placeRequest ??= fetch("/assets/accounts/philippine-places.json")
    .then((r) => {
      if (!r.ok) throw new Error("Place search unavailable");
      return r.json() as Promise<Place[]>;
    })
    .catch((error) => {
      placeRequest = undefined;
      throw error;
    }));
}
export function locationLabel(
  latitude: number | null,
  longitude: number | null,
  list: Place[],
) {
  if (latitude === null || longitude === null)
    return "Choose your alert location";
  let closest: Place | undefined,
    distance = Infinity;
  for (const p of list) {
    const d =
      (p[2] - latitude) ** 2 +
      ((p[3] - longitude) * Math.cos((latitude * Math.PI) / 180)) ** 2;
    if (d < distance) {
      distance = d;
      closest = p;
    }
  }
  return closest
    ? `${distance > 0.000001 ? "Pin near " : ""}${closest[0]}, ${closest[1]}`
    : "Your selected map pin";
}
export function usePlaces() {
  const [list, setList] = useState<Place[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    places()
      .then((x) => {
        if (active) setList(x);
      })
      .catch(() => {
        if (active)
          setError(
            "Place search is unavailable. You can still choose a map pin.",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  return { list, error };
}
function radius(
  latitude: number,
  longitude: number,
  km: number,
): GeoJSON.Feature<GeoJSON.Polygon> {
  const rad = Math.PI / 180,
    a = km / 6371.0088,
    lat = latitude * rad,
    lng = longitude * rad;
  const points: number[][] = [];
  for (let i = 0; i <= 80; i++) {
    const bearing = (i / 80) * Math.PI * 2;
    const y = Math.asin(
      Math.sin(lat) * Math.cos(a) +
        Math.cos(lat) * Math.sin(a) * Math.cos(bearing),
    );
    const x =
      lng +
      Math.atan2(
        Math.sin(bearing) * Math.sin(a) * Math.cos(lat),
        Math.cos(a) - Math.sin(lat) * Math.sin(y),
      );
    points.push([x / rad, y / rad]);
  }
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [points] },
  };
}
function fitRadius(map: Map, point: [number, number], km: number) {
  const lat = km / 111.2,
    lng = lat / Math.max(0.1, Math.cos((point[0] * Math.PI) / 180));
  map.fitBounds(
    [
      [point[1] - lng, Math.max(-85, point[0] - lat)],
      [point[1] + lng, Math.min(85, point[0] + lat)],
    ],
    { padding: 24, maxZoom: 12, duration: 0 },
  );
}

export default function LocationPicker({
  draft,
  onUse,
  onEditChange,
  validationAttempt = 0,
}: {
  draft: Preferences;
  onUse: (
    location: Pick<Preferences, "latitude" | "longitude" | "distanceKm">,
  ) => void;
  onEditChange: (location: Pick<Preferences, "latitude" | "longitude" | "distanceKm"> | null) => void;
  validationAttempt?: number;
}) {
  const { list, error: searchError } = usePlaces();
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState(false);
  const editingRef = useRef(editing);
  editingRef.current = editing;
  const locationRequest = useRef(0);
  const editButton = useRef<HTMLButtonElement>(null);
  const previousEditing = useRef(false);
  const searchAnchor = useRef<HTMLDivElement>(null);
  const [point, setPoint] = useState<[number, number] | null>(
    draft.latitude == null || draft.longitude == null
      ? null
      : [draft.latitude, draft.longitude],
  );
  const [distance, setDistance] = useState(String(draft.distanceKm ?? 50));
  useEffect(() => {
    if (editing) return;
    setPoint(draft.latitude === null || draft.longitude === null ? null : [draft.latitude, draft.longitude]);
    setDistance(String(draft.distanceKm ?? 50));
  }, [draft.latitude, draft.longitude, draft.distanceKm, editing]);
  const showMap = editing || point !== null;
  const [pinError, setPinError] = useState("");
  const [distanceError, setDistanceError] = useState("");
  const [mapError, setMapError] = useState<"runtime" | "tiles" | null>(null);
  const [mapAttempt, setMapAttempt] = useState(0);
  const [locating, setLocating] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const container = useRef<HTMLDivElement>(null),
    map = useRef<Map | null>(null),
    marker = useRef<Marker | null>(null);
  const pointRef = useRef(point);
  pointRef.current = point;
  const distanceRef = useRef(distance);
  distanceRef.current = distance;
  function validate() {
    const km = Number(distance);
    const missingPin = !point;
    const invalidDistance = !Number.isInteger(km) || km < 1 || km > 1000;
    setPinError(missingPin ? "Choose a location using search or the map." : "");
    if (missingPin) toast.add({
      id: "account-location-pin-error",
      type: "error",
      title: "Choose a location using search or the map.",
      timeout: 8000,
    });
    setDistanceError(invalidDistance ? "Enter a whole-kilometre distance from 1 to 1,000 km." : "");
    if (missingPin) searchAnchor.current?.querySelector("input")?.focus();
    else if (invalidDistance) document.getElementById("distance")?.focus();
    return !missingPin && !invalidDistance;
  }
  const previousValidation = useRef(validationAttempt);
  useEffect(() => {
    if (validationAttempt !== previousValidation.current) validate();
    previousValidation.current = validationAttempt;
  }, [validationAttempt]);
  useEffect(() => { if (point) setPinError(""); }, [point]);
  useEffect(() => {
    const changed = editing && (point?.[0] !== (draft.latitude ?? undefined) ||
      point?.[1] !== (draft.longitude ?? undefined) || Number(distance) !== (draft.distanceKm ?? 50));
    onEditChange(changed ? { latitude: point?.[0] ?? null, longitude: point?.[1] ?? null, distanceKm: Number(distance) } : null);
  }, [editing, point, distance, draft.latitude, draft.longitude, draft.distanceKm, onEditChange]);
  const matches = useMemo(() => {
    const terms = normalized(query.trim()).split(/\s+/);
    const text = normalized(query.trim());
    const rank = (p: Place) =>
      normalized(p[0]) === text
        ? 0
        : normalized(p[0]).startsWith(text)
          ? 1
          : normalized(p[0]).includes(text)
            ? 2
            : 3;
    return query.trim().length < 2
      ? []
      : list
          .map((p, index) => ({ p, index }))
          .filter(({ p }) =>
            terms.every((t) =>
              normalized(`${p[0]} ${p[1]} ${p[4]}`).includes(t),
            ),
          )
          .sort((a, b) => rank(a.p) - rank(b.p))
          .slice(0, 20);
  }, [query, list]);
  useEffect(() => {
    let active = true;
    if (!showMap) return;
    setMapError(null);
    setMapReady(false);
    loadMapRuntime()
      .then((lib) => {
        if (!active || !container.current) return;
        const initial = pointRef.current;
        const instance = new lib.Map({
          container: container.current,
          style: "https://tiles.openfreemap.org/styles/liberty",
          center: initial ? [initial[1], initial[0]] : [121, 12.4],
          zoom: initial ? 9 : 4.5,
          attributionControl: { compact: false },
        });
        map.current = instance;
        instance.addControl(
          new lib.NavigationControl({ showCompass: false }),
          "top-right",
        );
        const pin = new lib.Marker({ color: "#0e6873", draggable: editingRef.current });
        marker.current = pin;
        pin.on("dragend", () => {
          if (!editingRef.current) return;
          const position = pin.getLngLat();
          setPoint([position.lat, position.lng]);
        });
        instance.on("click", (event) => {
          if (editingRef.current) setPoint([event.lngLat.lat, event.lngLat.lng]);
        });
        instance.on("error", () =>
          { if (active) setMapError("tiles"); },
        );
        instance.on("idle", () =>
          setMapReady(
            Boolean(instance.isStyleLoaded() && instance.areTilesLoaded()),
          ),
        );
        instance.on("load", () => {
          const current = pointRef.current,
            km = Number(distanceRef.current);
          instance.addSource("alert-radius", {
            type: "geojson",
            data:
              current && Number.isFinite(km) && km >= 1 && km <= 1000
                ? radius(current[0], current[1], km)
                : { type: "FeatureCollection", features: [] },
          });
          instance.addLayer({
            id: "alert-radius-fill",
            type: "fill",
            source: "alert-radius",
            paint: { "fill-color": "#0e6873", "fill-opacity": 0.13 },
          });
          instance.addLayer({
            id: "alert-radius-line",
            type: "line",
            source: "alert-radius",
            paint: { "line-color": "#0e6873", "line-width": 2 },
          });
          refresh();
          if (current && Number.isFinite(km) && km >= 1 && km <= 1000)
            fitRadius(instance, current, km);
        });
        function refresh() {
          const current = pointRef.current;
          if (current) pin.setLngLat([current[1], current[0]]).addTo(instance);
        }
      })
      .catch(() => { if (active) setMapError("runtime"); });
    return () => {
      active = false;
      locationRequest.current++;
      marker.current?.remove();
      map.current?.remove();
      map.current = null;
    };
  }, [showMap, mapAttempt]);
  useEffect(() => {
    if (!map.current || !marker.current) return;
    if (point) marker.current.setLngLat([point[1], point[0]]).addTo(map.current);
    else marker.current.remove();
    const source = map.current.getSource("alert-radius") as
      import("maplibre-gl").GeoJSONSource | undefined;
    const km = Number(distance);
    if (!point) {
      source?.setData({ type: "FeatureCollection", features: [] });
      map.current.jumpTo({ center: [121, 12.4], zoom: 4.5 });
    } else if (source && Number.isFinite(km) && km >= 1 && km <= 1000) {
      source.setData(radius(point[0], point[1], km));
      setMapReady(false);
      fitRadius(map.current, point, km);
    }
  }, [point, distance]);
  useEffect(() => {
    marker.current?.setDraggable(editing);
    if (editing) searchAnchor.current?.querySelector("input")?.focus({ preventScroll: true });
    else if (previousEditing.current) editButton.current?.focus({ preventScroll: true });
    previousEditing.current = editing;
  }, [editing]);
  function cancel() {
    locationRequest.current++;
    setLocating(false);
    setPoint(draft.latitude == null || draft.longitude == null ? null : [draft.latitude, draft.longitude]);
    setDistance(String(draft.distanceKm ?? 50));
    setQuery("");
    setPinError("");
    setDistanceError("");
    setEditing(false);
  }
  function choose(next: [number, number]) {
    setPinError("");
    setPoint(next);
    setMapReady(false);
  }
  function locate() {
    const request = ++locationRequest.current;
    setLocating(true);
    setPinError("");
    setDistanceError("");
    if (!navigator.geolocation) {
      toast.add({
        id: "account-location-error",
        type: "error",
        title:
          "Location is unavailable on this device. Search or choose a map pin.",
        timeout: 8000,
      });
      setLocating(false);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (request !== locationRequest.current || !editingRef.current) return;
        choose([position.coords.latitude, position.coords.longitude]);
        setLocating(false);
      },
      () => {
        if (request !== locationRequest.current || !editingRef.current) return;
        toast.add({
          id: "account-location-error",
          type: "error",
          title:
            "Your location could not be used. Search for a place or choose a map pin.",
          timeout: 8000,
        });
        setLocating(false);
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
    );
  }
  function use() {
    const km = Number(distance);
    if (!validate() || !point) return;
    onUse({ latitude: point[0], longitude: point[1], distanceKm: km });
    locationRequest.current++;
    setQuery("");
    setPinError("");
    setDistanceError("");
    setEditing(false);
  }
  return (
    <>
      <div className="location-heading">
        <h2 id="form-title">{editing ? "Choose your alert location" : "Alert location"}</h2>
        {!editing && point && <Button className="secondary location-heading-edit" ref={editButton} onPress={() => setEditing(true)}>
          <Pencil aria-hidden="true" />Edit
        </Button>}
      </div>
      {editing && <p className="form-intro">
        Search for a place, then adjust the pin. Your device is only located
        when you ask.
      </p>}
      {!showMap && <Empty className="location-empty">
        <EmptyHeader>
          <EmptyMedia variant="icon"><Earth aria-hidden="true" /></EmptyMedia>
          <EmptyTitle>No alert location yet</EmptyTitle>
          <EmptyDescription>Choose a location to set your nearby alert area.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent><Button className="secondary" ref={editButton} onPress={() => setEditing(true)}>Set location</Button></EmptyContent>
      </Empty>}
      {showMap && <div className="location-map" data-map-ready={mapReady}>
        <div className="location-map-canvas" ref={container}
          aria-label={editing ? "Choose an alert location on the map" : "Your alert location on the map"} />
        {mapError && <Empty className="location-map-error" role="alert">
          <EmptyHeader>
            <EmptyMedia variant="icon"><CircleX aria-hidden="true" /></EmptyMedia>
            <EmptyTitle>{mapError === "runtime" ? "The map could not load" : "Map tiles could not load"}</EmptyTitle>
            <EmptyDescription>Search for a location or use your device location.</EmptyDescription>
          </EmptyHeader>
          {mapError === "tiles" && <EmptyContent><Button variant="outline" onPress={() => setMapAttempt(attempt => attempt + 1)}>Retry</Button></EmptyContent>}
        </Empty>}
      </div>}
      {showMap && <div className="location-controls" data-editing={editing ? "true" : undefined}>
        <Field data-invalid={pinError ? true : undefined}>
        <p
          className="location-summary"
          aria-live="polite"
          data-selected={point ? "true" : undefined}
          data-missing={pinError ? "true" : undefined}
        >
          <MapPin aria-hidden="true" />
          <span>
            <strong>{!editing && !point ? "No alert location yet" : locationLabel(point?.[0] ?? null, point?.[1] ?? null, list)}</strong>
            {!editing && point && <small className="location-view-distance">Within {distance} km</small>}
          </span>
        </p>
        </Field>
        {editing ? <>
        <div className="location-search-row">
          <Combobox
            className="location-search-combobox"
            inputValue={query}
            onInputChange={setQuery}
            allowsCustomValue
            allowsEmptyCollection
            defaultFilter={() => true}
            onSelectionChange={(key) => {
              const match = matches.find((x) => x.index === key);
              if (match) choose([match.p[2], match.p[3]]);
            }}
            menuTrigger="input"
          >
            <Field className="location-search-field-wrapper" data-invalid={searchError ? true : undefined}>
            <Label className="location-search-label">
              Search for a location
            </Label>
            <div ref={searchAnchor}>
              <InputGroup className="location-search-field">
                <InputGroupInput placeholder="Search regions, cities or municipalities"
                  aria-invalid={!!searchError} aria-describedby={searchError ? "location-search-error" : undefined} />
                <InputGroupAddon>
                  <Search aria-hidden="true" />
                </InputGroupAddon>
                <InputGroupAddon align="inline-end">
                  <ComboboxTrigger aria-label="Show matching locations" />
                </InputGroupAddon>
              </InputGroup>
            </div>
            {searchError && <FieldError id="location-search-error">{searchError}</FieldError>}
            </Field>
            <ComboboxContent anchor={searchAnchor}>
              <ComboboxList<{ p: Place; index: number }>
                items={matches}
                renderEmptyState={() => (
                  <ComboboxEmpty>
                    No matching places. Try another name or use the map.
                  </ComboboxEmpty>
                )}
              >
                {({ p, index }) => (
                  <ComboboxItem id={index} textValue={`${p[0]}, ${p[1]}`}>
                    <span>
                      {p[0]}
                      <small className="place-context">{p[1]}</small>
                    </span>
                  </ComboboxItem>
                )}
              </ComboboxList>
            </ComboboxContent>
          </Combobox>
          <Button
            className="secondary location-locate"
            onPress={locate}
            isDisabled={locating}
          >
            <MapPinSearch />
            {locating ? "Finding your location…" : "Use my location"}
          </Button>
        </div>
        <Field className="field account-form-field location-distance" data-invalid={distanceError ? true : undefined}>
          <FieldLabel htmlFor="distance">Nearby distance (km)</FieldLabel>
          <Input
            id="distance"
            aria-describedby={distanceError ? "distance-error distance-help" : "distance-help"}
            aria-invalid={!!distanceError}
            type="text"
            inputMode="numeric"
            pattern="[0-9]+"
            title="Enter a whole-kilometre distance from 1 to 1,000 km."
            value={distance}
            onChange={(e) => {
              if (/^\d*$/.test(e.target.value)) {
                setDistance(e.target.value);
                setDistanceError("");
              }
            }}
          />
          {distanceError && <FieldError id="distance-error">{distanceError}</FieldError>}
        </Field>
        <p id="distance-help" className="support location-distance-help">
          Receive alerts for earthquakes within this distance of your pin when
          “Only earthquakes near my location” is on.
        </p>
        <div className="location-actions">
          <Button className="secondary" onPress={cancel}>
            Cancel
          </Button>
          <Button className="primary" onPress={use}>
            Use this location
          </Button>
        </div>
        </> : null}
      </div>}
    </>
  );
}
