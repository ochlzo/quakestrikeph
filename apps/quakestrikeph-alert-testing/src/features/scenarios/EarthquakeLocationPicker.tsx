import { useEffect, useMemo, useRef, useState } from "react";
import type { Map, Marker } from "maplibre-gl";
import { Label } from "react-aria-components";
import { MapPinSearch } from "lucide-react";
import { Button } from "@quakestrikeph/ui/button";
import {
  Combobox,
  ComboboxContent,
  ComboboxItem,
  ComboboxList,
  ComboboxEmpty,
  ComboboxTrigger,
} from "@quakestrikeph/ui/combobox";
import {
  InputGroup,
  InputGroupInput,
  InputGroupAddon,
} from "@quakestrikeph/ui/input-group";
import { Field, FieldError } from "@quakestrikeph/ui/field";
import { Spinner } from "@quakestrikeph/ui/spinner";
import { toast } from "@quakestrikeph/ui/toast";
import { loadMapRuntime } from "../../lib/map-runtime";
import { useErrorToast } from "../feedback";
import type { Inputs } from "../workspace/workspace-memory";
import {
  earthquakePoint,
  earthquakeLocationLabel,
  matchingPlaces,
  applyEarthquakeLocation,
  type Place,
  type Point,
} from "./earthquake-location";
import "maplibre-gl/dist/maplibre-gl.css";

