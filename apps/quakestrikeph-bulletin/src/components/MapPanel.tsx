import { useEffect, useRef, useState } from "react";
import { Layers3, LocateFixed, Minus, Plus } from "lucide-react";
import type { Map, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import type { Earthquake } from "../lib/events";

type Props = {
  events: Earthquake[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

const magnitudeBands = [
  { minimum: 6, className: "mag-6", label: "M6.0+" },
  { minimum: 5, className: "mag-5", label: "M5.0–<6.0" },
  { minimum: 4, className: "mag-4", label: "M4.0–<5.0" },
  {
    minimum: 3,
    className: "mag-3",
    label:
      "M3.0–<4.0                                                           ",
  },
  { minimum: -Infinity, className: "mag-under-3", label: "Below M3.0" },
] as const;

function magnitudeBand(value: number) {
  return (
    magnitudeBands.find((band) => value >= band.minimum) ??
    magnitudeBands.at(-1)!
  );
}

export default function MapPanel({ events, selectedId, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const markers = useRef<Marker[]>([]);
  const onSelectRef = useRef(onSelect);
  const [terrain, setTerrain] = useState(true);
  const [mapReady, setMapReady] = useState(false);
  onSelectRef.current = onSelect;

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
            customAttribution:
              '<a href="https://mapterhorn.com/attribution/" target="_blank" rel="noopener noreferrer">© Mapterhorn</a>',
          },
          style: "https://tiles.openfreemap.org/styles/positron",
          center: compact ? [123.1, 11.7] : [123.3, 10.8],
          zoom: compact ? 4.15 : 5.55,
          pitch: compact ? 20 : 42,
          bearing: 0,
        });
        map.current = instance;
        // Attach to this map instance, including maps recreated by Fast Refresh.
        const attribution = instance
          .getContainer()
          .querySelector<HTMLDetailsElement>(".maplibregl-ctrl-attrib");
        if (attribution) {
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
          instance.addSource("terrain", {
            type: "raster-dem",
            tiles: ["https://tiles.mapterhorn.com/{z}/{x}/{y}.webp"],
            tileSize: 512,
            maxzoom: 12,
            encoding: "terrarium",
          });
          instance.setTerrain({ source: "terrain", exaggeration: 1.3 });
          instance.addLayer({
            id: "terrain-shade",
            type: "hillshade",
            source: "terrain",
            paint: {
              "hillshade-shadow-color": "#3e6c6d",
              "hillshade-highlight-color": "#ffffff",
              "hillshade-accent-color": "#719896",
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
      markers.current = [];
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    if (!mapReady || !map.current) return;
    let cancelled = false;
    import("maplibre-gl").then((ml) => {
      if (cancelled || !map.current) return;
      markers.current.forEach((marker) => marker.remove());
      markers.current = events.map((event) => {
        const band = magnitudeBand(event.magnitude);
        const button = document.createElement("button");
        button.type = "button";
        button.className = `quake-marker ${band.className} ${event.eventId === selectedId ? "is-selected" : ""}`;
        button.setAttribute(
          "aria-label",
          `Magnitude ${event.magnitude.toFixed(1)}, ${band.label}, ${event.locationDescription}`,
        );
        button.title = `M${event.magnitude.toFixed(1)} · ${event.locationDescription}`;
        button.addEventListener("click", () =>
          onSelectRef.current(event.eventId),
        );
        return new ml.Marker({ element: button, anchor: "center" })
          .setLngLat([event.longitude, event.latitude])
          .addTo(map.current!);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [events, selectedId, mapReady]);

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
    if (!map.current) return;
    const next = !terrain;
    map.current.setTerrain(
      next ? { source: "terrain", exaggeration: 1.3 } : null,
    );
    map.current.easeTo({
      pitch: next
        ? window.matchMedia("(max-width: 600px)").matches
          ? 20
          : 42
        : 0,
      duration: 500,
    });
    setTerrain(next);
  }

  return (
    <section
      className="map-panel"
      aria-label="Earthquakes on the Philippine map"
    >
      <img className="map-plate" src="/assets/plates/relief-map.png" alt="" />
      <div className="map-canvas" ref={container} />
      <button
        className="terrain-button"
        type="button"
        onClick={toggleTerrain}
        aria-pressed={terrain}
        aria-label="3D terrain"
      >
        <Layers3 size={18} aria-hidden="true" />
        <span className="terrain-label">3D terrain</span>
        <span className="terrain-switch" aria-hidden="true">
          <span className="terrain-thumb" />
        </span>
      </button>
      <div className="map-tools">
        <button onClick={() => zoom(1)} aria-label="Zoom in">
          <Plus size={20} />
        </button>
        <button onClick={() => zoom(-1)} aria-label="Zoom out">
          <Minus size={20} />
        </button>
        <button onClick={recenter} aria-label="Show the Philippines">
          <LocateFixed size={19} />
        </button>
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
