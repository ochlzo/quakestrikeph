import { useCallback, useEffect, useRef, useState, type SubmitEvent } from "react";
import { ChevronDown, CircleAlert } from "lucide-react";
import ForecastFacts from "@/components/ForecastFacts";
import ForecastDiscussion from "@/components/ForecastDiscussion";
import MapPanel, { isInBulletinMap } from "@/components/MapPanel";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { FormField } from "@/features/accounts/FormField";
import LocationSearchControls from "@/features/accounts/LocationSearchControls";
import { browserLocation } from "@/features/accounts/location-edit";
import { usePlaces } from "@/features/accounts/location-places";
import { displayPreciseTime } from "@/lib/events";
import { initForecastDetails } from "@/lib/forecast-details";
import {
  refreshSimulationPage,
  runForecastSimulation,
  unavailableCatalog,
  type SimulationCatalog,
  type SimulationResult,
} from "@/lib/api/forecast-simulations";

const fields = [
  {
    name: "latitude",
    label: "Latitude",
    placeholder: "13.6000",
    message: "Pick a point on the map or enter a latitude within the map area.",
  },
  {
    name: "longitude",
    label: "Longitude",
    placeholder: "124.7500",
    message: "Pick a point on the map or enter a longitude within the map area.",
  },
  {
    name: "magnitude",
    label: "Magnitude",
    placeholder: "1.0–10.0",
    message: "Enter a magnitude between 1.0 and 10.0.",
  },
  {
    name: "depth",
    label: "Depth (km)",
    placeholder: "0–700",
    message: "Enter a depth between 0 and 700 km.",
  },
] as const;

type Name = (typeof fields)[number]["name"];
type Values = Record<Name, string>;
type Errors = Partial<Record<Name, string>>;
type Point = { latitude: number; longitude: number };
type View = {
  values: Values;
  point: Point | null;
  focus: number;
  query: string;
  errors: Errors;
};

const blank: Values = { latitude: "", longitude: "", magnitude: "", depth: "" };
const blockedCookieMessage = {
  title: "Your browser is blocking cookies",
  description: "Allow cookies for this site, then reload the page to run a simulation.",
};
const messages = {
  insufficient_history: {
    title: "More earthquake records are needed",
    description: "Try again when seven full days of verified PHIVOLCS records are available.",
  },
  too_old: {
    title: "The latest earthquake records are too old",
    description:
      "The last verified PHIVOLCS records are over seven weeks old. Try again when newer records are available.",
  },
  cookies: {
    title: "A guest cookie is required",
    description: "Reload the page to confirm your guest cookie and try again.",
  },
  limit: {
    title: "Simulation limit reached",
    description: "Try again in a moment.",
  },
  busy: {
    title: "Too many simulations are running",
    description: "Wait a moment, then try again.",
  },
  quota: {
    title: "We couldn't check how many runs you have left",
    description: "Try again in a moment.",
  },
  failed: {
    title: "Simulation didn't finish",
    description: "This attempt counts toward your limit because the simulation started.",
  },
  unavailable: {
    title: "The PHIVOLCS catalog could not be checked",
    description: "This page will check again automatically.",
  },
  unknown: {
    title: "The simulation outcome could not be confirmed",
    description: "We don't know whether this attempt counted toward your limit.",
  },
  invalid: {
    title: "The simulation request was rejected",
    description: "Check the earthquake details and try again.",
  },
} satisfies Record<string, { title: string; description: string }>;
type RunFeedback = Exclude<keyof typeof messages, SimulationCatalog["status"]>;
const formErrorToast = "simulation-form-error";
const minuteMs = 60_000;
const catalogRefreshMs = 30_000;
const scenarioMagnitude = new Intl.NumberFormat("en-PH", {
  minimumFractionDigits: 1, maximumFractionDigits: 20,
});
const dayMs = 86_400_000;
const recordDays = 7;
const timelineDate = new Intl.DateTimeFormat("en-PH", {
  timeZone: "Asia/Manila",
  month: "short",
  day: "numeric",
});
const noEvents: [] = [];
const ignoreSelection = () => {};

