import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import type { Map, Marker } from "maplibre-gl";
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
import type { AlertLocation, LocationEdit } from "./location-edit";
import { locationLabel, usePlaces, type Place } from "./location-places";
import "maplibre-gl/dist/maplibre-gl.css";

const normalized = (s: string) =>
  s
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
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

export default function LocationPicker({ edit, onUse }: {
  edit: LocationEdit;
  onUse: (location: AlertLocation) => void;
}) {
  const { list, error: searchError } = usePlaces();
  const state = useSyncExternalStore(edit.subscribe, edit.getSnapshot, edit.getSnapshot);
  const { editing, point, distance, locating, errors } = state;
  const pinError = errors.pin, distanceError = errors.distance;
  const [query, setQuery] = useState("");
  const editingRef = useRef(editing);
  editingRef.current = editing;
  const editButton = useRef<HTMLButtonElement>(null);
  const previousEditing = useRef(false);
  const searchAnchor = useRef<HTMLDivElement>(null);
  const showMap = editing || point !== null;
  const [mapError, setMapError] = useState<"runtime" | "tiles" | null>(null);
  const [mapAttempt, setMapAttempt] = useState(0);
  const [mapReady, setMapReady] = useState(false);
  const container = useRef<HTMLDivElement>(null),
    map = useRef<Map | null>(null),
    marker = useRef<Marker | null>(null);
  const pointRef = useRef(point);
  pointRef.current = point;
  const distanceRef = useRef(distance);
  distanceRef.current = distance;
  useEffect(() => {
    if (!errors.focus) return;
    if (errors.pin) toast.add({
      id: "account-location-pin-error", type: "error", title: errors.pin, timeout: 8000,
    });
    if (errors.focus === "pin") searchAnchor.current?.querySelector("input")?.focus();
    else document.getElementById("distance")?.focus();
  }, [errors]);
  useEffect(() => { if (!editing) setQuery(""); }, [editing]);
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
          choose([position.lat, position.lng]);
        });
        instance.on("click", (event) => {
          if (editingRef.current) choose([event.lngLat.lat, event.lngLat.lng]);
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
  function cancel() { edit.cancel(); }
  function choose(next: [number, number]) {
    edit.choose(next);
    setMapReady(false);
  }
  function locate() {
    edit.locate(message => toast.add({
      id: "account-location-error", type: "error", title: message, timeout: 8000,
    }));
  }
  function use() {
    const location = edit.commit('immediate');
    if (location) onUse(location);
  }
  return (
    <>
      <div className="location-heading">
        <h2 id="form-title">{editing ? "Choose your alert location" : "Alert location"}</h2>
        {!editing && point && <Button className="secondary location-heading-edit" ref={editButton} onPress={() => edit.begin()}>
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
        <EmptyContent><Button className="secondary" ref={editButton} onPress={() => edit.begin()}>Set location</Button></EmptyContent>
      </Empty>}
      {editing && <div className="location-search">
        <div className="location-search-row">
          <Combobox
            className="location-search-combobox"
            aria-label="Search for a location"
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
                  <ComboboxEmpty className="location-search-empty">
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
      </div>}
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
            onChange={(e) => edit.setDistance(e.target.value)}
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
