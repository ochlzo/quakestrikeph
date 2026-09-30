import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  Calendar,
  ChevronRight,
  ExternalLink,
  Search,
  Stone,
} from "lucide-react";
import MapPanel from "./MapPanel";
import { bulletinApi } from "../lib/api/client";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  displayTime,
  magnitude,
  type Earthquake,
  type EarthquakeDetail,
} from "../lib/events";
import "../styles/bulletin.css";

const dateOptions = [
  { label: "All dates", value: "all" },
  { label: "Last 24 hours", value: "1" },
  { label: "Last 7 days", value: "7" },
  { label: "Last 30 days", value: "30" },
];

const magnitudeOptions = [
  { label: "All magnitudes", value: "all" },
  { label: "M3.0 and above", value: "3" },
  { label: "M4.0 and above", value: "4" },
  { label: "M5.0 and above", value: "5" },
];

export default function Bulletin() {
  const [query, setQuery] = useState("");
  const [dateRange, setDateRange] = useState("all");
  const [minMagnitude, setMinMagnitude] = useState("");
  const [events, setEvents] = useState<Earthquake[]>([]);
  const [settledLocation, setSettledLocation] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [previousId, setPreviousId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<EarthquakeDetail | null>(null);
  const [detailStatus, setDetailStatus] = useState<"loading" | "ready" | "error">("loading");
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [pageStatus, setPageStatus] = useState<"idle" | "loading" | "error">("idle");
  const pageController = useRef<AbortController | null>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [requestAttempt, setRequestAttempt] = useState(0);
  const location = query.trim();

  useEffect(() => () => pageController.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    pageController.current?.abort();
    pageController.current = null;
    setPageStatus("idle");
    setNextCursor(null);

    if (location.length === 1) return () => controller.abort();

    async function loadEvents() {
      setStatus("loading");
      try {
        const { data } = await bulletinApi.POST("/earthquakes/search", {
          body: { limit: 30, location: location || undefined },
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!data) throw new Error("Search failed");
        setEvents(data.items);
        setNextCursor(data.nextCursor);
        setSettledLocation(location);
        setPreviousId(null);
        setSelectedId((current) =>
          data.items.some((item) => item.eventId === current)
            ? current
            : null,
        );
        setStatus("ready");
      } catch {
        if (!controller.signal.aborted) {
          setSettledLocation(location);
          setStatus("error");
        }
      }
    }

    const timer = window.setTimeout(() => void loadEvents(), location ? 300 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [location, requestAttempt]);

  async function loadMore() {
    if (
      !nextCursor ||
      pageController.current ||
      status !== "ready" ||
      settledLocation !== location
    ) return;
    const controller = new AbortController();
    pageController.current = controller;
    setPageStatus("loading");
    try {
      const { data } = await bulletinApi.POST("/earthquakes/search", {
        body: { limit: 30, cursor: nextCursor, location: location || undefined },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!data) throw new Error("Search failed");
      setEvents((current) => {
        const seen = new Set(current.map((event) => event.eventId));
        return [...current, ...data.items.filter((event) => !seen.has(event.eventId))];
      });
      setNextCursor(data.nextCursor);
      setPageStatus("idle");
    } catch {
      if (!controller.signal.aborted) setPageStatus("error");
    } finally {
      if (pageController.current === controller) pageController.current = null;
    }
  }

  useEffect(() => {
    if (!selectedId) {
      setSelectedDetail(null);
      return;
    }
    const controller = new AbortController();
    setSelectedDetail(null);
    setDetailStatus("loading");
    bulletinApi.GET("/earthquakes/{eventId}", {
      params: { path: { eventId: selectedId } },
      signal: controller.signal,
    })
      .then(({ data }) => {
        if (!data) throw new Error("Detail failed");
        if (controller.signal.aborted) return;
        setSelectedDetail(data.item);
        setDetailStatus("ready");
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setSelectedDetail(null);
        setDetailStatus("error");
      });
    return () => controller.abort();
  }, [selectedId]);

  const visible = status === "ready" && settledLocation === location ? events : [];
  const searching =
    location.length !== 1 &&
    (status === "loading" || settledLocation !== location);
  const selected = visible.find((event) => event.eventId === selectedId);
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
    setFocusRequest((current) => current + 1);
    if (id === selected?.eventId) return;
    setDetailStatus("loading");
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
              ref={searchInput}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              aria-busy={location.length >= 2 && searching}
              maxLength={100}
              placeholder="Search by location (e.g. Legazpi, Albay)"
            />
            {location.length >= 2 && searching && (
              <span className="search-spinner" aria-hidden="true" />
            )}
          </label>
          <Select
            aria-label="Date observed"
            className="w-full"
            value={dateRange}
            onChange={(value) => setDateRange(String(value))}
          >
            <SelectTrigger className="filter-select-trigger">
              <Calendar
                className="filter-select-icon size-5"
                aria-hidden="true"
              />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>Date observed</SelectLabel>
                {dateOptions.map((option) => (
                  <SelectItem key={option.value} id={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
          <Select
            aria-label="Minimum magnitude"
            className="w-full"
            value={minMagnitude || "all"}
            onChange={(value) =>
              setMinMagnitude(value === "all" ? "" : String(value))
            }
          >
            <SelectTrigger className="filter-select-trigger">
              <Stone
                className="filter-select-icon size-5"
                aria-hidden="true"
              />
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                <SelectLabel>Minimum magnitude</SelectLabel>
                {magnitudeOptions.map((option) => (
                  <SelectItem key={option.value} id={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>

        <div className="content-grid">
          <section className="events-panel" aria-labelledby="events-title">
            <div className="events-head">
              <div>
                <h1 id="events-title">Earthquakes</h1>
                <p>Browse observed events across the Philippines.</p>
              </div>
            </div>
            {searching && !location && (
              <>
                <span className="sr-only" role="status">Loading recent earthquakes…</span>
                <div className="event-list event-list-skeleton" aria-label="Recent earthquakes" aria-busy="true">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div className="event-row event-row-v2 event-row-skeleton" key={index} aria-hidden="true">
                      <span className="row-v2-measure">
                        <Skeleton className="h-6 w-12" />
                        <Skeleton className="h-3 w-14" />
                      </span>
                      <span className="row-v2-detail">
                        <Skeleton className="h-4 w-4/5" />
                        <Skeleton className="h-3 w-3/5" />
                        <Skeleton className="h-3 w-16" />
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {location.length === 1 && (
              <div className="notice" role="status">
                Enter at least 2 characters to search locations.
              </div>
            )}
            {status === "error" && settledLocation === location && (
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
            {status === "ready" && settledLocation === location && !visible.length && !location && (
              <div className="notice" role="status">
                No earthquake information is available right now.
              </div>
            )}
            {status === "ready" && settledLocation === location && !visible.length && location && (
              <div className="search-empty-state">
                <p role="status">No earthquakes found</p>
                <button
                  className="clear-search-button"
                  type="button"
                  onClick={() => {
                    setQuery("");
                    searchInput.current?.focus();
                  }}
                >
                  Clear search
                </button>
              </div>
            )}
            {visible.length > 0 && (
              <div
                id="event-list"
                className="event-list"
                aria-label={location ? "Earthquake search results" : "Recent earthquakes"}
              >
                {renderRows()}
                {(nextCursor || pageStatus === "error") && (
                  <div className="load-more">
                    {pageStatus === "error" && (
                      <p role="alert">Could not load more earthquakes. Please try again.</p>
                    )}
                    <a
                      className="load-more-link"
                      href="#event-list"
                      aria-controls="event-list"
                      aria-disabled={pageStatus === "loading"}
                      onClick={(event) => {
                        event.preventDefault();
                        if (pageStatus !== "loading") void loadMore();
                      }}
                    >
                      {pageStatus === "loading"
                        ? "Loading more earthquakes…"
                        : pageStatus === "error"
                          ? "Try again"
                          : "Load more earthquakes"}
                    </a>
                  </div>
                )}
              </div>
            )}
          </section>
          <MapPanel
            events={visible}
            selectedId={selected?.eventId ?? null}
            focusRequest={focusRequest}
            forecast={
              selected && selectedDetail?.eventId === selected.eventId
                ? selectedDetail.forecast
                : null
            }
            forecastStatus={
              selected && selectedDetail?.eventId === selected.eventId
                ? "ready"
                : detailStatus === "error"
                  ? "error"
                  : "loading"
            }
            onSelect={selectEvent}
          />
        </div>
      </main>
    </div>
  );
}
