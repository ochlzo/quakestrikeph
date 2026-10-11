import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { toast } from "./ui/toast";
import { parseDate, today } from "@internationalized/date";
import { Dialog, type DateValue, type RangeValue } from "react-aria-components";
import {
  ArrowRight,
  ChevronRight,
  ChevronsUpDown,
  ListCollapse,
  X,
  Earth,
  ExternalLink,
  Search,
} from "lucide-react";
import MapPanel from "./MapPanel";
import BulletinLayout from "./BulletinLayout";
import { useIsMobile } from "../hooks/use-mobile";
import MagnitudeFilter from "./MagnitudeFilter";
import { magnitudeBand, magnitudeRangesForBands } from "../lib/magnitude";
import { bulletinApi } from "../lib/api/client";
import type { components } from "../lib/api/schema";
import { readEarthquakeCache, writeEarthquakeCache, type EarthquakeSearch } from "../lib/earthquake-cache";
import { bulletinParams, matchesBulletinFilters, type BulletinState, type DateFilter } from "../lib/bulletin-navigation";
import { Button, buttonVariants } from "@/components/ui/button";
import { Drawer, DrawerClose, DrawerContent, DrawerDescription, DrawerTitle, DrawerTrigger } from "@/components/ui/drawer";
import { RangeCalendar } from "@/components/ui/calendar";
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import { Popover } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  displayTime,
  locationLabel,
  magnitude,
  type Earthquake,
  type EarthquakeDetail,
} from "../lib/events";

const dateOptions = [
  { label: "All dates", value: "all" },
  { label: "Last 24 hours", value: "1" },
  { label: "Last 7 days", value: "7" },
  { label: "Last 30 days", value: "30" },
];

function formatDate(date: Date, year = true) {
  return new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    month: "short",
    day: "numeric",
    ...(year ? { year: "numeric" } : {}),
  }).format(date);
}

function formatCalendarDate(date: DateValue, year = true) {
  return formatDate(
    new Date(Date.UTC(date.year, date.month - 1, date.day, 12)),
    year,
  );
}

function formatCalendarRange(range: RangeValue<DateValue>, year = true) {
  const { start, end } = range;
  if (start.compare(end) === 0) return formatCalendarDate(start, year);
  if (!year) return `${formatCalendarDate(start, false)} - ${formatCalendarDate(end, false)}`;
  if (start.year !== end.year) {
    return `${formatCalendarDate(start)} - ${formatCalendarDate(end)}`;
  }
  return `${formatCalendarDate(start, false)} - ${formatCalendarDate(end)}`;
}

function phtDayBoundary(date: DateValue, nextDay = false) {
  return new Date(
    Date.UTC(date.year, date.month - 1, date.day + Number(nextDay)) -
      8 * 60 * 60 * 1000,
  ).toISOString();
}

