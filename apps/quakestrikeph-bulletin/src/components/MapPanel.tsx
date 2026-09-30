import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Layers3, LocateFixed, Minus, Plus } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import type { GeoJSONSource, Map as MapLibreMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { Earthquake, Forecast } from "../lib/events";

type Props = {
  events: Earthquake[];
  selectedId: string | null;
  focusRequest: number;
  forecast: Forecast | null;
  forecastStatus: "loading" | "ready" | "error";
  onSelect: (id: string) => void;
};

const emptyRadius = { type: "FeatureCollection" as const, features: [] };
const earthRadiusKm = 6371.0088;
const markerButtonClass = buttonVariants({ variant: "ghost", size: "icon" });
const philippinesBounds: [[number, number], [number, number]] = [
  [110, 0],
  [135, 26],
];

// A great-circle destination keeps the drawn radius in kilometres at any latitude.
function pointAtDistance(
  lng: number,
  lat: number,
  distanceKm: number,
  bearing: number,
): [number, number] {
  const latitude = (lat * Math.PI) / 180;
  const longitude = (lng * Math.PI) / 180;
  const angle = distanceKm / earthRadiusKm;
  const nextLatitude = Math.asin(
    Math.sin(latitude) * Math.cos(angle) +
      Math.cos(latitude) * Math.sin(angle) * Math.cos(bearing),
  );
  const nextLongitude =
    longitude +
    Math.atan2(
      Math.sin(bearing) * Math.sin(angle) * Math.cos(latitude),
      Math.cos(angle) - Math.sin(latitude) * Math.sin(nextLatitude),
    );
  return [
    (((nextLongitude * 180) / Math.PI + 540) % 360) - 180,
    (nextLatitude * 180) / Math.PI,
  ];
}

function radiusCoordinates(event: Earthquake, radiusKm: number) {
  return Array.from({ length: 97 }, (_, index) =>
    pointAtDistance(
      event.longitude,
      event.latitude,
      radiusKm,
      (index * 2 * Math.PI) / 96,
    ),
  );
}

function chance(value: number) {
  if (value > 0 && value < 0.005) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function forecastEnd(value: string) {
  return `${new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(value))} PHT`;
}

const magnitudeBands = [
  { minimum: 6, className: "mag-6", label: "M6.0+" },
  { minimum: 5, className: "mag-5", label: "M5.0–<6.0" },
  { minimum: 4, className: "mag-4", label: "M4.0–<5.0" },
  { minimum: 3, className: "mag-3", label: "M3.0–<4.0" },
  { minimum: -Infinity, className: "mag-under-3", label: "Below M3.0" },
] as const;

function magnitudeBand(value: number) {
  return (
    magnitudeBands.find((band) => value >= band.minimum) ??
    magnitudeBands.at(-1)!
  );
}

function set3DInteractions(instance: MapLibreMap, enabled: boolean) {
  instance.setMaxPitch(enabled ? 60 : 0);
  if (enabled) {
    instance.dragRotate.enable();
    instance.touchPitch.enable();
    instance.touchZoomRotate.enableRotation();
    instance.keyboard.enableRotation();
  } else {
    instance.dragRotate.disable();
    instance.touchPitch.disable();
    instance.touchZoomRotate.disableRotation();
    instance.keyboard.disableRotation();
  }
}

export default function MapPanel({
  events,
  selectedId,
  focusRequest,
  forecast,
  forecastStatus,
  onSelect,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const previousSelectedId = useRef<string | null>(null);
  const annotationMarker = useRef<Marker | null>(null);
  const onSelectRef = useRef(onSelect);
  const selectedIdRef = useRef(selectedId);
  const focusRequestRef = useRef(focusRequest);
  const [annotationHost, setAnnotationHost] = useState<HTMLDivElement | null>(
    null,
  );
  const [dismissedForecast, setDismissedForecast] = useState<{
    id: string;
    focusRequest: number;
  } | null>(null);
  const [terrain, setTerrain] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  onSelectRef.current = onSelect;
  selectedIdRef.current = selectedId;
  focusRequestRef.current = focusRequest;
  const selectedEvent = events.find((event) => event.eventId === selectedId);
  const forecastDismissed =
    dismissedForecast?.id === selectedId &&
    dismissedForecast.focusRequest === focusRequest;
  const reportedRadiusKm =
    forecastStatus === "ready" &&
    forecast &&
    forecast.activityRadiusMedianKm24h !== null &&
    Number.isFinite(forecast.activityRadiusMedianKm24h) &&
    forecast.activityRadiusMedianKm24h >= 0
      ? forecast.activityRadiusMedianKm24h
      : null;
  const radiusKm =
    reportedRadiusKm !== null && reportedRadiusKm > 0 ? reportedRadiusKm : null;

  useEffect(() => {
    if (!container.current) return;
    let disposed = false;
    const attributionListeners = new AbortController();
    import("maplibre-gl")
      .then((ml) => {
        if (disposed || !container.current) return;
        ml.setWorkerUrl(workerUrl);
        const compact = window.matchMedia("(max-width: 600px)").matches;
        const instance = new ml.Map({
          container: container.current,
          attributionControl: {
            compact: true,
            // stop adding custom attributions
          },
          style: "https://tiles.openfreemap.org/styles/positron",
          maxBounds: philippinesBounds,
          minZoom: 3.25,
          center: compact ? [123.1, 11.7] : [123.3, 10.8],
          zoom: compact ? 4.15 : 5.55,
          pitch: 0,
          bearing: 0,
        });
        set3DInteractions(instance, false);
        map.current = instance;
        instance.on("click", (event) => {
          const target = event.originalEvent.target;
          if (
            !selectedIdRef.current ||
            (target instanceof Element &&
              target.closest(
                ".quake-marker, .forecast-map-host, .maplibregl-control-container",
              ))
          )
            return;
          setDismissedForecast({
            id: selectedIdRef.current,
            focusRequest: focusRequestRef.current,
          });
        });
        // Attach to this map instance, including maps recreated by Fast Refresh.
        const attribution = instance
          .getContainer()
          .querySelector<HTMLDetailsElement>(".maplibregl-ctrl-attrib");
        if (attribution) {
          attribution.classList.remove("maplibregl-compact-show");
          attribution.open = false;
          const closeUnlessInside = (target: EventTarget | null) => {
            if (target instanceof Node && attribution.contains(target)) return;
            attribution.classList.remove("maplibregl-compact-show");
            attribution.open = false;
          };
          document.addEventListener(
            "pointerdown",
            (event) => closeUnlessInside(event.target),
            { capture: true, signal: attributionListeners.signal },
          );
          attribution.addEventListener(
            "focusout",
            (event) => closeUnlessInside(event.relatedTarget),
            { signal: attributionListeners.signal },
          );
        }
        instance.on("load", () => {
          if (disposed) return;
          for (const layer of instance.getStyle().layers) {
            if (layer.type === "fill" && /water|ocean|sea/i.test(layer.id)) {
              instance.setPaintProperty(layer.id, "fill-color", "#a4c6d3");
            }
          }
          // geoBoundaries gbOpen PHL ADM0, simplified OCHA/NAMRIA geometry;
          // islets under 0.5 km² are omitted to avoid dark dots at regional zoom.
          // This avoids the internal edges of OpenMapTiles water polygons.
          instance.addSource("coastline", {
            type: "geojson",
            data: "/assets/map/philippines-coastline.geojson",
          });
          instance.addLayer(
            {
              id: "coastline-outline",
              type: "line",
              source: "coastline",
              layout: { "line-join": "round", "line-cap": "round" },
              paint: { "line-color": "#163c61", "line-width": 1.5 },
            },
            instance.getStyle().layers.find((layer) => layer.type === "symbol")
              ?.id,
          );
          instance.addSource("terrain", {
            type: "raster-dem",
            tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
            tileSize: 512,
            maxzoom: 12,
            encoding: "terrarium",
          });
          instance.addLayer({
            id: "terrain-shade",
            type: "hillshade",
            source: "terrain",
            layout: { visibility: "none" },
            paint: {
              "hillshade-shadow-color": "#3e6c6d",
              "hillshade-highlight-color": "#ffffff",
              "hillshade-accent-color": "#719896",
            },
          });
          instance.addSource("forecast-radius", {
            type: "geojson",
            data: emptyRadius,
          });
          instance.addLayer({
            id: "forecast-radius-fill",
            type: "fill",
            source: "forecast-radius",
            paint: { "fill-color": "#117e89", "fill-opacity": 0.14 },
          });
          instance.addLayer({
            id: "forecast-radius-outline",
            type: "line",
            source: "forecast-radius",
            paint: {
              "line-color": "#096975",
              "line-width": 2,
              "line-dasharray": [2, 2],
            },
          });
          instance.addControl(
            new ml.ScaleControl({ maxWidth: 192, unit: "metric" }),
            "bottom-left",
          );
          setMapReady(true);
        });
      })
      .catch(() => setMapReady(false));
    return () => {
      disposed = true;
      attributionListeners.abort();
      markers.current.forEach((marker) => marker.remove());
      markers.current.clear();
      annotationMarker.current?.remove();
      annotationMarker.current = null;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !map.current) return;
    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || !map.current) return;
      const eventIds = new Set(events.map((event) => event.eventId));
      for (const [id, marker] of markers.current) {
        if (eventIds.has(id)) continue;
        marker.remove();
        markers.current.delete(id);
      }
      for (const event of events) {
        const band = magnitudeBand(event.magnitude);
        const existing = markers.current.get(event.eventId);
        if (existing) {
          const position = existing.getLngLat();
          if (
            position.lng !== event.longitude ||
            position.lat !== event.latitude
          ) {
            existing.setLngLat([event.longitude, event.latitude]);
          }
          const button = existing.getElement();
          button.classList.remove(
            ...magnitudeBands.map((item) => item.className),
          );
          button.classList.add(band.className);
          button.setAttribute(
            "aria-label",
            `Magnitude ${event.magnitude.toFixed(1)}, ${band.label}, ${event.locationDescription}`,
          );
          button.title = `M${event.magnitude.toFixed(1)} · ${event.locationDescription}`;
          continue;
        }
        const button = document.createElement("button");
        button.type = "button";
        button.className = `${markerButtonClass} quake-marker ${band.className} ${event.eventId === selectedIdRef.current ? "is-selected" : ""}`;
        button.setAttribute(
          "aria-label",
          `Magnitude ${event.magnitude.toFixed(1)}, ${band.label}, ${event.locationDescription}`,
        );
        button.title = `M${event.magnitude.toFixed(1)} · ${event.locationDescription}`;
        button.addEventListener("click", () =>
          onSelectRef.current(event.eventId),
        );
        markers.current.set(
          event.eventId,
          new ml.Marker({ element: button, anchor: "center" })
            .setLngLat([event.longitude, event.latitude])
            .addTo(map.current!),
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [events, mapReady]);

  useEffect(() => {
    if (previousSelectedId.current !== selectedId) {
      if (previousSelectedId.current) {
        markers.current
          .get(previousSelectedId.current)
          ?.getElement()
          .classList.remove("is-selected");
      }
      previousSelectedId.current = selectedId;
    }
    if (selectedId)
      markers.current
        .get(selectedId)
        ?.getElement()
        .classList.add("is-selected");
  }, [events, selectedId, mapReady]);

  useEffect(() => {
    const instance = map.current;
    if (!mapReady || !instance) return;
    const source = instance.getSource("forecast-radius") as
      GeoJSONSource | undefined;
    annotationMarker.current?.remove();
    annotationMarker.current = null;
    setAnnotationHost(null);
    if (!selectedEvent || forecastDismissed) {
      void source?.setData(emptyRadius);
      return;
    }

    const coordinates = radiusKm
      ? radiusCoordinates(selectedEvent, radiusKm)
      : null;
    void source?.setData(
      coordinates
        ? {
            type: "Feature" as const,
            properties: {},
            geometry: { type: "Polygon" as const, coordinates: [coordinates] },
          }
        : emptyRadius,
    );

    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || map.current !== instance) return;
      const width = instance.getContainer().clientWidth;
      const stacked = width < 280;
      const annotationPoint = radiusKm
        ? pointAtDistance(
            selectedEvent.longitude,
            selectedEvent.latitude,
            radiusKm,
            stacked ? 0 : Math.PI / 2,
          )
        : ([selectedEvent.longitude, selectedEvent.latitude] as [
            number,
            number,
          ]);
      const host = document.createElement("div");
      host.className = "forecast-map-host";
      annotationMarker.current = new ml.Marker({
        element: host,
        anchor: stacked ? "bottom" : "left",
        offset: stacked ? [0, -12] : [12, width < 340 ? -14 : 0],
      })
        .setLngLat(annotationPoint)
        .addTo(instance);
      setAnnotationHost(host);

      if (forecastStatus === "loading") return;
      const duration = window.matchMedia("(prefers-reduced-motion: reduce)")
        .matches
        ? 0
        : 700;
      const zoom = Math.min(instance.getZoom() + 0.85, stacked ? 6.8 : 7.3);
      if (!coordinates) {
        instance.flyTo({
          center: [selectedEvent.longitude, selectedEvent.latitude],
          zoom,
          offset: stacked ? [0, 55] : [-90, 0],
          duration,
        });
        return;
      }
      const bounds = coordinates.reduce(
        (result, point) => result.extend(point),
        new ml.LngLatBounds(coordinates[0], coordinates[0]),
      );
      const height = instance.getContainer().clientHeight;
      instance.fitBounds(bounds, {
        padding: stacked
          ? {
              top: Math.min(145, height * 0.34),
              right: 38,
              bottom: 48,
              left: 38,
            }
          : {
              top: Math.min(70, height * 0.18),
              right:
                width < 340 ? 154 : Math.min(230, Math.max(188, width * 0.42)),
              bottom: Math.min(70, height * 0.18),
              left: Math.min(52, width * 0.12),
            },
        maxZoom: zoom,
        duration,
      });
    });
    return () => {
      cancelled = true;
      annotationMarker.current?.remove();
      annotationMarker.current = null;
    };
  }, [
    mapReady,
    selectedEvent,
    radiusKm,
    forecastStatus,
    focusRequest,
    forecastDismissed,
  ]);

  function zoom(delta: number) {
    map.current?.zoomTo(map.current.getZoom() + delta, { duration: 350 });
  }
  function recenter() {
    const compact = window.matchMedia("(max-width: 600px)").matches;
    map.current?.flyTo({
      center: compact ? [123.1, 11.7] : [123.3, 10.8],
      zoom: compact ? 4.15 : 5.55,
      pitch: terrain ? (compact ? 20 : 42) : 0,
      duration: 700,
    });
  }
  function toggleTerrain() {
    if (!mapReady || !map.current) return;
    const next = !terrain;
    map.current.setTerrain(
      next ? { source: "terrain", exaggeration: 1.3 } : null,
    );
    map.current.setLayoutProperty(
      "terrain-shade",
      "visibility",
      next ? "visible" : "none",
    );
    set3DInteractions(map.current, next);
    map.current.easeTo({
      pitch: next
        ? window.matchMedia("(max-width: 600px)").matches
          ? 20
          : 42
        : 0,
      bearing: next ? map.current.getBearing() : 0,
      duration: 500,
    });
    setTerrain(next);
  }

  return (
    <section
      className="map-panel"
      aria-label="Earthquakes on the Philippine map"
    >
      <img
        className="map-plate"
        src="/assets/plates/relief-map.webp"
        alt=""
        fetchPriority="high"
      />
      <div className="map-canvas" ref={container} />
      {annotationHost &&
        selectedEvent &&
        !forecastDismissed &&
        createPortal(
          <div
            className="forecast-map-annotation"
            role="status"
            aria-live="polite"
          >
            {forecastStatus === "loading" ? (
              <span>Loading forecast…</span>
            ) : forecastStatus === "error" ? (
              <span>Forecast details are unavailable right now.</span>
            ) : forecast ? (
              <>
                <strong className="forecast-map-radius">
                  {reportedRadiusKm === null
                    ? "Activity radius unavailable"
                    : `${Math.round(reportedRadiusKm)} km estimated activity radius`}
                </strong>
                <span className="forecast-map-period">
                  24-hour forecast {forecast.expired ? "ended" : "through"}{" "}
                  {forecastEnd(forecast.windowEnd)}
                </span>
                <span
                  className="forecast-map-occurrence"
                  aria-label={`${chance(forecast.probabilityM1Plus24h)} chance of at least one further earthquake of magnitude 1.0 or higher`}
                >
                  <strong>
                    {chance(forecast.probabilityM1Plus24h)} chance
                  </strong>{" "}
                  of at least one further M1.0+ earthquake
                </span>
                {radiusKm !== null && (
                  <small>
                    The circle shows distance, not a safety boundary or chance
                    area.
                  </small>
                )}
              </>
            ) : (
              <span>No forecast is available for this earthquake.</span>
            )}
          </div>,
          annotationHost,
        )}
      <Button
        variant="outline"
        className="terrain-button"
        onPress={toggleTerrain}
        isDisabled={!mapReady}
        aria-pressed={terrain}
        aria-label="3D terrain"
      >
        <Layers3 size={18} aria-hidden="true" />
        <span className="terrain-label">3D terrain</span>
        <span className="terrain-switch" aria-hidden="true">
          <span className="terrain-thumb" />
        </span>
      </Button>
      <div className="map-tools">
        <Button
          variant="outline"
          size="icon"
          onPress={() => zoom(1)}
          aria-label="Zoom in"
        >
          <Plus aria-hidden="true" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onPress={() => zoom(-1)}
          aria-label="Zoom out"
        >
          <Minus aria-hidden="true" />
        </Button>
        <Button
          variant="outline"
          size="icon"
          onPress={recenter}
          aria-label="Show the Philippines"
        >
          <LocateFixed aria-hidden="true" />
        </Button>
      </div>
      <div className="map-legend" aria-label="Magnitude legend">
        <strong>Magnitude (M)</strong>
        {magnitudeBands.map((band) => (
          <span key={band.className}>
            <i className={`dot ${band.className}`} aria-hidden="true" />
            {band.label}
          </span>
        ))}
      </div>
    </section>
  );
}
