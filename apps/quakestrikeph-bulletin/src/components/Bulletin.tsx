import { useEffect, useState } from "react";
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
import { displayTime, magnitude, type Earthquake } from "../lib/events";
import "../styles/bulletin.css";

export default function Bulletin() {
  const [query, setQuery] = useState("");
  const [dateRange, setDateRange] = useState("all");
  const [minMagnitude, setMinMagnitude] = useState("");
  const [events, setEvents] = useState<Earthquake[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [previousId, setPreviousId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<Earthquake | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [more, setMore] = useState(false);
  const [requestAttempt, setRequestAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    async function loadEvents() {
      setStatus("loading");
      try {
        const response = await fetch("/api/v1/earthquakes/search", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ limit: 30 }),
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
      } catch {
        if (!controller.signal.aborted) setStatus("error");
      }
    }

    void loadEvents();
    return () => {
      controller.abort();
    };
  }, [requestAttempt]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedDetail(null);
      return;
    }
    const controller = new AbortController();
    setSelectedDetail(null);
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
  }, [selectedId]);

  const visible = events;
  const selected =
    visible.find((event) => event.eventId === selectedId) ?? visible[0];
  const sourceUrl =
    selectedDetail &&
    selected &&
    selectedDetail.eventId === selected.eventId &&
    /^https?:\/\//i.test(selectedDetail.source?.url ?? "")
      ? selectedDetail.source?.url
      : undefined;
  const forecastHref = selected
    ? `/forecasts?event=${encodeURIComponent(selected.eventId)}`
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
              maxLength={100}
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
                <option value="all">All dates</option>
                <option value="1">Last 24 hours</option>
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
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
                <p>Earthquake data is unavailable right now.</p>
                <button
                  className="retry-button"
                  type="button"
                  onClick={() => setRequestAttempt((attempt) => attempt + 1)}
                >
                  Try again
                </button>
              </div>
            )}
            {status === "ready" && !visible.length && (
              <div className="notice" role="status">
                No earthquake information is available right now.
              </div>
            )}
            {selected && (
              <div className="event-list" aria-label="Recent earthquakes">
                {renderRows()}
              </div>
            )}
            {more && (
              <p className="more-note">
                Showing the 30 most recent earthquakes.
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