function number(text: string) {
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text.trim()) ? Number(text) : NaN;
}

function pointFrom(values: Values) {
  const point = {
    latitude: number(values.latitude),
    longitude: number(values.longitude),
  };
  return isInBulletinMap(point) ? point : null;
}

function validate(values: Values): Errors {
  const latitude = number(values.latitude);
  const longitude = number(values.longitude);
  const measured = number(values.magnitude);
  const depth = number(values.depth);
  const valid = {
    latitude: isInBulletinMap({ latitude, longitude: 122 }),
    longitude: isInBulletinMap({ latitude: 13, longitude }),
    magnitude: measured >= 1 && measured <= 10,
    depth: depth >= 0 && depth <= 700,
  };
  return Object.fromEntries(
    fields
      .filter(({ name }) => !valid[name])
      .map(({ name, label, message }) => [
        name,
        values[name].trim() ? message : `Enter the ${label.toLowerCase().replace(" (km)", "")}.`,
      ]),
  );
}

function focusField(form: HTMLFormElement, name: Name) {
  const input = form.elements.namedItem(name);
  if (input instanceof HTMLInputElement) input.focus();
}

function RetryCountdown({ retryAt, onElapsed }: { retryAt: number; onElapsed: () => void }) {
  const [minutes, setMinutes] = useState(() => Math.max(1, Math.ceil((retryAt - Date.now()) / minuteMs)));

  useEffect(() => {
    let timeout: number | undefined;

    function tick() {
      const remaining = retryAt - Date.now();
      if (remaining <= 0) {
        onElapsed();
        return;
      }

      const roundedMinutes = Math.ceil(remaining / minuteMs);
      setMinutes(roundedMinutes);
      const untilNextMinute = remaining - (roundedMinutes - 1) * minuteMs;
      timeout = window.setTimeout(tick, untilNextMinute);
    }

    tick();
    return () => window.clearTimeout(timeout);
  }, [retryAt, onElapsed]);

  return (
    <p role="timer">
      Try again in {minutes} {minutes === 1 ? "minute" : "minutes"}.
    </p>
  );
}

function RecordsTimeline({ cutoff }: { cutoff: string }) {
  const simulatedTime = Date.parse(cutoff);
  const milestones = [
    {
      label: "Records start",
      date: new Date(simulatedTime - recordDays * dayMs),
    },
    { label: "Simulated earthquake", date: new Date(simulatedTime) },
    { label: "Forecast ends", date: new Date(simulatedTime + dayMs) },
  ];

  return (
    <figure className="simulate-timeline" aria-label="Earthquake records and forecast timeline">
      <div className="timeline-periods">
        <span>7 days of records</span>
        <span>24-hour forecast</span>
      </div>
      <div className="timeline-axis" aria-hidden="true">
        {Array.from({ length: recordDays + 1 }, (_, day) => (
          <div className="timeline-day" key={day} />
        ))}
        <span className="timeline-marker" />
      </div>
      <ol className="timeline-milestones">
        {milestones.map(({ label, date }, index) => (
          <li key={label} className={index === 1 ? "timeline-earthquake" : undefined}>
            <time dateTime={date.toISOString()}>{timelineDate.format(date)}</time>
            <span className={index === 1 ? "timeline-milestone-label" : "sr-only"}>{label}</span>
          </li>
        ))}
      </ol>
    </figure>
  );
}

