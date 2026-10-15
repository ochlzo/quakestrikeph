import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type Ref } from "react";
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
import ForecastOverview from "./ForecastOverview";
import BulletinLayout from "./BulletinLayout";
import { useIsMobile } from "../hooks/use-mobile";
import MagnitudeFilter from "./MagnitudeFilter";
import { magnitudeBand } from "../lib/magnitude";
import type { components } from "../lib/api/schema";
import type { BulletinState } from "../lib/bulletin-navigation";
import { useEventResults } from "../features/event-results/useEventResults";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerTitle,
  DrawerTrigger,
} from "@/components/ui/drawer";
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
import {
  Pagination, PaginationContent, PaginationItem,
  PaginationPrevious, PaginationNext,
} from "@/components/ui/pagination";
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
import { displayTime, locationLabel, magnitude } from "../lib/events";
import type { Earthquake } from "../lib/events";

function SelectedEarthquakeCard({ event, sourceUrl, forecastHref, ref, className = "" }: {
  event: Earthquake;
  sourceUrl?: string;
  forecastHref: string;
  ref?: Ref<HTMLElement>;
  className?: string;
}) {
  return (
    <article ref={ref} className={`selected-card ${className}`} aria-label="Selected earthquake">
      <div className="card-top">
        <div className={`selected-mag magnitude-value ${magnitudeBand(event.magnitude).className}`}>
          {magnitude(event.magnitude)}
        </div>
        <time dateTime={event.eventTime}>{displayTime(event.eventTime)}</time>
      </div>
      <h2>{locationLabel(event.locationDescription)}</h2>
      <div className="card-bottom" data-base-ui-swipe-ignore>
        <div className="selected-facts">
          <span>
            <small>Depth</small>
            <strong>{event.depthKm === null ? "Unknown" : `${event.depthKm} km`}</strong>
          </span>
          <span className="fact-source">
            <small>Source</small>
            {sourceUrl ? (
              <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
                PHIVOLCS <ExternalLink size={17} aria-hidden="true" />
              </a>
            ) : <strong>PHIVOLCS</strong>}
          </span>
        </div>
        <a className="forecast-link" href={forecastHref} data-astro-reload>
          View forecast <ArrowRight size={22} aria-hidden="true" />
        </a>
      </div>
    </article>
  );
}

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
  if (!year)
    return `${formatCalendarDate(start, false)} - ${formatCalendarDate(end, false)}`;
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

function DateFilterText({
  text,
  compactText = text,
}: {
  text: string;
  compactText?: string;
}) {
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
      <span
        ref={ref}
        className="absolute invisible pointer-events-none"
        aria-hidden="true"
      >
        {text}
      </span>
      {compact ? compactText : text}
    </span>
  );
}