function DateFilterText({ text, compactText = text }: { text: string; compactText?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [compact, setCompact] = useState(false);

  useLayoutEffect(() => {
    const label = ref.current;
    const field = label?.parentElement?.parentElement;
    if (!label || !field) return;
    let active = true;

    const fit = () => {
      if (!active || !field.clientWidth) return;
      setCompact(label.getBoundingClientRect().width > field.clientWidth);
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(field);
    void document.fonts.ready.then(fit);
    return () => {
      active = false;
      observer.disconnect();
    };
  }, [text]);

  return (
    <span className="filter-value-text" title={text}>
      <span ref={ref} className="absolute invisible pointer-events-none" aria-hidden="true">{text}</span>
      {compact ? compactText : text}
    </span>
  );
}

export default function Bulletin({ initialResults = null, initialState = { query: '', date: { value: 'all' }, magnitudes: [], selectedId: null } }: {
  initialResults?: components["schemas"]["SearchResponse"] | null;
  initialState?: BulletinState;
}) {
  const initialPage = useRef(initialResults);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get('preferences') !== 'saved') return;
    toast.add({ type: 'success', title: 'Alert preferences saved.', description: 'Automatic alert delivery is not yet available.' });
    url.searchParams.delete('preferences');
    window.history.replaceState(window.history.state, '', url);
  }, []);
  const mobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSnap, setDrawerSnap] = useState<number | string | null>(0.65);
  const [query, setQuery] = useState(initialState.query);
  const [dateFilter, setDateFilter] = useState<DateFilter>(initialState.date);
  const [settledDateFilter, setSettledDateFilter] =
    useState<DateFilter>(dateFilter);
  const [customRange, setCustomRange] = useState<RangeValue<DateValue>>(() => {
    if (initialState.date.value === 'custom' && initialState.date.from && initialState.date.to) {
      return {
        start: parseDate(new Date(Date.parse(initialState.date.from) + 8 * 3600000).toISOString().slice(0, 10)),
        end: parseDate(new Date(Date.parse(initialState.date.to) - 1 + 8 * 3600000).toISOString().slice(0, 10)),
      };
    }
    const end = today("Asia/Manila");
    return { start: end.subtract({ days: 30 }), end };
  });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarMonths, setCalendarMonths] = useState(1);
  const [magnitudeFilter, setMagnitudeFilter] = useState<string[]>(initialState.magnitudes);
  const [settledMagnitudeFilter, setSettledMagnitudeFilter] = useState(magnitudeFilter);
  const [events, setEvents] = useState<Earthquake[]>(initialResults?.items ?? []);
  const [settledLocation, setSettledLocation] = useState(initialState.query.trim());
  const [selectedId, setSelectedId] = useState<string | null>(initialState.selectedId);
  const [focusRequest, setFocusRequest] = useState(0);
  const [previousId, setPreviousId] = useState<string | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<EarthquakeDetail | null>(
    null,
  );
  const [detailStatus, setDetailStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const [status, setStatus] = useState<"restoring" | "loading" | "ready" | "error">(
    initialResults ? "ready" : "restoring",
  );
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [pageStatus, setPageStatus] = useState<"idle" | "loading" | "error">(
    "idle",
  );
  const pageController = useRef<AbortController | null>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const drawerClose = useRef<HTMLButtonElement>(null);
  const dateSelectTrigger = useRef<HTMLButtonElement>(null);
  const eventList = useRef<HTMLDivElement>(null);
  const selectedCard = useRef<HTMLElement>(null);
  const pendingMapSelection = useRef<string | null>(null);
  const [requestAttempt, setRequestAttempt] = useState(0);
  const location = query.trim();
  const previousFilters = useRef({ location, dateFilter, magnitudeFilter });

  useEffect(() => {
    const previous = previousFilters.current;
    if (previous.location !== location || previous.dateFilter !== dateFilter || previous.magnitudeFilter !== magnitudeFilter) {
      setSelectedId(null);
      setPreviousId(null);
    }
    previousFilters.current = { location, dateFilter, magnitudeFilter };
  }, [location, dateFilter, magnitudeFilter]);

  useEffect(() => {
    const url = new URL(window.location.href);
    for (const key of ['q', 'date', 'from', 'to', 'magnitudes', 'selected']) url.searchParams.delete(key);
    bulletinParams({ query, date: dateFilter, magnitudes: magnitudeFilter, selectedId }).forEach((value, key) => url.searchParams.set(key, value));
    window.history.replaceState(window.history.state, '', url);
  }, [query, dateFilter, magnitudeFilter, selectedId]);

  useEffect(() => () => pageController.current?.abort(), []);
  useEffect(() => {
    const refreshRestoredPage = (event: PageTransitionEvent) => {
      if (event.persisted) setRequestAttempt((attempt) => attempt + 1);
    };
    window.addEventListener("pageshow", refreshRestoredPage);
    return () => window.removeEventListener("pageshow", refreshRestoredPage);
  }, []);

  useEffect(() => {
    setDrawerOpen(false);
    setCalendarOpen(false);
  }, [mobile]);


  useEffect(() => {
    const media = window.matchMedia("(min-width: 640px)");
    const update = () => setCalendarMonths(media.matches ? 2 : 1);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    pageController.current?.abort();
    pageController.current = null;
    setPageStatus("idle");
    setNextCursor(null);

    if (location.length === 1) return () => controller.abort();

    const search: EarthquakeSearch = {
      limit: 30,
      location: location || undefined,
      dateFrom: dateFilter.from,
      dateTo: dateFilter.to,
      magnitudeRanges: magnitudeRangesForBands(magnitudeFilter),
    };
    const initial = initialPage.current;
    initialPage.current = null;
    const cached = initial ? null : readEarthquakeCache(search);
    if (initial) writeEarthquakeCache(search, initial);
    if (cached) {
      setEvents(cached.items);
      setSettledLocation(location);
      setSettledDateFilter(dateFilter);
      setSettledMagnitudeFilter(magnitudeFilter);
      setStatus("ready");
    } else if (!initial) setStatus("loading");

    async function loadEvents() {
      try {
        const { data } = await bulletinApi.POST("/earthquakes/search", {
          body: search,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!data) throw new Error("Search failed");
        writeEarthquakeCache(search, data);
        setEvents((current) => JSON.stringify(current) === JSON.stringify(data.items) ? current : data.items);
        setNextCursor(data.nextCursor);
        setSettledLocation(location);
        setSettledDateFilter(dateFilter);
        setSettledMagnitudeFilter(magnitudeFilter);
        setPreviousId(null);
        setStatus("ready");
      } catch {
        if (!controller.signal.aborted) {
          if (cached || initial) {
            toast.add({ type: "error", title: "Earthquakes could not be refreshed.", description: "Showing saved results. Reload to try again." });
            return;
          }
          setSettledLocation(location);
          setSettledDateFilter(dateFilter);
          setSettledMagnitudeFilter(magnitudeFilter);
          setStatus("error");
        }
      }
    }

    const timer = window.setTimeout(
      () => void loadEvents(),
      location || magnitudeFilter !== settledMagnitudeFilter ? 300 : 0,
    );
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [location, dateFilter, magnitudeFilter, requestAttempt]);

  async function loadMore() {
    if (
      !nextCursor ||
      pageController.current ||
      status !== "ready" ||
      settledLocation !== location ||
      settledDateFilter !== dateFilter ||
      settledMagnitudeFilter !== magnitudeFilter
    )
      return;
    const controller = new AbortController();
    pageController.current = controller;
    setPageStatus("loading");
    try {
      const { data } = await bulletinApi.POST("/earthquakes/search", {
        body: {
          limit: 30,
          cursor: nextCursor,
          location: location || undefined,
          dateFrom: dateFilter.from,
          dateTo: dateFilter.to,
          magnitudeRanges: magnitudeRangesForBands(magnitudeFilter),
        },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!data) throw new Error("Search failed");
      setEvents((current) => {
        const seen = new Set(current.map((event) => event.eventId));
        return [
          ...current,
          ...data.items.filter((event) => !seen.has(event.eventId)),
        ];
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
    bulletinApi
      .GET("/earthquakes/{eventId}", {
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

  const resultsCurrent =
    status === "ready" &&
    settledLocation === location &&
    settledDateFilter === dateFilter &&
    settledMagnitudeFilter === magnitudeFilter;
  // A restored selection can be older than the first search page.
  const restoredSelection = selectedDetail && selectedDetail.eventId === selectedId &&
    !events.some(event => event.eventId === selectedId) &&
    matchesBulletinFilters(selectedDetail, { query, date: dateFilter, magnitudes: magnitudeFilter, selectedId })
      ? selectedDetail : null;
  const visible = resultsCurrent ? (restoredSelection ? [...events, restoredSelection] : events) : [];
  const searching =
    location.length !== 1 &&
    (status === "loading" ||
      settledLocation !== location ||
      settledDateFilter !== dateFilter ||
      settledMagnitudeFilter !== magnitudeFilter);
  const activeFilterCount = Number(Boolean(location)) +
    Number(dateFilter.value !== "all") + Number(magnitudeFilter.length > 0);
  const emptyStateKind = activeFilterCount > 1 || magnitudeFilter.length > 0
    ? "generic"
    : location
      ? "search"
      : dateFilter.value !== "all"
        ? "date"
        : "none";
  const selectedDateLabel = dateFilter.value === "custom"
    ? formatCalendarRange(customRange)
    : dateOptions.find((option) => option.value === dateFilter.value)?.label;
  const selected = visible.find((event) => event.eventId === selectedId);
  const sourceUrl =
    selectedDetail &&
    selected &&
    selectedDetail.eventId === selected.eventId &&
    /^https?:\/\//i.test(selectedDetail.source?.url ?? "")
      ? selectedDetail.source?.url
      : undefined;
  const forecastHref = selected
    ? `/forecasts/${encodeURIComponent(selected.eventId)}`
    : "/";
  const chooseDateOption = (value: string | number | null) => {
    if (value === null) return;
    if (value === "custom") {
      setCalendarOpen(true);
      return;
    }
    setCalendarOpen(false);
    setDateFilter(
      value === "all"
        ? { value }
        : {
            value: String(value),
            from: new Date(
              Date.now() - Number(value) * 24 * 60 * 60 * 1000,
            ).toISOString(),
          },
    );
  };
  const chooseCustomRange = (range: RangeValue<DateValue>) => {
    setCustomRange(range);
    setDateFilter({
      value: "custom",
      from: phtDayBoundary(range.start),
      to: phtDayBoundary(range.end, true),
    });
    setCalendarOpen(false);
  };
  const selectEvent = (id: string, fromMap = false) => {
    pendingMapSelection.current = fromMap ? id : null;
    setFocusRequest((current) => current + 1);
    if (id === selected?.eventId) return;
    setDetailStatus("loading");
    setPreviousId(selected?.eventId ?? null);
    setSelectedId(id);
  };
  useEffect(() => {
    if (pendingMapSelection.current !== selected?.eventId) return;
    pendingMapSelection.current = null;
    const list = eventList.current;
    const card = selectedCard.current;
    if (!list || !card) return;
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth";
    if (window.matchMedia("(max-width: 760px)").matches) {
      if (drawerOpen) card.scrollIntoView({ block: "nearest", behavior });
      return;
    }
    const listBounds = list.getBoundingClientRect();
    const cardBounds = card.getBoundingClientRect();
    list.scrollTo({
      top:
        list.scrollTop +
        cardBounds.top -
        listBounds.top +
        (cardBounds.height - listBounds.height) / 2,
      behavior,
    });
  }, [focusRequest, selected?.eventId, drawerOpen]);

  const renderRows = () =>
    visible.map((event) =>
      event.eventId === selected?.eventId ? (
        <article
          key={event.eventId}
          ref={selectedCard}
          className={`selected-card${previousId !== null ? " selection-enter" : ""}`}
          aria-label="Selected earthquake"
        >
          <div className="card-top">
            <div className={`selected-mag magnitude-value ${magnitudeBand(event.magnitude).className}`}>{magnitude(event.magnitude)}</div>
            <time dateTime={event.eventTime}>
              {displayTime(event.eventTime)}
            </time>
          </div>
          <h2>{locationLabel(event.locationDescription)}</h2>
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
            <a className="forecast-link" href={forecastHref} data-astro-reload>
              View forecast <ArrowRight size={22} aria-hidden="true" />
            </a>
          </div>
        </article>
      ) : (
        <Button
          key={event.eventId}
          variant="ghost"
          className={`event-row event-row-v2${event.eventId === previousId ? " selection-exit" : ""}`}
          onPress={() => selectEvent(event.eventId)}
        >
          <span className="row-v2-measure">
            <strong className={`magnitude-value ${magnitudeBand(event.magnitude).className}`}>{magnitude(event.magnitude)}</strong>
            <small>
              {event.depthKm === null
                ? "Unknown depth"
                : `${event.depthKm} km deep`}
            </small>
          </span>
          <span className="row-v2-detail">
            <b>{locationLabel(event.locationDescription)}</b>
            <time dateTime={event.eventTime}>
              {displayTime(event.eventTime)}
            </time>
          </span>
          <ChevronRight aria-hidden="true" />
        </Button>
      ),
    );

  const filters = (
    <div className="filter-bar" aria-label="Earthquake filters">
      <label className="search-field">
        <Search size={20} aria-hidden="true" />
        <span className="sr-only">Search by location</span>
        <input
          id="location-search"
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
        value={dateFilter.value}
        onChange={chooseDateOption}
      >
        <SelectTrigger
          ref={dateSelectTrigger}
          className="filter-select-trigger date-filter-trigger"
        >
          <SelectValue className="filter-scroll-value">
            {() => (
              <DateFilterText text={dateFilter.value === "custom"
                ? formatCalendarRange(customRange)
                : dateOptions.find((option) => option.value === dateFilter.value)?.label ?? "All dates"}
                compactText={dateFilter.value === "custom" ? formatCalendarRange(customRange, false) : undefined} />
            )}
          </SelectValue>
        </SelectTrigger>
        <SelectContent className="date-filter-popover">
          <SelectGroup>
            <SelectLabel>Date observed</SelectLabel>
            {dateOptions.map((option) => (
              <SelectItem key={option.value} id={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator />
          <SelectGroup>
            <SelectLabel>Custom date range</SelectLabel>
            <SelectItem id="custom" onClick={() => setCalendarOpen(true)}>
              {formatCalendarRange(customRange)}
            </SelectItem>
          </SelectGroup>
        </SelectContent>
      </Select>
      <Popover
        triggerRef={dateSelectTrigger}
        isOpen={calendarOpen}
        onOpenChange={setCalendarOpen}
        placement="bottom start"
        className="w-auto max-w-[calc(100vw-24px)] p-1"
      >
        <Dialog
          aria-label="Choose custom date range"
          className="date-range-dialog"
        >
          <RangeCalendar
            aria-label="Earthquake date range"
            value={customRange}
            onChange={chooseCustomRange}
            numberOfMonths={calendarMonths}
          />
        </Dialog>
      </Popover>
      <MagnitudeFilter
        value={magnitudeFilter}
        onChange={(keys) => setMagnitudeFilter((current) =>
          current.length === keys.length && current.every((key, index) => key === keys[index])
            ? current
            : keys,
        )}
      />
    </div>
  );
  const earthquakeList = (
    <section className="events-panel" aria-labelledby="events-title">
      <div className="events-head">
        <div>
          <h1 id="events-title">Earthquakes</h1>
          <p>Browse observed events across the Philippines.</p>
        </div>
      </div>
      {searching && (
        <>
          <span className="sr-only" role="status">
            {location
              ? "Searching earthquakes…"
              : "Loading recent earthquakes…"}
          </span>
          <div
            className="event-list event-list-skeleton"
            aria-label={
              location
                ? "Earthquake search results"
                : "Recent earthquakes"
            }
            aria-busy="true"
          >
            {Array.from({ length: 6 }, (_, index) => (
              <div
                className="event-row event-row-v2 event-row-skeleton"
                key={index}
                aria-hidden="true"
              >
                <span className="row-v2-measure">
                  <Skeleton className="h-6 w-12" />
                  <Skeleton className="h-3 w-14" />
                </span>
                <span className="row-v2-detail">
                  <Skeleton className="h-4 w-4/5" />
                  <Skeleton className="h-3 w-3/5" />
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
      {status === "error" &&
        settledLocation === location &&
        settledDateFilter === dateFilter &&
        settledMagnitudeFilter === magnitudeFilter && (
          <div className="notice" role="alert">
            <p>Earthquake data is unavailable right now.</p>
            <Button
              className="retry-button"
              onPress={() => setRequestAttempt((attempt) => attempt + 1)}
            >
              Try again
            </Button>
          </div>
        )}
      {resultsCurrent && !visible.length && emptyStateKind === "none" && (
        <div className="notice" role="status">
          No earthquake information is available right now.
        </div>
      )}
      {resultsCurrent && !visible.length && emptyStateKind !== "none" && (
        <Empty className="search-empty-state">
          <EmptyHeader>
            <EmptyMedia>
              <Earth size={30} strokeWidth={1.8} aria-hidden="true" />
            </EmptyMedia>
            <EmptyTitle role="status">
              {emptyStateKind === "generic" ? (
                "No earthquake found"
              ) : (
                <>
                  No earthquakes found
                  <span>for “{emptyStateKind === "search" ? location : selectedDateLabel}”</span>
                </>
              )}
            </EmptyTitle>
            <EmptyDescription>
              {emptyStateKind === "generic"
                ? "Try a different location, date range, or magnitude."
                : emptyStateKind === "date"
                  ? "Try widening the date range to see more earthquakes."
                  : "Try searching for provinces like “Albay”."}
            </EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button
              variant="outline"
              className="clear-search-button"
              onPress={() => {
                if (emptyStateKind !== "date") setQuery("");
                if (emptyStateKind !== "search") setDateFilter({ value: "all" });
                if (emptyStateKind === "generic") setMagnitudeFilter([]);
                if (emptyStateKind === "search") searchInput.current?.focus();
              }}
            >
              {emptyStateKind === "generic"
                ? "Clear filters"
                : emptyStateKind === "search"
                  ? "Clear search"
                  : "Clear date filter"}
            </Button>
          </EmptyContent>
        </Empty>
      )}
      {visible.length > 0 && (
        <div
          id="event-list"
          ref={eventList}
          className="event-list"
          aria-busy={searching}
          aria-label={
            location ? "Earthquake search results" : "Recent earthquakes"
          }
        >
          {renderRows()}
          {resultsCurrent && (nextCursor || pageStatus === "error") && (
            <div className="load-more">
              {pageStatus === "error" && (
                <p role="alert">
                  Could not load more earthquakes. Please try again.
                </p>
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
  );

  return (
    <BulletinLayout filters={filters} results={earthquakeList}>
      <div className="content-grid">
        <div className="map-stage">
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
            onSelect={(id) => selectEvent(id, true)}
          />
          {mobile && (
            <Drawer
              open={drawerOpen}
              onOpenChange={(open) => {
                if (open) setDrawerSnap(0.65);
                else setCalendarOpen(false);
                setDrawerOpen(open);
              }}
              snapPoints={[0.65, 1]}
              snapPoint={drawerSnap}
              onSnapPointChange={setDrawerSnap}
              showSwipeHandle
            >
              <DrawerTrigger className={buttonVariants({ className: "earthquake-drawer-trigger" })}>
                <ListCollapse aria-hidden="true" />
                Show earthquakes
              </DrawerTrigger>
              <DrawerContent className="earthquake-drawer" initialFocus={drawerClose}>
                <DrawerTitle className="sr-only">Earthquake search and results</DrawerTitle>
                <DrawerDescription className="sr-only">
                  Filter earthquakes by location, date, and magnitude. Drag the handle to expand or close.
                </DrawerDescription>
                <div className="earthquake-drawer-actions">
                  <button type="button" className={buttonVariants({ variant: "ghost", size: "icon" })}
                    aria-label={drawerSnap === 1 ? "Collapse earthquake drawer" : "Expand earthquake drawer"}
                    onClick={() => setDrawerSnap(drawerSnap === 1 ? 0.65 : 1)}>
                    <ChevronsUpDown aria-hidden="true" />
                  </button>
                  <DrawerClose ref={drawerClose} className={buttonVariants({ variant: "ghost", size: "icon" })} aria-label="Close earthquakes">
                    <X aria-hidden="true" />
                  </DrawerClose>
                </div>
                <div className="earthquake-drawer-scroll">
                  {filters}
                  {earthquakeList}
                </div>
              </DrawerContent>
            </Drawer>
          )}
        </div>
      </div>
    </BulletinLayout>
  );
}