export default function Simulation({
  catalog: initialCatalog,
  guestCookieConfirmed: initialGuestCookieConfirmed,
}: {
  catalog: SimulationCatalog;
  guestCookieConfirmed: boolean | null;
}) {
  const [view, update] = useState<View>({
    values: blank,
    point: null,
    focus: 0,
    query: "",
    errors: {},
  });
  const [catalog, setCatalog] = useState(initialCatalog);
  const [guestCookieConfirmed, setGuestCookieConfirmed] = useState(initialGuestCookieConfirmed);
  const [feedback, setFeedback] = useState<RunFeedback | null>(null);
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const pending = useRef(false);
  const resultSection = useRef<HTMLElement>(null);
  const resultTitle = useRef<HTMLHeadingElement>(null);
  const [scrollRequest, requestScroll] = useState(0);
  const [locating, setLocating] = useState(false);
  const locationRequest = useRef(0);
  const { list, error: searchError } = usePlaces();
  const { catalogCutoff: cutoff, status } = catalog;
  const eligible = status === "current" || status === "stale";
  const catalogMessage = eligible ? null : messages[status];
  const message = guestCookieConfirmed === false
    ? blockedCookieMessage
    : catalogMessage ?? (feedback ? messages[feedback] : null);
  const blocked =
    running || !eligible || guestCookieConfirmed !== true || feedback === "cookies" || retryAt !== null;
  const hasResult = result !== null;
  const sourceSummary = (
    <>
      <span>PHIVOLCS records available through</span>
      {cutoff ? <time dateTime={cutoff}>{displayPreciseTime(cutoff)}</time> : <strong>Unavailable</strong>}
      {status === "stale" && <span className="simulate-stale">Records older than 24 hours</span>}
    </>
  );
  const sourceExplanation =
    eligible && cutoff ? (
      <RecordsTimeline cutoff={cutoff} />
    ) : (
      <p>
        The model needs seven days of recent, verified PHIVOLCS records to estimate further earthquake
        activity.
      </p>
    );

  const clearRunLimit = useCallback(() => {
    setRetryAt(null);
    setFeedback((previous) => (previous === "limit" ? null : previous));
  }, []);

  useEffect(() => setHydrated(true), []);

  useEffect(() => {
    if (running) return;
    const request = new AbortController();
    const timer = window.setInterval(async () => {
      if (document.visibilityState !== "visible" || pending.current) return;
      const page = await refreshSimulationPage(request.signal, guestCookieConfirmed === false);
      if (request.signal.aborted || pending.current) return;
      const refreshedCatalog = page?.catalog ?? unavailableCatalog;
      setCatalog((previous) =>
        previous.status === refreshedCatalog.status &&
        previous.catalogCutoff === refreshedCatalog.catalogCutoff
          ? previous
          : refreshedCatalog,
      );
      if (!page) return;
      setGuestCookieConfirmed(page.guestCookieConfirmed);
      if (page.guestCookieConfirmed) {
        setFeedback((previous) => previous === "cookies" ? null : previous);
      }
    }, catalogRefreshMs);
    return () => {
      window.clearInterval(timer);
      request.abort();
    };
  }, [running, guestCookieConfirmed]);

  useEffect(() => {
    if (!message) return;
    toast.add({
      id: formErrorToast,
      type: "error",
      title: message.title,
      timeout: 8000,
    });
    return () => toast.close(formErrorToast);
  }, [message]);

  function focusResult() {
    requestScroll((request) => request + 1);
  }

  useEffect(() => {
    const heading = resultTitle.current;
    if (!scrollRequest || !heading) return;
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
    });
  }, [scrollRequest]);

  useEffect(() => {
    if (hasResult && resultSection.current) return initForecastDetails(resultSection.current);
  }, [hasResult]);

  useEffect(
    () => () => {
      locationRequest.current++;
    },
    [],
  );

  const cancelLocation = useCallback(() => {
    locationRequest.current++;
    setLocating(false);
  }, []);

  const setCoordinate = useCallback(
    (point: Point, query: string, focus: boolean) => {
      cancelLocation();
      const values = {
        latitude: String(point.latitude),
        longitude: String(point.longitude),
      };
      update((previous) => ({
        ...previous,
        values: { ...previous.values, ...values },
        point,
        query,
        focus: focus ? previous.focus + 1 : 0,
        errors: {
          ...previous.errors,
          latitude: undefined,
          longitude: undefined,
        },
      }));
    },
    [cancelLocation],
  );

  function locate() {
    if (running || locating) return;
    const request = ++locationRequest.current;
    setLocating(true);
    const reportError = (title: string) => {
      setLocating(false);
      toast.add({
        id: "simulation-location-error",
        type: "error",
        title,
        timeout: 8000,
      });
    };
    browserLocation(
      ([latitude, longitude]) => {
        if (request !== locationRequest.current) return;
        const point = { latitude, longitude };
        if (isInBulletinMap(point)) setCoordinate(point, "", true);
        else
          reportError(
            "Your device is outside the Bulletin map area. Search for a place or choose a map pin.",
          );
      },
      (message) => {
        if (request === locationRequest.current) reportError(message);
      },
    );
  }

  const pickOnMap = useCallback(
    (point: Point) => {
      if (running) return;
      const position = {
        latitude: Number(point.latitude.toFixed(5)),
        longitude: Number(point.longitude.toFixed(5)),
      };
      setCoordinate(position, "", false);
    },
    [running, setCoordinate],
  );

  function commitCoordinates() {
    update((previous) => {
      const point = pointFrom(previous.values);
      if (point?.latitude === previous.point?.latitude && point?.longitude === previous.point?.longitude)
        return previous;
      return { ...previous, point, query: "", focus: previous.focus + 1 };
    });
  }

  async function simulate(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (blocked || pending.current) return;
    const form = event.currentTarget;
    const { values } = view;
    const errors = validate(values);
    const firstError = fields.find(({ name }) => errors[name]);
    if (firstError) {
      update((previous) => ({ ...previous, errors }));
      focusField(form, firstError.name);
      return;
    }
    const point = pointFrom(values);
    if (!point) return;
    pending.current = true;
    cancelLocation();
    setFeedback(null);
    setRunning(true);
    update((previous) => ({ ...previous, point, errors: {} }));

    const outcome = await runForecastSimulation({
      ...point,
      magnitude: number(values.magnitude),
      depthKm: number(values.depth),
    });
    pending.current = false;
    setRunning(false);
    if ("result" in outcome) {
      setCatalog(outcome.catalog);
      setResult(outcome.result);
      focusResult();
    } else if (outcome.state === "field") {
      const name = outcome.field === "depthKm" ? "depth" : outcome.field;
      update((previous) => ({
        ...previous,
        errors: { [name]: outcome.message },
      }));
      focusField(form, name);
    } else if (outcome.state === "catalog") {
      setCatalog(outcome.catalog);
    } else {
      if (outcome.state === "limit") setRetryAt(outcome.retryAt);
      setFeedback(outcome.state);
    }
  }

  return (
    <div data-simulation>
      <form className="simulate-workspace" noValidate onSubmit={simulate}>
        <div className="simulate-map-stack">
          <LocationSearchControls
            places={list}
            query={view.query}
            searchError={searchError}
            locating={locating}
            isDisabled={running}
            onQueryChange={(query) => update((previous) => ({ ...previous, query }))}
            onPlaceSelect={([name, area, latitude, longitude]) =>
              setCoordinate({ latitude, longitude }, `${name}, ${area}`, true)
            }
            onLocate={locate}
          />
          <div className="simulate-map">
            <MapPanel
              events={noEvents}
              selectedId={null}
              focusRequest={view.focus}
              forecast={null}
              forecastStatus="ready"
              onSelect={ignoreSelection}
              showForecastOverview={false}
              scenario={{ point: view.point, onPick: pickOnMap }}
              mapId="choose-epicenter-map"
            />
          </div>
        </div>
        <div className="simulate-inputs">
          <h2>Earthquake details</h2>
          <div className="simulate-fields">
            {fields.map(({ name, label, placeholder }) => (
              <FormField
                key={name}
                id={`simulation-${name}`}
                name={name}
                label={label}
                value={view.values[name]}
                placeholder={placeholder}
                error={view.errors[name]}
                required
                inputMode="decimal"
                readOnly={running}
                onChange={(event) => {
                  const value = event.currentTarget.value;
                  if (name === "latitude" || name === "longitude") cancelLocation();
                  update((previous) => ({
                    ...previous,
                    values: { ...previous.values, [name]: value },
                    errors: { ...previous.errors, [name]: undefined },
                  }));
                }}
                onBlur={name === "latitude" || name === "longitude" ? commitCoordinates : undefined}
              />
            ))}
          </div>
          {message && (
            <div className="simulate-feedback">
              <CircleAlert size={18} aria-hidden="true" />
              <div>
                <strong>{message.title}</strong>
                {message === messages.limit && retryAt !== null ? (
                  <RetryCountdown key={retryAt} retryAt={retryAt} onElapsed={clearRunLimit} />
                ) : (
                  <p>{message.description}</p>
                )}
              </div>
            </div>
          )}
          <Button className="simulate-run" type="submit" isDisabled={blocked || !hydrated}>
            {running ? "Running simulation…" : message && !blocked ? "Try again" : "Run simulation"}
          </Button>
          <span className="sr-only" role="status">
            {running ? "Running simulation" : ""}
          </span>
          <div className="simulate-source simulate-source-desktop">
            <div className="simulate-source-heading">{sourceSummary}</div>
            {sourceExplanation}
          </div>
        </div>
      </form>

      <details className="simulate-source simulate-source-mobile">
        <summary className="simulate-source-heading">
          {sourceSummary}
          <ChevronDown size={16} aria-hidden="true" />
        </summary>
        {sourceExplanation}
      </details>

      {result && (
        <section className="simulation-result" aria-labelledby="simulation-result-title" ref={resultSection}>
          <h2 id="simulation-result-title" tabIndex={-1} ref={resultTitle}>
            Simulated 24-hour forecast
          </h2>
          <p className="simulation-result-window">24 hours after the hypothetical earthquake</p>
          <div className="overview">
            <div className="facts">
              <details className="event-details">
                <summary>
                  Simulated earthquake details
                  <ChevronDown className="chevron" size={18} aria-hidden="true" />
                </summary>
                <dl className="disclosure-body event-grid">
                  <div>
                    <dt className="field-label">Latitude and longitude</dt>
                    <dd>
                      {result.scenario.latitude}°, {result.scenario.longitude}°
                    </dd>
                  </div>
                  <div>
                    <dt className="field-label">Magnitude</dt>
                    <dd>M{scenarioMagnitude.format(result.scenario.magnitude)}</dd>
                  </div>
                  <div>
                    <dt className="field-label">Depth</dt>
                    <dd>{result.scenario.depthKm} km</dd>
                  </div>
                </dl>
              </details>
              <div className="window">
                <div className="window-head">
                  <h3>Forecast window</h3>
                </div>
                <div className="window-times">
                  <div>
                    <span className="field-label">Starts at PHIVOLCS cutoff</span>
                    <time dateTime={result.forecast.windowStart}>
                      {displayPreciseTime(result.forecast.windowStart)}
                    </time>
                  </div>
                  <div>
                    <span className="field-label">Ends</span>
                    <time dateTime={result.forecast.windowEnd}>{displayPreciseTime(result.forecast.windowEnd)}</time>
                  </div>
                </div>
              </div>
              <ForecastFacts forecast={result.forecast} simulated />
            </div>
            <figure className="simulate-radius-figure">
              <div className="simulate-map simulate-radius-map">
                <MapPanel
                  events={noEvents}
                  selectedId={null}
                  focusRequest={1}
                  forecast={null}
                  forecastStatus="ready"
                  onSelect={ignoreSelection}
                  showForecastOverview={false}
                  scenario={{
                    point: result.scenario,
                    radiusKm: result.forecast.activityRadiusMedianKm24h,
                  }}
                  mapId="simulated-activity-map"
                />
              </div>
              {result.forecast.activityRadiusMedianKm24h !== null && (
                <figcaption>
                  {result.forecast.activityRadiusMedianKm24h} km estimated activity radius
                </figcaption>
              )}
            </figure>
          </div>
          <ForecastDiscussion forecast={result.forecast} simulated />
        </section>
      )}
    </div>
  );
}
