import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleQuestionMark, LocateFixed, Minus, Plus } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import type { GeoJSONSource, Map as MapLibreMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Earthquake, Forecast } from "../lib/events";
import { occurrenceRelativeTo } from "../lib/events";
import ForecastOverview, { forecastRadiusKm } from "./ForecastOverview";
import { magnitudeBand, magnitudeBands } from "../lib/magnitude";
import { addLandmarkLabels } from "../lib/map-landmarks";
import { cleanMapStyle, transformLabelRequest } from "../lib/map-labels";
import { loadMapRuntime } from "../lib/map-runtime";
import { toast } from "./ui/toast";

type Props = {
  events: Earthquake[];
  selectedId: string | null;
  focusRequest: number;
  forecast: Forecast | null;
  forecastStatus: "loading" | "ready" | "error";
  onSelect: (id: string) => void;
  showForecastOverview?: boolean;
  overviewInDrawer?: boolean;
  forecastAnchor?: Earthquake;
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

function set3DInteractions(instance: MapLibreMap, enabled: boolean) {
  instance.setMaxPitch(enabled ? 85 : 0);
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

function applyTerrain(instance: MapLibreMap, enabled: boolean) {
  instance.setTerrain(
    enabled ? { source: "terrain", exaggeration: 1.3 } : null,
  );
  instance.setSky({
    "sky-color": enabled ? "#eaf2f8" : "transparent",
    "horizon-color": enabled ? "#ffffff" : "transparent",
    "sky-horizon-blend": 0.35,
    "fog-color": "transparent",
    "fog-ground-blend": 1,
    "atmosphere-blend": 0,
  });
  set3DInteractions(instance, enabled);
}

export default function MapPanel({
  events,
  selectedId,
  focusRequest,
  forecast,
  forecastStatus,
  onSelect,
  showForecastOverview = true,
  overviewInDrawer = false,
  forecastAnchor,
}: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const markers = useRef(new Map<string, Marker>());
  const previousSelectedId = useRef<string | null>(null);
  const annotationMarker = useRef<Marker | null>(null);
  const observationPopup = useRef<{ id: string; popup: Popup } | null>(null);
  const onSelectRef = useRef(onSelect);
  const selectedIdRef = useRef(selectedId);
  const [annotationHost, setAnnotationHost] = useState<HTMLDivElement | null>(
    null,
  );
  const [dismissedForecast, setDismissedForecast] = useState<{
    id: string;
    focusRequest: number;
  } | null>(null);
  const legendControl = useRef<HTMLDivElement>(null);
  const [legendOpen, setLegendOpen] = useState(true);
  const [terrain, setTerrain] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  onSelectRef.current = onSelect;
  selectedIdRef.current = selectedId;
  const selectedEvent = events.find((event) => event.eventId === selectedId);
  const areaEvent = forecastAnchor ?? selectedEvent;
  const forecastDismissed =
    !overviewInDrawer && dismissedForecast?.id === selectedId &&
    dismissedForecast.focusRequest === focusRequest;
  const reportedRadiusKm =
    forecastStatus === "ready" ? forecastRadiusKm(forecast) : null;
  const radiusKm =
    reportedRadiusKm !== null && reportedRadiusKm > 0 ? reportedRadiusKm : null;

  useEffect(() => {
    if (!legendOpen) return;
    const listeners = new AbortController();
    document.addEventListener(
      "pointerdown",
      (event) => {
        if (
          event.target instanceof Node &&
          !legendControl.current?.contains(event.target)
        ) {
          setLegendOpen(false);
        }
      },
      { capture: true, signal: listeners.signal },
    );
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape") setLegendOpen(false);
      },
      { signal: listeners.signal },
    );
    return () => listeners.abort();
  }, [legendOpen]);

  useEffect(() => {
    if (!container.current) return;
    setMapReady(false);
    setTerrain(false);
    let disposed = false;
    const attributionListeners = new AbortController();
    loadMapRuntime()
      .then((ml) => {
        if (disposed || !container.current) return;
        const compact = window.matchMedia("(max-width: 600px)").matches;
        const instance = new ml.Map({
          container: container.current,
          trackResize: false,
          attributionControl: { compact: false },
          transformRequest: transformLabelRequest,
          maxBounds: philippinesBounds,
          minZoom: 3.25,
          center: forecastAnchor
            ? [forecastAnchor.longitude, forecastAnchor.latitude]
            : compact
              ? [123.1, 11.7]
              : [123.3, 10.8],
          zoom: forecastAnchor ? 7.2 : compact ? 4.15 : 5.55,
          pitch: 0,
          maxPitch: 0,
          bearing: 0,
        });
        set3DInteractions(instance, false);
        map.current = instance;
        let reportedError = false;
        instance.on("error", () => {
          if (disposed || reportedError) return;
          reportedError = true;
          toast.add({
            id: "map-load-error",
            type: "error",
            title: "Some map details could not be loaded.",
            description: "Reload the page to try again.",
          });
        });
        instance.on("dragstart", () => setLegendOpen(false));
        instance.on("load", () => {
          if (disposed) return;
          const nativeWaterColor = instance.getPaintProperty(
            "water",
            "fill-color",
          );
          if (typeof nativeWaterColor === "string") {
            instance.setPaintProperty("water", "fill-color", [
              "case",
              ["==", ["get", "class"], "ocean"],
              "#74A9D9",
              nativeWaterColor,
            ]);
          }
          void addLandmarkLabels(instance, attributionListeners.signal);
          instance.addSource("terrain", {
            type: "raster-dem",
            tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
            tileSize: 512,
            maxzoom: 12,
            encoding: "terrarium",
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
          const mobileControls = window.matchMedia("(max-width: 760px)");
          let scale = new ml.ScaleControl({
            maxWidth: mobileControls.matches ? 96 : 192,
            unit: "metric",
          });
          instance.addControl(scale, "bottom-left");
          mobileControls.addEventListener(
            "change",
            () => {
              instance.removeControl(scale);
              scale = new ml.ScaleControl({
                maxWidth: mobileControls.matches ? 96 : 192,
                unit: "metric",
              });
              instance.addControl(scale, "bottom-left");
            },
            { signal: attributionListeners.signal },
          );
          setMapReady(true);
        });
        instance.setStyle("https://tiles.openfreemap.org/styles/liberty", {
          transformStyle: (_previous, next) => cleanMapStyle(next),
        });
      })
      .catch(() => {
        if (disposed) return;
        setMapReady(false);
        toast.add({
          id: "map-load-error",
          type: "error",
          title: "The map could not be loaded.",
          description: "Reload the page to try again.",
        });
      });
    return () => {
      disposed = true;
      attributionListeners.abort();
      markers.current.forEach((marker) => marker.remove());
      markers.current.clear();
      annotationMarker.current?.remove();
      annotationMarker.current = null;
      observationPopup.current?.popup.remove();
      observationPopup.current = null;
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !container.current) return;
    const element = container.current;
    const viewport = element.parentElement!;
    const shell = element.closest(".bulletin-shell");
    const sidebarGap = shell?.querySelector('[data-slot="sidebar-gap"]');
    let transitionCenter: [number, number] | null = null;
    const resizeWithoutMovingImage = (
      width: number,
      changeLayout: () => void,
    ) => {
      const instance = map.current;
      if (!instance) return;
      const canvas = instance.getCanvas();
      // Preserve the geography at the right edge while the clipping area changes.
      const center = instance.unproject([
        canvas.clientWidth - width / 2,
        canvas.clientHeight / 2,
      ]);
      changeLayout();
      instance.resize().jumpTo({ center }).redraw();
    };
    const finishTransition = () => {
      if (!transitionCenter) return;
      const center = transitionCenter;
      transitionCenter = null;
      resizeWithoutMovingImage(viewport.clientWidth, () => {
        element.classList.remove("map-sidebar-transition");
        element.style.removeProperty("--map-transition-width");
      });
      map.current?.easeTo({ center, duration: 220 });
    };
    const startTransition = () => {
      const instance = map.current;
      if (!instance || !shell) return;
      instance.stop();
      transitionCenter = instance.getCenter().toArray();
      const inset = parseFloat(
        getComputedStyle(element.closest(".dashboard")!).paddingLeft,
      );
      const width =
        viewport.getBoundingClientRect().right -
        shell.getBoundingClientRect().left -
        inset;
      resizeWithoutMovingImage(width, () => {
        element.style.setProperty("--map-transition-width", `${width}px`);
        element.classList.add("map-sidebar-transition");
      });
    };
    sidebarGap?.addEventListener("transitionrun", startTransition);
    sidebarGap?.addEventListener("transitionend", finishTransition);
    sidebarGap?.addEventListener("transitioncancel", finishTransition);
    let previousHeight = viewport.clientHeight;
    const observer = new ResizeObserver(() => {
      if (transitionCenter) return;
      const heightChanged = viewport.clientHeight !== previousHeight;
      previousHeight = viewport.clientHeight;
      // Redraw before browser paint; resizing clears the WebGL canvas.
      map.current?.resize().redraw();
      if (overviewInDrawer && selectedEvent && heightChanged) {
        map.current?.jumpTo({ center: [selectedEvent.longitude, selectedEvent.latitude] });
      }
    });
    observer.observe(viewport);
    return () => {
      observer.disconnect();
      sidebarGap?.removeEventListener("transitionrun", startTransition);
      sidebarGap?.removeEventListener("transitionend", finishTransition);
      sidebarGap?.removeEventListener("transitioncancel", finishTransition);
      element.classList.remove("map-sidebar-transition");
      element.style.removeProperty("--map-transition-width");
    };
  }, [mapReady, overviewInDrawer, selectedEvent]);

  useEffect(() => {
    if (!mapReady || !map.current) return;
    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || !map.current) return;
      const eventIds = new Set(events.map((event) => event.eventId));
      if (observationPopup.current && !eventIds.has(observationPopup.current.id)) {
        observationPopup.current.popup.remove();
        observationPopup.current = null;
      }
      for (const [id, marker] of markers.current) {
        if (eventIds.has(id)) continue;
        marker.remove();
        markers.current.delete(id);
      }
      for (const event of events) {
        const band = magnitudeBand(event.magnitude);
        const inspect = (click: MouseEvent) => {
          observationPopup.current?.popup.remove();
          observationPopup.current = null;
          if (!forecastAnchor || event.eventId === forecastAnchor.eventId) {
            onSelectRef.current(event.eventId);
            return;
          }
          click.stopPropagation();
          const instance = map.current;
          if (!instance) return;
          const position = new ml.LngLat(event.longitude, event.latitude);
          const distanceKm = position.distanceTo(new ml.LngLat(
            forecastAnchor.longitude, forecastAnchor.latitude,
          )) / 1000;
          const content = document.createElement("div");
          content.className = "forecast-observation-info";
          content.setAttribute("role", "status");
          const magnitude = document.createElement("strong");
          magnitude.textContent = `M${event.magnitude.toFixed(1)}`;
          const distance = document.createElement("span");
          distance.textContent = `${Math.round(distanceKm)} km from the trigger epicenter`;
          const occurrence = document.createElement("span");
          occurrence.textContent = occurrenceRelativeTo(event.eventTime, forecastAnchor.eventTime);
          content.append(magnitude, distance, occurrence);
          const popup = new ml.Popup({
            className: "forecast-observation-popup",
            maxWidth: "300px",
            offset: 12,
            padding: { top: 56, right: 8, bottom: 28, left: 8 },
            focusAfterOpen: false,
          }).setLngLat(position).setDOMContent(content).addTo(instance);
          observationPopup.current = { id: event.eventId, popup };
          popup.on("close", () => {
            if (observationPopup.current?.popup === popup) observationPopup.current = null;
          });
          popup.getElement().querySelector("button")?.addEventListener("click", () => {
            markers.current.get(event.eventId)?.getElement().focus({ preventScroll: true });
          });
          instance.flyTo({
            center: position,
            duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 700,
          });
        };
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
          button.onclick = inspect;
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
        button.onclick = inspect;
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
  }, [events, mapReady, forecastAnchor]);

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
    const source = mapReady
      ? (map.current?.getSource("forecast-radius") as GeoJSONSource | undefined)
      : undefined;
    const coordinates =
      areaEvent &&
      radiusKm &&
      (forecastAnchor || (showForecastOverview && !forecastDismissed))
        ? radiusCoordinates(areaEvent, radiusKm)
        : null;
    void source?.setData(
      coordinates
        ? {
            type: "Feature",
            properties: {},
            geometry: { type: "Polygon", coordinates: [coordinates] },
          }
        : emptyRadius,
    );
  }, [
    mapReady,
    areaEvent,
    radiusKm,
    forecastAnchor,
    showForecastOverview,
    forecastDismissed,
  ]);

  useEffect(() => {
    const instance = map.current;
    if (!mapReady || !instance) return;
    annotationMarker.current?.remove();
    annotationMarker.current = null;
    setAnnotationHost(null);
    if (!selectedEvent || forecastDismissed || !showForecastOverview || overviewInDrawer) {
      return;
    }

    const coordinates = radiusKm
      ? radiusCoordinates(selectedEvent, radiusKm)
      : null;

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

      if (forecastStatus === "loading" || !instance.getContainer().clientHeight)
        return;
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
    showForecastOverview,
    overviewInDrawer,
  ]);

  useEffect(() => {
    if (
      (showForecastOverview && !overviewInDrawer) ||
      (forecastAnchor && !focusRequest) ||
      !mapReady ||
      !map.current ||
      !selectedEvent
    )
      return;
    map.current.flyTo({
      center: [selectedEvent.longitude, selectedEvent.latitude],
      zoom: forecastAnchor ? map.current.getZoom() : 7.2,
      duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : 700,
    });
  }, [
    showForecastOverview,
    overviewInDrawer,
    forecastAnchor,
    mapReady,
    selectedEvent,
    focusRequest,
  ]);

  useEffect(() => {
    const instance = map.current;
    if (!mapReady || !instance || !forecastAnchor) return;
    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || map.current !== instance) return;
      const coordinates = radiusKm
        ? radiusCoordinates(forecastAnchor, radiusKm)
        : null;
      const bounds = coordinates?.reduce(
        (bounds, point) => bounds.extend(point),
        new ml.LngLatBounds(coordinates[0], coordinates[0]),
      );
      const camera = bounds
        ? instance.cameraForBounds(bounds, { padding: 50, maxZoom: 9.2 })
        : null;
      instance.jumpTo({
        center: [forecastAnchor.longitude, forecastAnchor.latitude],
        zoom: camera?.zoom ?? 7.2,
        pitch: 0,
        bearing: 0,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [mapReady, forecastAnchor, radiusKm]);

  function zoom(delta: number) {
    map.current?.zoomTo(map.current.getZoom() + delta, { duration: 350 });
  }
  function recenter() {
    if (forecastAnchor) {
      observationPopup.current?.popup.remove();
      map.current?.flyTo({
        center: [forecastAnchor.longitude, forecastAnchor.latitude],
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 700,
      });
      return;
    }
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
    applyTerrain(map.current, next);
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
    <div className="map-region">
      <section
        id="earthquake-map"
        className="map-panel"
        aria-label="Earthquakes on the Philippine map"
        onKeyDown={(event) => {
          if (event.key !== "Escape" || !observationPopup.current) return;
          const { id, popup } = observationPopup.current;
          if (popup.getElement().contains(document.activeElement)) {
            markers.current.get(id)?.getElement().focus({ preventScroll: true });
          }
          popup.remove();
          observationPopup.current = null;
        }}
      >
        {!mapReady && (
          <img
            className="map-plate"
            src="/assets/plates/relief-map.webp"
            alt=""
            fetchPriority="high"
          />
        )}
        <div className="map-canvas" ref={container} />
        {annotationHost &&
          selectedEvent &&
          !forecastDismissed &&
          createPortal(
            <ForecastOverview
              forecast={forecast}
              status={forecastStatus}
              onClose={() => {
                setDismissedForecast({
                  id: selectedEvent.eventId,
                  focusRequest,
                });
                markers.current
                  .get(selectedEvent.eventId)
                  ?.getElement()
                  .focus({ preventScroll: true });
              }}
            />,
            annotationHost,
          )}
        <Button
          variant="outline"
          className="terrain-button"
          onPress={toggleTerrain}
          isDisabled={!mapReady}
          aria-pressed={terrain}
          aria-label="3D terrain"
          aria-description="In 3D, right-drag or use Shift + arrow keys to tilt and rotate. On touchscreens, move two fingers together to tilt; pinch to zoom."
        >
          <span className="terrain-switch" aria-hidden="true">
            <span className="terrain-thumb" />
          </span>
          <span className="terrain-label">3D terrain</span>
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
            aria-label={forecastAnchor ? "Recenter on trigger earthquake" : "Show the Philippines"}
          >
            <LocateFixed aria-hidden="true" />
          </Button>
        </div>
        <div
          className={`map-legend-control${legendOpen ? " is-open" : ""}`}
          ref={legendControl}
        >
          <Button
            variant="ghost"
            size="icon-xs"
            className="map-legend-toggle"
            aria-label="Magnitude legend"
            aria-expanded={legendOpen}
            aria-controls="map-magnitude-legend"
            onPress={() => setLegendOpen((open) => !open)}
          >
            <CircleQuestionMark aria-hidden="true" />
          </Button>
          <div
            id="map-magnitude-legend"
            className="map-legend"
            role="region"
            aria-label="Magnitude legend"
          >
            <strong>Magnitude (M)</strong>
            {magnitudeBands.map((band) => (
              <span key={band.className}>
                <i className={`dot ${band.className}`} aria-hidden="true" />
                {band.label}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