export default function EarthquakeLocationPicker({
  inputs,
  onChange,
  disabled,
  owner,
  error,
}: {
  inputs: Inputs;
  onChange: (inputs: Inputs) => void;
  disabled: boolean;
  owner: string;
  error?: string;
}) {
  const [places, setPlaces] = useState<Place[]>([]),
    [placesError, setPlacesError] = useState("");
  const [mapError, setMapError] = useState(""),
    [mapReady, setMapReady] = useState(false);
  const [attempt, setAttempt] = useState(0),
    [locating, setLocating] = useState(false);
  const [selectedKey, setSelectedKey] = useState<number | null>(null);
  const [query, setQuery] = useState(inputs.location);
  const container = useRef<HTMLDivElement>(null),
    anchor = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null),
    marker = useRef<Marker | null>(null);
  const latest = useRef({ inputs, onChange, disabled, owner, places });
  latest.current = { inputs, onChange, disabled, owner, places };
  const deviceRequest = useRef(0);
  const previousPoint = useRef(`${inputs.latitude},${inputs.longitude}`);
  const editablePoint = useRef(false);
  const matches = useMemo(() => matchingPlaces(places, query), [places, query]);
  useEffect(() => {
    setQuery(inputs.location);
  }, [inputs.location, owner]);

  useErrorToast(placesError, "earthquake-places", () =>
    setAttempt((value) => value + 1),
  );
  useErrorToast(mapError, "earthquake-map", () =>
    setAttempt((value) => value + 1),
  );
  useEffect(() => {
    let active = true;
    setPlacesError("");
    fetch("/assets/accounts/philippine-places.json")
      .then((response) => {
        if (!response.ok) throw new Error();
        return response.json() as Promise<Place[]>;
      })
      .then((list) => {
        if (active) setPlaces(list);
      })
      .catch(() => {
        if (active)
          setPlacesError(
            "Could not load places.",
          );
      });
    return () => {
      active = false;
    };
  }, [attempt]);

  function update(next: Inputs) {
    setQuery(next.location);
    latest.current.inputs = next;
    latest.current.onChange(next);
  }
  function choose(point: Point, label?: string, key: number | null = null) {
    if (latest.current.disabled) return;
    toast.close("device-location");
    deviceRequest.current++;
    setLocating(false);
    setSelectedKey(key);
    const next = applyEarthquakeLocation(
      latest.current.inputs,
      point,
      latest.current.places,
      label,
    );
    previousPoint.current = `${next.latitude},${next.longitude}`;
    update(next);
  }

  useEffect(() => {
    let active = true;
    setMapError("");
    setMapReady(false);
    loadMapRuntime()
      .then((lib) => {
        if (!active || !container.current) return;
        const point = earthquakePoint(latest.current.inputs);
        const instance = new lib.Map({
          container: container.current,
          style: "https://tiles.openfreemap.org/styles/liberty",
          center: point
            ? [point[1], Math.max(-85, Math.min(85, point[0]))]
            : [121, 12.4],
          zoom: point ? 7 : 4.5,
          attributionControl: { compact: false },
        });
        map.current = instance;
        instance.addControl(
          new lib.NavigationControl({ showCompass: false }),
          "top-right",
        );
        const pin = new lib.Marker({
          color: "#0e6873",
          draggable: !latest.current.disabled,
        });
        marker.current = pin;
        pin
          .getElement()
          .setAttribute(
            "aria-label",
            "Earthquake epicenter. Use arrow keys to move the pin.",
          );
        if (point) pin.setLngLat([point[1], point[0]]).addTo(instance);
        pin.on("dragend", () => {
          const position = pin.getLngLat().wrap();
          choose([position.lat, position.lng]);
        });
        instance.on("click", (event) =>
          choose([event.lngLat.lat, event.lngLat.wrap().lng]),
        );
        instance.on("idle", () => {
          if (active && instance.isStyleLoaded()) setMapReady(true);
        });
        instance.on("error", () => {
          if (active)
            setMapError(
              "Could not load the map.",
            );
        });
        const resize = new ResizeObserver(() => instance.resize());
        resize.observe(container.current);
        observer = resize;
      })
      .catch(() => {
        if (active)
          setMapError(
            "Could not load the map.",
          );
      });
    let observer: ResizeObserver | undefined;
    return () => {
      active = false;
      observer?.disconnect();
      marker.current?.remove();
      map.current?.remove();
      map.current = null;
      marker.current = null;
    };
  }, [attempt]);

  useEffect(() => {
    deviceRequest.current++;
    setLocating(false);
    setSelectedKey(null);
    marker.current?.setDraggable(!disabled);
  }, [disabled, owner]);
  useEffect(
    () => () => {
      deviceRequest.current++;
    },
    [],
  );
  useEffect(() => {
    const point = earthquakePoint(inputs),
      identity = `${inputs.latitude},${inputs.longitude}`;
    if (point && map.current && marker.current) {
      marker.current.setLngLat([point[1], point[0]]).addTo(map.current);
      map.current.jumpTo({
        center: [point[1], Math.max(-85, Math.min(85, point[0]))],
      });
    } else if (!point) marker.current?.remove();
    if (disabled || !editablePoint.current) {
      editablePoint.current = !disabled;
      previousPoint.current = identity;
      return;
    }
    if (previousPoint.current !== identity) {
      previousPoint.current = identity;
      deviceRequest.current++;
      setLocating(false);
      setSelectedKey(null);
      if (point && !disabled)
        update({
          ...latest.current.inputs,
          location: earthquakeLocationLabel(point, places),
        });
    }
  }, [inputs.latitude, inputs.longitude, disabled, places]);

  function locate() {
    if (disabled || locating) return;
    if (!navigator.geolocation) {
      toast.add({
        id: "device-location",
        type: "error",
        title: "Could not use your location.",
        actionProps: { children: "Choose place", onClick: () => document.getElementById("location")?.focus() },
        timeout: 8000,
      });
      return;
    }
    const request = ++deviceRequest.current,
      session = owner;
    setLocating(true);
    const valid = () =>
      request === deviceRequest.current &&
      session === latest.current.owner &&
      !latest.current.disabled;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (valid())
          choose([position.coords.latitude, position.coords.longitude]);
      },
      () => {
        if (!valid()) return;
        setLocating(false);
        toast.add({
          id: "device-location",
          type: "error",
          title: "Could not use your location.",
          actionProps: { children: "Choose place", onClick: () => document.getElementById("location")?.focus() },
          timeout: 8000,
        });
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 },
    );
  }

  return (
    <>
      <div
        className="earthquake-location-map"
        aria-busy={!mapReady && !mapError}
      >
        <div
          ref={container}
          className="earthquake-location-canvas"
          aria-label="Choose earthquake epicenter"
        />
        {!mapReady && !mapError && (
          <div className="earthquake-map-loading">
            <Spinner
              className="size-6 text-muted-foreground"
              aria-label="Loading earthquake map"
            />
          </div>
        )}
      </div>
      <div className="earthquake-location-row">
        <Combobox
          className="earthquake-location-combobox"
          inputValue={query}
          selectedKey={selectedKey}
          isDisabled={disabled}
          allowsCustomValue
          allowsEmptyCollection
          defaultFilter={() => true}
          menuTrigger="input"
          onInputChange={(value) => {
            deviceRequest.current++;
            setLocating(false);
            setSelectedKey(null);
            setQuery(value);
          }}
          onSelectionChange={(key) => {
            const match = matches.find((item) => item.index === key);
            if (match)
              choose(
                [match.place[2], match.place[3]],
                `${match.place[0]}, ${match.place[1]}`,
                match.index,
              );
          }}
        >
          <Field className="form-field" data-invalid={!!error || undefined}>
            <Label htmlFor="location" className="earthquake-location-label">
              Location description
            </Label>
            <div ref={anchor}>
              <InputGroup>
                <InputGroupInput
                  id="location"
                  placeholder="Search regions, cities or municipalities"
                  aria-invalid={!!error}
                  aria-describedby={error ? "location-error" : undefined}
                />
                <InputGroupAddon align="inline-end">
                  <ComboboxTrigger aria-label="Show matching locations" />
                </InputGroupAddon>
              </InputGroup>
            </div>
            {error && <FieldError id="location-error">{error}</FieldError>}
          </Field>
          <ComboboxContent
            anchor={anchor}
            className="earthquake-places-popover"
          >
            <ComboboxList<{ place: Place; index: number }>
              items={matches}
              renderEmptyState={() => (
                <ComboboxEmpty>
                  No matching places. Try another name or choose a map pin.
                </ComboboxEmpty>
              )}
            >
              {({ place, index }) => (
                <ComboboxItem id={index} textValue={`${place[0]}, ${place[1]}`}>
                  <span>
                    {place[0]}
                    <small className="earthquake-place-context">
                      {place[1]}
                    </small>
                  </span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
        <Button
          className="earthquake-use-location"
          variant="outline"
          isDisabled={disabled || locating}
          onPress={locate}
        >
          {locating ? (
            <Spinner aria-label="Finding device location" />
          ) : (
            <MapPinSearch size={16} />
          )}
          Use my location
        </Button>
      </div>
    </>
  );
}