export default function Bulletin({
  initialResults = null,
  initialState = {
    query: "",
    date: { value: "all" },
    magnitudes: [],
    selectedId: null,
  },
}: {
  initialResults?: components["schemas"]["SearchResponse"] | null;
  initialState?: BulletinState;
}) {
  const {
    state: { query, date: dateFilter, magnitudes: magnitudeFilter },
    events: visible,
    selected,
    selectedDetail,
    detailStatus,
    searching,
    resultsCurrent,
    failed,
    canLoadMore,
    pageStatus,
    previousId,
    changeFilters,
    select,
    refresh,
    pageNumber,
    pageSize,
    nextPage,
    previousPage,
    changePageSize,
  } = useEventResults(initialState, initialResults);
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.get("preferences") !== "saved") return;
    toast.add({
      type: "success",
      title: "Alert preferences saved.",
      description: "Automatic alert delivery is not yet available.",
    });
    url.searchParams.delete("preferences");
    window.history.replaceState(window.history.state, "", url);
  }, []);
  const mobile = useIsMobile();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerSnap, setDrawerSnap] = useState<number | string | null>(0.65);
  const [drawerMode, setDrawerMode] = useState<"event" | "forecast" | "list">("event");
  const [compactHeight, setCompactHeight] = useState(240);
  const [viewportHeight, setViewportHeight] = useState(824);
  const compactSnap = `${compactHeight}px`;
  const expandedHeight = Math.max(compactHeight, Math.round(viewportHeight * 0.65));
  const drawerHeight = typeof drawerSnap === "string" ? parseFloat(drawerSnap)
    : drawerSnap !== null && drawerSnap <= 1 ? drawerSnap * viewportHeight
    : drawerSnap ?? compactHeight;
  const [drawerSummary, setDrawerSummary] = useState<HTMLDivElement | null>(null);
  const [drawerPopup, setDrawerPopup] = useState<HTMLDivElement | null>(null);
  const mapStage = useRef<HTMLDivElement>(null);
  const [customRange, setCustomRange] = useState<RangeValue<DateValue>>(() => {
    if (
      initialState.date.value === "custom" &&
      initialState.date.from &&
      initialState.date.to
    ) {
      return {
        start: parseDate(
          new Date(Date.parse(initialState.date.from) + 8 * 3600000)
            .toISOString()
            .slice(0, 10),
        ),
        end: parseDate(
          new Date(Date.parse(initialState.date.to) - 1 + 8 * 3600000)
            .toISOString()
            .slice(0, 10),
        ),
      };
    }
    const end = today("Asia/Manila");
    return { start: end.subtract({ days: 30 }), end };
  });
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarMonths, setCalendarMonths] = useState(1);
  const [focusRequest, setFocusRequest] = useState(0);
  const searchInput = useRef<HTMLInputElement>(null);
  const drawerClose = useRef<HTMLButtonElement>(null);
  const dateSelectTrigger = useRef<HTMLButtonElement>(null);
  const eventList = useRef<HTMLDivElement>(null);
  const drawerScroll = useRef<HTMLDivElement>(null);
  const drawerSwipeStart = useRef<{ x: number; y: number } | null>(null);
  const selectedCard = useRef<HTMLElement>(null);
  const pendingMapSelection = useRef<string | null>(null);
  const location = query.trim();

  useEffect(() => {
    eventList.current?.scrollTo({ top: 0 });
  }, [pageNumber, pageSize, query, dateFilter, magnitudeFilter]);

  useEffect(() => {
    setDrawerOpen(mobile && Boolean(selected));
    setDrawerMode("event");
    setDrawerSnap(compactSnap);
    setCalendarOpen(false);
    const updateViewport = () => setViewportHeight(window.innerHeight);
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, [mobile]);

  useEffect(() => {
    if (!mobile || !selected) return;
    setDrawerOpen(true);
    if (drawerMode !== "list") {
      setDrawerMode("event");
      setDrawerSnap(compactSnap);
    }
  }, [selected?.eventId]);

  useLayoutEffect(() => {
    const scroll = drawerScroll.current;
    if (!scroll) return;
    const overview = drawerMode === "forecast" && compactHeight === expandedHeight
      ? scroll.querySelector<HTMLElement>("#mobile-forecast-overview") : null;
    scroll.scrollTo({
      top: overview ? overview.getBoundingClientRect().top - scroll.getBoundingClientRect().top + scroll.scrollTop : 0,
    });
  }, [drawerMode, selected?.eventId, compactHeight, expandedHeight]);

  useLayoutEffect(() => {
    const stage = mapStage.current;
    if (!mobile || !stage || !drawerPopup) return;
    let frame = 0;
    let previousHeight = -1;
    const followDrawer = () => {
      frame = 0;
      const bounds = stage.getBoundingClientRect();
      const height = Math.min(bounds.height, Math.max(0, drawerPopup.getBoundingClientRect().top - bounds.top));
      if (height !== previousHeight) {
        stage.style.setProperty("--earthquake-map-height", `${height}px`);
        previousHeight = height;
      }
      if (drawerPopup.hasAttribute("data-swiping") || drawerPopup.getAnimations().some((animation) => animation.playState === "running")) {
        frame = requestAnimationFrame(followDrawer);
      }
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(followDrawer);
    };
    // The popup stays mounted through dismissal, so the map also follows its exit.
    stage.setAttribute("data-drawer-tracking", "");
    followDrawer();
    const mutations = new MutationObserver(schedule);
    mutations.observe(drawerPopup, {
      attributes: true,
      attributeFilter: ["style", "data-swiping", "data-starting-style", "data-ending-style"],
    });
    const resize = new ResizeObserver(schedule);
    resize.observe(stage);
    resize.observe(drawerPopup);
    drawerPopup.addEventListener("transitionrun", schedule);
    return () => {
      cancelAnimationFrame(frame);
      mutations.disconnect();
      resize.disconnect();
      drawerPopup.removeEventListener("transitionrun", schedule);
      stage.removeAttribute("data-drawer-tracking");
      stage.style.removeProperty("--earthquake-map-height");
    };
  }, [mobile, drawerPopup]);

  useLayoutEffect(() => {
    const summary = drawerSummary;
    if (!mobile || !drawerOpen || !summary) return;
    const measure = () => {
      const bottomPadding = parseFloat(getComputedStyle(summary.parentElement!).paddingBottom);
      // Include the 12px swipe handle, 44px controls, and safe-area padding.
      setCompactHeight(Math.min(Math.ceil(summary.getBoundingClientRect().height + bottomPadding) + 56, Math.round(window.innerHeight * 0.65)));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(summary);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [mobile, drawerOpen, drawerSummary]);

  useEffect(() => {
    if (drawerMode === "event") setDrawerSnap(compactSnap);
    else setDrawerSnap((snap) => drawerMode === "list" && snap === 1 ? 1 : expandedHeight);
  }, [compactSnap, drawerMode, expandedHeight]);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 640px)");
    const update = () => setCalendarMonths(media.matches ? 2 : 1);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  const activeFilterCount =
    Number(Boolean(location)) +
    Number(dateFilter.value !== "all") +
    Number(magnitudeFilter.length > 0);
  const emptyStateKind =
    activeFilterCount > 1 || magnitudeFilter.length > 0
      ? "generic"
      : location
        ? "search"
        : dateFilter.value !== "all"
          ? "date"
          : "none";
  const selectedDateLabel =
    dateFilter.value === "custom"
      ? formatCalendarRange(customRange)
      : dateOptions.find((option) => option.value === dateFilter.value)?.label;
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
  const selectedForecast = selected && selectedDetail?.eventId === selected.eventId
    ? selectedDetail.forecast : null;
  const forecastStatus = selected && selectedDetail?.eventId === selected.eventId
    ? "ready" : detailStatus === "error" ? "error" : "loading";
  const chooseDateOption = (value: string | number | null) => {
    if (value === null) return;
    if (value === "custom") {
      setCalendarOpen(true);
      return;
    }
    setCalendarOpen(false);
    changeFilters({
      date:
        value === "all"
          ? { value }
          : {
              value: String(value),
              from: new Date(
                Date.now() - Number(value) * 24 * 60 * 60 * 1000,
              ).toISOString(),
            },
    });
  };
  const chooseCustomRange = (range: RangeValue<DateValue>) => {
    setCustomRange(range);
    changeFilters({
      date: {
        value: "custom",
        from: phtDayBoundary(range.start),
        to: phtDayBoundary(range.end, true),
      },
    });
    setCalendarOpen(false);
  };
  const selectEvent = (id: string, fromMap = false) => {
    if (mobile) {
      setDrawerOpen(true);
      setDrawerMode("event");
      setDrawerSnap(compactSnap);
      setCalendarOpen(false);
    }
    pendingMapSelection.current = fromMap ? id : null;
    setFocusRequest((current) => current + 1);
    if (id === selected?.eventId) return;
    select(id);
  };
  useEffect(() => {
    if (pendingMapSelection.current !== selected?.eventId) return;
    pendingMapSelection.current = null;
    const list = eventList.current;
    const card = selectedCard.current;
    if (!list || !card) return;
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)")
      .matches
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
      !mobile && event.eventId === selected?.eventId ? (
        <SelectedEarthquakeCard
          key={event.eventId}
          ref={selectedCard}
          event={event}
          sourceUrl={sourceUrl}
          forecastHref={forecastHref}
          className={previousId !== null ? "selection-enter" : ""}
        />
      ) : (
        <Button
          key={event.eventId}
          variant="ghost"
          className={`event-row event-row-v2${event.eventId === previousId ? " selection-exit" : ""}`}
          onPress={() => selectEvent(event.eventId)}
          aria-pressed={mobile ? event.eventId === selected?.eventId : undefined}
        >
          <span className="row-v2-measure">
            <strong
              className={`magnitude-value ${magnitudeBand(event.magnitude).className}`}
            >
              {magnitude(event.magnitude)}
            </strong>
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
        <span className="sr-only">Search by Province</span>
        <input
          id="location-search"
          ref={searchInput}
          value={query}
          onChange={(event) => changeFilters({ query: event.target.value })}
          aria-busy={location.length >= 2 && searching}
          maxLength={100}
          placeholder="Search by Province (e.g. Albay)"
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
              <DateFilterText
                text={
                  dateFilter.value === "custom"
                    ? formatCalendarRange(customRange)
                    : (dateOptions.find(
                        (option) => option.value === dateFilter.value,
                      )?.label ?? "All dates")
                }
                compactText={
                  dateFilter.value === "custom"
                    ? formatCalendarRange(customRange, false)
                    : undefined
                }
              />
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
        onChange={(magnitudes) => changeFilters({ magnitudes })}
      />
    </div>
  );
  const earthquakeList = (
    <section className="events-panel" aria-labelledby="events-title">
      <div className="events-head">
        <h1 id="events-title">Earthquakes</h1>
        <div className="events-pagination">
          <div className="events-page-size">
            <span id="rows-label">Rows</span>
            <Select aria-labelledby="rows-label" value={String(pageSize)}
              onChange={(value) => { if (value !== null) changePageSize(Number(value)); }}>
              <SelectTrigger className="magnitude-filter-field events-rows-trigger">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="magnitude-filter-popover events-rows-popover" placement="bottom start">
                {[10, 30, 50, 70, 100].map((size) => (
                  <SelectItem key={size} id={String(size)}>{size}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Pagination aria-label="Earthquake pages" className="events-page-nav">
            <PaginationContent>
              <PaginationItem>
                <PaginationPrevious href="#event-list" className="events-page-arrow"
                  isDisabled={!resultsCurrent || pageNumber === 1 || pageStatus === "loading"}
                  onPress={previousPage} onClick={(event) => event.preventDefault()} />
              </PaginationItem>
              <PaginationItem>
                <span className="events-page-number" role="status" aria-live="polite">Page {pageNumber}</span>
              </PaginationItem>
              <PaginationItem>
                <PaginationNext href="#event-list" className="events-page-arrow"
                  isDisabled={!canLoadMore || pageStatus === "loading"}
                  onPress={() => { void nextPage(); }} onClick={(event) => event.preventDefault()} />
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        </div>
      </div>
      {pageStatus === "loading" && <span className="sr-only" role="status">Loading earthquake page…</span>}
      {pageStatus === "error" && (
        <div className="notice" role="alert">
          Could not load the next page.
          <Button variant="link" onPress={() => { void nextPage(); }}>Try again</Button>
        </div>
      )}
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
              location ? "Earthquake search results" : "Recent earthquakes"
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
          Enter at least 2 characters to search provinces.
        </div>
      )}
      {failed && (
        <div className="notice" role="alert">
          <p>Earthquake data is unavailable right now.</p>
          <Button className="retry-button" onPress={refresh}>
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
                  <span>
                    for “
                    {emptyStateKind === "search" ? location : selectedDateLabel}
                    ”
                  </span>
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
                changeFilters({
                  query: emptyStateKind !== "date" ? "" : query,
                  date:
                    emptyStateKind !== "search" ? { value: "all" } : dateFilter,
                  magnitudes:
                    emptyStateKind === "generic" ? [] : magnitudeFilter,
                });
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
          aria-busy={searching || pageStatus === "loading"}
          aria-label={
            location ? "Earthquake search results" : "Recent earthquakes"
          }
        >
          {renderRows()}
        </div>
      )}
    </section>
  );

  return (
    <BulletinLayout filters={filters} results={earthquakeList}>
      <div className="content-grid">
        <div className="map-stage" ref={mapStage} style={{
          "--earthquake-panel-height": mobile && drawerOpen ? `${drawerHeight}px` : "0px",
        } as CSSProperties}>
          <MapPanel
            events={visible}
            selectedId={selected?.eventId ?? null}
            focusRequest={focusRequest}
            forecast={selectedForecast}
            forecastStatus={forecastStatus}
            overviewInDrawer={mobile}
            onSelect={(id) => selectEvent(id, true)}
          />
          {mobile && (
            <Drawer
              open={drawerOpen}
              onOpenChange={(open) => {
                if (open) {
                  setDrawerMode("list");
                  setDrawerSnap(expandedHeight);
                } else setCalendarOpen(false);
                setDrawerOpen(open);
              }}
              modal={false}
              disablePointerDismissal
              snapPoints={drawerMode === "list" ? [expandedHeight, 1]
                : expandedHeight > compactHeight ? [compactSnap, expandedHeight] : [compactSnap]}
              snapPoint={drawerSnap}
              onSnapPointChange={(snap, details) => {
                setDrawerSnap(snap);
                if (drawerMode !== "list" && selected) {
                  if (expandedHeight > compactHeight) {
                    setDrawerMode(snap === compactSnap ? "event" : "forecast");
                  } else if (snap !== null && details.reason === "swipe"
                    && details.event.type !== "pointercancel" && details.event.type !== "touchcancel") {
                    // At the height cap, a swipe changes content without changing height.
                    const start = drawerSwipeStart.current;
                    const release = "changedTouches" in details.event ? details.event.changedTouches[0]
                      : "clientY" in details.event ? details.event : null;
                    if (start && release) {
                      const deltaY = release.clientY - start.y;
                      if (Math.abs(deltaY) >= 24 && Math.abs(deltaY) > Math.abs(release.clientX - start.x)) {
                        setDrawerMode(deltaY < 0 ? "forecast" : "event");
                      }
                    }
                  }
                }
                drawerSwipeStart.current = null;
              }}
              showSwipeHandle
            >
              <DrawerTrigger
                className={buttonVariants({
                  className: "earthquake-drawer-trigger",
                })}
              >
                <ListCollapse aria-hidden="true" />
                Show earthquakes
              </DrawerTrigger>
              <DrawerContent
                ref={setDrawerPopup}
                className="earthquake-drawer"
                initialFocus={false}
                onPointerDownCapture={(event) => {
                  drawerSwipeStart.current = event.isPrimary ? { x: event.clientX, y: event.clientY } : null;
                }}
                onTouchStartCapture={(event) => {
                  const touch = event.touches.length === 1 ? event.touches[0] : null;
                  drawerSwipeStart.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
                }}
                aria-keyshortcuts={selected && drawerMode !== "list" ? "ArrowUp ArrowDown" : undefined}
                onKeyDown={(event) => {
                  if (!selected || drawerMode === "list" || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
                  if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
                  event.preventDefault();
                  const expand = event.key === "ArrowUp";
                  setDrawerMode(expand ? "forecast" : "event");
                  setDrawerSnap(expand ? expandedHeight : compactSnap);
                }}
              >
                <DrawerTitle className="sr-only">
                  Selected earthquake and earthquake search
                </DrawerTitle>
                <DrawerDescription className="sr-only">
                  Read the selected earthquake. Swipe up for its forecast overview, or use the Up and Down arrow keys. Use the list control to search earthquakes.
                </DrawerDescription>
                <div className="earthquake-drawer-actions" data-base-ui-swipe-ignore>
                  <button
                    type="button"
                    className={buttonVariants({
                      variant: "ghost",
                      size: "icon",
                    })}
                    aria-label={
                      drawerMode !== "list"
                        ? "Show earthquake list"
                        : drawerSnap === 1
                        ? "Collapse earthquake drawer"
                        : "Expand earthquake drawer"
                    }
                    onClick={() => {
                      if (drawerMode !== "list") {
                        setDrawerMode("list");
                        setDrawerSnap(expandedHeight);
                        setCalendarOpen(false);
                      } else setDrawerSnap(drawerSnap === 1 ? expandedHeight : 1);
                    }}
                  >
                    <ChevronsUpDown aria-hidden="true" />
                  </button>
                  <DrawerClose
                    ref={drawerClose}
                    className={buttonVariants({
                      variant: "ghost",
                      size: "icon",
                    })}
                    aria-label="Close earthquakes"
                  >
                    <X aria-hidden="true" />
                  </DrawerClose>
                </div>
                <div className="earthquake-drawer-scroll" ref={drawerScroll}>
                  {selected && drawerMode !== "list" && (
                    <div className="earthquake-drawer-summary" ref={setDrawerSummary}>
                      <SelectedEarthquakeCard event={selected} sourceUrl={sourceUrl} forecastHref={forecastHref} />
                    </div>
                  )}
                  {selected && (
                    <section id="mobile-forecast-overview" aria-label="Forecast overview" hidden={drawerMode !== "forecast"}>
                      <ForecastOverview forecast={selectedForecast} status={forecastStatus} />
                    </section>
                  )}
                  <div id="mobile-earthquake-list" hidden={drawerMode !== "list"}>
                    {filters}
                    {earthquakeList}
                  </div>
                </div>
              </DrawerContent>
            </Drawer>
          )}
        </div>
      </div>
    </BulletinLayout>
  );
}
