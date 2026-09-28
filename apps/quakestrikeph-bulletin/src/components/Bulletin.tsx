import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Search,
} from "lucide-react";
import MapPanel from "./MapPanel";
import {
  demoEvents,
  displayTime,
  magnitude,
  type Earthquake,
} from "../lib/events";
import "../styles/bulletin.css";

export default function Bulletin() {
  const demo =
    import.meta.env.DEV &&
    new URLSearchParams(window.location.search).has("demo");
  const [query, setQuery] = useState("");
  const [dateRange, setDateRange] = useState(demo ? "demo" : "7");
  const [minMagnitude, setMinMagnitude] = useState("");
  const [events, setEvents] = useState<Earthquake[]>(demo ? demoEvents : []);
  const [selectedId, setSelectedId] = useState<string | null>(
    demo ? demoEvents[0].eventId : null,
  );
  const [previousId, setPreviousId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<Earthquake | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    demo ? "ready" : "loading",
  );
  const [more, setMore] = useState(false);

  useEffect(() => {
    if (demo) return;
    const controller = new AbortController();
    const timer = window.setTimeout(
      async () => {
        setStatus("loading");
        try {
          const body = {
            location: query.trim().length >= 2 ? query.trim() : undefined,
            dateFrom:
              dateRange === "all"
                ? undefined
                : new Date(
                    Date.now() - Number(dateRange) * 86400000,
                  ).toISOString(),
            magnitudeRanges: minMagnitude
              ? [{ from: Number(minMagnitude) }]
              : undefined,
            limit: 30,
          };
          const response = await fetch("/api/v1/earthquakes/search", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(body),
            signal: controller.signal,
          });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = (await response.json()) as {
            items: Earthquake[];
            hasMore: boolean;
          };
          setEvents(data.items);
          setMore(data.hasMore);
          setSelectedId((current) =>
            data.items.some((item) => item.eventId === current)
              ? current
              : (data.items[0]?.eventId ?? null),
          );
          setStatus("ready");
        } catch (error) {
          if (!controller.signal.aborted) setStatus("error");
        }
      },
      query ? 300 : 0,
    );
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query, dateRange, minMagnitude, demo]);

  useEffect(() => {
    if (demo || !selectedId) {
      setSelectedDetail(null);
      return;
    }
    const controller = new AbortController();
    fetch(`/api/v1/earthquakes/${encodeURIComponent(selectedId)}`, {
      signal: controller.signal,
    })
      .then((response) =>
        response.ok
          ? response.json()
          : Promise.reject(new Error("detail failed")),
      )
      .then((data: { item: Earthquake }) => setSelectedDetail(data.item))
      .catch(() => {
        if (!controller.signal.aborted) setSelectedDetail(null);
      });
    return () => controller.abort();
  }, [selectedId, demo]);

  const visible = useMemo(() => {
    if (!demo) return events;
    const latestDemoTime = Date.parse(demoEvents[0].eventTime);
    return events.filter(
      (event) =>
        event.locationDescription.toLowerCase().includes(query.toLowerCase()) &&
        (!minMagnitude || event.magnitude >= Number(minMagnitude)) &&
        (dateRange === "all" ||
          dateRange === "demo" ||
          Date.parse(event.eventTime) >=
            latestDemoTime - Number(dateRange) * 86400000),
    );
  }, [demo, events, query, minMagnitude, dateRange]);
  const selected =
    visible.find((event) => event.eventId === selectedId) ?? visible[0];
  const sourceUrl =
    selectedDetail?.eventId === selected?.eventId &&
    /^https?:\/\//i.test(selectedDetail.source?.url ?? "")
      ? selectedDetail.source?.url
      : undefined;
  const forecastHref = selected
    ? `/forecasts?event=${encodeURIComponent(selected.eventId)}${demo ? "&demo=1" : ""}`
    : "/forecasts";
  const selectEvent = (id: string) => {
    if (id === selected?.eventId) return;
    setPreviousId(selected?.eventId ?? null);
    setSelectedId(id);
  };
  const renderRows = () =>
    visible.map((event) =>
      event.eventId === selected?.eventId ? (
        <article
          key={event.eventId}
          className={`selected-card${previousId !== null ? " selection-enter" : ""}`}
          aria-label="Selected earthquake"
        >
          <div className="card-top">
            <div className="selected-mag">{magnitude(event.magnitude)}</div>
            <time dateTime={event.eventTime}>
              {displayTime(event.eventTime)}
            </time>
          </div>
          <h2>{event.locationDescription}</h2>
          <div className="card-bottom">
            <div className="selected-facts">
              <span>
                <small>Depth</small>
                <strong>
                  {event.depthKm === null ? "Unknown" : `${event.depthKm} km`}
                </strong>
              </span>
              <span className="fact-source">
                <small>Source</small>
                {sourceUrl ? (
                  <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
                    PHIVOLCS <ExternalLink size={17} aria-hidden="true" />
                  </a>
                ) : (
                  <strong>PHIVOLCS</strong>
                )}
              </span>
            </div>
            <a className="forecast-link" href={forecastHref}>
              View forecast <ArrowRight size={22} aria-hidden="true" />
            </a>
          </div>
        </article>
      ) : (
        <button
          key={event.eventId}
          className={`event-row event-row-v2${event.eventId === previousId ? " selection-exit" : ""}`}
          onClick={() => selectEvent(event.eventId)}
        >
          <span className="row-v2-measure">
            <strong>{magnitude(event.magnitude)}</strong>
            <small>
              {event.depthKm === null
                ? "Unknown depth"
                : `${event.depthKm} km deep`}
            </small>
          </span>
          <span className="row-v2-detail">
            <b>{event.locationDescription}</b>
            <time dateTime={event.eventTime}>
              {displayTime(event.eventTime)}
            </time>
            <small>PHIVOLCS</small>
          </span>
          <ChevronRight aria-hidden="true" />
        </button>
      ),
    );

  return (
    <div className="bulletin-app">
      <header className="site-header">
        <a className="brand" href="/" aria-label="QuakeStrike PH Bulletin home">
          <span className="brand-mark">
            <Activity aria-hidden="true" size={24} strokeWidth={2.2} />
          </span>
          <span>
            <strong>QuakeStrike PH Bulletin</strong>
            <small>PHILIPPINE EARTHQUAKE INFORMATION</small>
          </span>
        </a>
        <nav className="site-nav" aria-label="Main navigation">
          <a href="/" aria-current="page">
            Earthquakes
          </a>
          <a href="/forecasts">Forecasts</a>
          <a href="/about">About</a>
        </nav>
        <a className="alerts-button" href="/alerts">
          <Bell size={17} aria-hidden="true" />
          Receive alerts
        </a>
      </header>

      <main className="dashboard">
        <div className="filter-bar" aria-label="Earthquake filters">
          <label className="search-field">
            <Search size={20} aria-hidden="true" />
            <span className="sr-only">Search by location</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by location (e.g. Legazpi, Albay)"
            />
          </label>
          <label className="select-field">
            <CalendarDays size={19} aria-hidden="true" />
            <span className="filter-font">
              <small>Date</small>
              <select
                value={dateRange}
                onChange={(event) => setDateRange(event.target.value)}
              >
                {demo && <option value="demo">Illustrative period</option>}
                <option value="1">
                  {demo ? "Sample: last 24 hours" : "Last 24 hours"}
                </option>
                <option value="7">
                  {demo ? "Sample: last 7 days" : "Last 7 days"}
                </option>
                <option value="30">
                  {demo ? "Sample: last 30 days" : "Last 30 days"}
                </option>
                <option value="all">All dates</option>
              </select>
            </span>
            <ChevronDown
              className="select-chevron"
              size={17}
              aria-hidden="true"
            />
          </label>
          <label className="select-field">
            <Activity size={19} aria-hidden="true" />
            <span className="filter-font">
              <small>Magnitude</small>
              <select
                value={minMagnitude}
                onChange={(event) => setMinMagnitude(event.target.value)}
              >
                <option value="">All magnitudes</option>
                <option value="3">M3.0 and above</option>
                <option value="4">M4.0 and above</option>
                <option value="5">M5.0 and above</option>
              </select>
            </span>
            <ChevronDown
              className="select-chevron"
              size={17}
              aria-hidden="true"
            />
          </label>
        </div>

        <div className="content-grid">
          <section className="events-panel" aria-labelledby="events-title">
            <div className="events-head">
              <div>
                <h1 id="events-title">Earthquakes</h1>
                <p>Browse observed events across the Philippines.</p>
              </div>
            </div>
            {status === "loading" && !events.length && (
              <div className="notice" role="status">
                Loading recent earthquakes…
              </div>
            )}
            {status === "error" && (
              <div className="notice" role="alert">
                Earthquake data is unavailable right now. Please try again
                later.
              </div>
            )}
            {status === "ready" && !visible.length && (
              <div className="notice" role="status">
                No earthquakes match these filters. Try a wider date or
                magnitude range.
              </div>
            )}
            {selected && (
              <div className="event-list" aria-label="Recent earthquakes">
                {renderRows()}
              </div>
            )}
            {more && (
              <p className="more-note">
                Showing the first 30 results. Narrow your search to find a
                specific event.
              </p>
            )}
          </section>
          <MapPanel
            events={visible}
            selectedId={selected?.eventId ?? null}
            onSelect={selectEvent}
          />
        </div>
      </main>
    </div>
  );
}
