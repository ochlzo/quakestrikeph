import type { Earthquake, EarthquakeDetail } from "./events";
import { displayTime } from "./events";
import { loadObservationWindow } from "./forecast-observations";
import { ForecastObservationCache } from "./forecast-observation-cache";
import { toast } from "../components/ui/toast";

export function initForecastActivity(
  event: EarthquakeDetail,
  showObservations: (items: Earthquake[]) => void,
) {
  if (!event.forecast) return;
  const get = <T extends HTMLElement>(id: string) =>
    document.getElementById(id) as T;
  const viewport = get<HTMLDivElement>("time-viewport");
  if (!viewport) return;
  const canvas = get<HTMLDivElement>("time-canvas");
  const replay = get<HTMLButtonElement>("replay-handle");
  const history = get<HTMLButtonElement>("history-handle");
  const play = get<HTMLButtonElement>("play");
  const status = get<HTMLSpanElement>("replay-load-status");
  const future = get<HTMLDivElement>("time-future");
  const nowLabel = get<HTMLTimeElement>("time-now");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  history.replaceChildren(replay.querySelector("svg")!.cloneNode(true));
  const start = Date.parse(event.forecast.windowStart);
  const endMinutes = (Date.parse(event.forecast.windowEnd) - start) / 60000;
  const cache = new ForecastObservationCache(start, loadObservationWindow);
  // Refresh Now during interactions rather than polling during playback.
  let availableThrough = Date.now();
  let replayTime = 0, rangeStart = 0;
  const viewSpan = 2880;
  let firstVisibleTime = -720;
  let canvasStart = -6480,
    width = 0;
  let timer: ReturnType<typeof setInterval> | null = null;
  let disposed = false,
    revision = 0;
  let loadTimer: ReturnType<typeof setTimeout> | null = null;
  let stretchTimer: ReturnType<typeof setTimeout> | null = null;
  let requested = "";
  const listeners = new AbortController();
  const options = { signal: listeners.signal };
  const date = (minutes: number) => new Date(start + minutes * 60000);
  const dateFormat = new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    weekday: "long",
    month: "short",
    day: "numeric",
  });
  const clock = new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
  const x = (minutes: number) => ((minutes - canvasStart) / viewSpan) * width;
  const viewStart = () =>
    canvasStart + (viewport.scrollLeft / width) * viewSpan;
  const nowMinutes = () => (availableThrough - start) / 60000;
  const playbackEnd = () => Math.min(endMinutes, nowMinutes());
  const rulerFraction = () => width >= 560 ? 0.75 : 0.65;
  const latestViewStart = () => nowMinutes() - viewSpan * rulerFraction();

  function releaseStretch() {
    if (stretchTimer !== null) clearTimeout(stretchTimer);
    stretchTimer = null;
    canvas.classList.remove("is-stretching");
    canvas.style.transform = "";
  }
  function resistFuture(pixels: number) {
    if (reducedMotion.matches || pixels <= 0) return;
    if (stretchTimer !== null) clearTimeout(stretchTimer);
    canvas.classList.add("is-stretching");
    canvas.style.transform = `translateX(-${Math.min(32, Math.sqrt(pixels) * 3)}px)`;
    stretchTimer = setTimeout(releaseStretch, 120);
  }
  function panBy(pixels: number) {
    availableThrough = Date.now();
    const limit = x(latestViewStart());
    const target = viewport.scrollLeft + pixels;
    viewport.scrollLeft = Math.min(target, limit);
    firstVisibleTime = viewStart();
    if (target > limit) resistFuture(target - limit);
    render();
  }

  function render() {
    const band = get<HTMLDivElement>("forecast-band");
    const left = Math.max(0, x(0)),
      right = Math.min(width * 5, x(Math.min(endMinutes, nowMinutes())));
    band.hidden = right <= left;
    band.style.left = `${left}px`;
    band.style.width = `${Math.max(0, right - left)}px`;
    band.querySelector("span")!.hidden = right - left < 140;
    const boundary = Math.max(0, Math.min(width * 5, x(nowMinutes())));
    get<HTMLDivElement>("ruler").style.width = `${boundary}px`;
    future.hidden = boundary >= width * 5;
    future.style.left = `${boundary}px`;
    future.style.setProperty("--future-copy-width", `${Math.max(70, Math.min(180, width * (1 - rulerFraction()) - 24))}px`);
    nowLabel.dateTime = new Date(availableThrough).toISOString();
    nowLabel.title = displayTime(nowLabel.dateTime);
    for (const [handle, minutes] of [
      [replay, replayTime],
      [history, rangeStart],
    ] as const) {
      const position = x(minutes);
      handle.hidden =
        position < 22 ||
        position > width * 5 - 22;
      handle.style.transform = `translate3d(${position - 22}px, 0, 0)`;
      handle.setAttribute(
        "aria-label",
        `${handle === history ? "Observation range starts" : "Replay time"}: ${displayTime(date(minutes).toISOString())}`,
      );
    }
    const trace = get<HTMLDivElement>("visible-period");
    trace.style.left = `${Math.max(0, x(rangeStart))}px`;
    trace.style.width = `${Math.max(0, Math.min(width * 5, x(replayTime)) - Math.max(0, x(rangeStart)))}px`;
  }
  function buildRuler() {
    canvas.style.width = `${width * 5}px`;
    const ruler = get<HTMLDivElement>("ruler");
    ruler.replaceChildren();
    const originHour = start / 3600000;
    // Align ticks to real Philippine clock hours, including non-midnight anchors.
    const first = Math.ceil((originHour + canvasStart / 60 + 8) / 2) * 2;
    const labelHours = width >= 560 ? 6 : 12;
    for (
      let localHour = first;
      localHour < originHour + canvasStart / 60 + 8 + 240 &&
        (localHour - 8) * 3600000 <= availableThrough;
      localHour += 2
    ) {
      const minutes = (localHour - 8 - originHour) * 60;
      const tick = document.createElement("span");
      tick.className = `ruler-tick${localHour % labelHours === 0 ? " major" : ""}${localHour % 24 === 0 ? " midnight" : ""}`;
      tick.style.left = `${x(minutes)}px`;
      if (localHour % 24 === 0) {
        const label = document.createElement("span");
        label.className = "ruler-date";
        label.textContent = dateFormat.format(date(minutes));
        tick.append(label);
      }
      if (localHour % labelHours === 0) {
        const label = document.createElement("span"),
          time = document.createElement("span"),
          offset = document.createElement("span");
        label.className = "ruler-label";
        time.className = "ruler-clock";
        offset.className = "ruler-offset";
        time.textContent = clock.format(date(minutes));
        const hours = minutes / 60;
        offset.textContent = `${hours < 0 ? "−" : hours > 0 ? "+" : ""}${new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 }).format(Math.abs(hours))}h`;
        label.append(time, offset);
        tick.append(label);
      }
      ruler.append(tick);
    }
    render();
  }
  function showTime(minutes: number) {
    const first = Math.min(minutes - viewSpan * 0.25, latestViewStart());
    firstVisibleTime = first;
    canvasStart = first - viewSpan * 2;
    buildRuler();
    viewport.scrollLeft = width * 2;
  }
  function keepInView() {
    const first = viewStart();
    if (
      replayTime < first + viewSpan * 0.08 ||
      replayTime > first + viewSpan * 0.9
    )
      showTime(replayTime);
  }
  function paintObservations() {
    const from = date(rangeStart).getTime(),
      to = date(replayTime).getTime();
    const items = cache.observations(
      from,
      Math.min(to, availableThrough),
      event.eventId,
    );
    showObservations(items);
    const complete = cache.covered(from, to, availableThrough);
    status.textContent = complete ? "" : "Loading observations…";
  }
  function loadingFailed() {
    setPlaying(false);
    paintObservations();
    status.textContent = "Observations incomplete";
    toast.add({
      id: "forecast-observations-error",
      type: "error",
      timeout: 0,
      title: "Observed earthquakes could not be loaded.",
      description:
        "Some observations are missing. Retry to load the selected period.",
      actionProps: {
        children: "Retry",
        onClick: () => {
          requested = "";
          requestObservations();
        },
      },
    });
  }
  function requestObservations(prefetch = false) {
    const from = date(rangeStart).getTime();
    const to = date(
      prefetch ? Math.min(replayTime + 120, playbackEnd()) : replayTime,
    ).getTime();
    const key = `${Math.floor((from - start) / 86400000)}:${Math.floor((to - start) / 86400000)}`;
    if (cache.covered(from, to, availableThrough) || requested === key) return;
    requested = key;
    const token = revision;
    void cache
      .ensure(from, to, availableThrough, () => !disposed && token === revision)
      .then(() => {
        if (!disposed && token === revision) {
          paintObservations();
          toast.close("forecast-observations-error");
        }
      })
      .catch(() => {
        if (!disposed && token === revision) loadingFailed();
      })
      .finally(() => {
        if (requested === key) requested = "";
      });
  }
  function setPlaying(playing: boolean) {
    if (timer !== null) clearInterval(timer);
    timer = null;
    playing = playing && replayTime < playbackEnd();
    play.setAttribute("aria-pressed", String(playing));
    play.setAttribute("aria-label", playing ? "Pause replay" : "Play replay");
    play.title = playing ? "Pause replay" : "Play replay";
    get<HTMLElement>("play-icon").toggleAttribute("hidden", playing);
    get<HTMLElement>("pause-icon").toggleAttribute("hidden", !playing);
    if (playing) {
      keepInView();
      requestObservations(true);
      timer = setInterval(() => {
        const next = Math.min(replayTime + 6, playbackEnd());
        if (
          !cache.covered(
            date(rangeStart).getTime(),
            date(next).getTime(),
            availableThrough,
          )
        ) {
          requestObservations(true);
          status.textContent = "Loading observations…";
          return;
        }
        replayTime = next;
        keepInView();
        render();
        paintObservations();
        if (replayTime >= playbackEnd()) {
          setPlaying(false);
          return;
        }
        requestObservations(true);
      }, 100);
    }
  }
  function seek(handle: HTMLButtonElement, minutes: number) {
    setPlaying(false);
    availableThrough = Date.now();
    const snapped = Math.round(minutes / 15) * 15;
    const target =
      handle === history
        ? Math.min(snapped, replayTime)
        : Math.min(Math.max(snapped, rangeStart), nowMinutes());
    if (handle === replay && snapped > nowMinutes())
      resistFuture(((snapped - nowMinutes()) / viewSpan) * width);
    if (target === (handle === history ? rangeStart : replayTime)) return;
    revision++;
    requested = "";
    if (handle === history) rangeStart = target;
    else replayTime = target;
    render();
    paintObservations();
    if (loadTimer !== null) clearTimeout(loadTimer);
    loadTimer = setTimeout(() => requestObservations(), 150);
  }
  const dragFrames = new Set<number>();
  for (const handle of [replay, history]) {
    let pointer: number | null = null,
      lastX = 0,
      offset = 0,
      frame = 0;
    function drag() {
      dragFrames.delete(frame);
      if (pointer === null) return;
      const rect = viewport.getBoundingClientRect();
      if (lastX < rect.left + 30) panBy(-10);
      if (lastX > rect.right - 30) panBy(10);
      seek(
        handle,
        canvasStart +
          ((viewport.scrollLeft + lastX - rect.left - offset) / width) *
            viewSpan,
      );
      frame = requestAnimationFrame(drag);
      dragFrames.add(frame);
    }
    handle.addEventListener(
      "pointerdown",
      (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        pointer = event.pointerId;
        lastX = event.clientX;
        offset =
          lastX -
          viewport.getBoundingClientRect().left -
          (x(handle === history ? rangeStart : replayTime) -
            viewport.scrollLeft);
        handle.classList.add("pointer-focus");
        handle.focus({ preventScroll: true });
        handle.setPointerCapture(pointer);
        frame = requestAnimationFrame(drag);
        dragFrames.add(frame);
      },
      options,
    );
    handle.addEventListener(
      "pointermove",
      (event) => {
        if (pointer === event.pointerId) lastX = event.clientX;
      },
      options,
    );
    const endDrag = () => {
      releaseStretch();
      pointer = null;
      cancelAnimationFrame(frame);
      dragFrames.delete(frame);
    };
    for (const name of ["pointerup", "pointercancel", "lostpointercapture"])
      handle.addEventListener(name, endDrag, options);
    handle.addEventListener(
      "blur",
      () => handle.classList.remove("pointer-focus"),
      options,
    );
    handle.addEventListener(
      "keydown",
      (event) => {
        handle.classList.remove("pointer-focus");
        const step = event.shiftKey ? 60 : 15;
        const changes: Record<string, number> = {
          ArrowLeft: -step,
          ArrowDown: -step,
          ArrowRight: step,
          ArrowUp: step,
          PageUp: -1440,
          PageDown: 1440,
        };
        if (!(event.key in changes)) return;
        event.preventDefault();
        event.stopPropagation();
        seek(
          handle,
          (handle === history ? rangeStart : replayTime) + changes[event.key],
        );
        showTime(handle === history ? rangeStart : replayTime);
      },
      options,
    );
  }
  let panPointer: number | null = null,
    panX = 0;
  viewport.addEventListener(
    "pointerdown",
    (event) => {
      if (
        event.button !== 0 ||
        (event.target as Element).closest("button")
      )
        return;
      if (event.pointerType === "mouse") event.preventDefault();
      panPointer = event.pointerId;
      panX = event.clientX;
      viewport.setPointerCapture(panPointer);
      viewport.classList.add("is-dragging");
    },
    options,
  );
  viewport.addEventListener(
    "pointermove",
    (event) => {
      if (event.pointerId !== panPointer) return;
      panBy(panX - event.clientX);
      panX = event.clientX;
    },
    options,
  );
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"])
    viewport.addEventListener(
      name,
      () => {
        panPointer = null;
        releaseStretch();
        viewport.classList.remove("is-dragging");
      },
      options,
    );
  viewport.addEventListener(
    "wheel",
    (event) => {
      if (!event.deltaX && !event.shiftKey) return;
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? width : 1;
      panBy((event.deltaX || event.deltaY) * unit);
    },
    { ...options, passive: false },
  );
  viewport.addEventListener(
    "scroll",
    () => {
      if (!width || width !== viewport.clientWidth) return;
      const limit = x(latestViewStart());
      if (viewport.scrollLeft > limit) {
        resistFuture(viewport.scrollLeft - limit);
        viewport.scrollLeft = limit;
      }
      firstVisibleTime = viewStart();
      if (
        width &&
        (viewport.scrollLeft < width * 0.5 || viewport.scrollLeft > width * 3.5)
      ) {
        canvasStart = firstVisibleTime - viewSpan * 2;
        buildRuler();
        viewport.scrollLeft = width * 2;
      }
    },
    options,
  );
  viewport.addEventListener(
    "keydown",
    (event) => {
      const changes: Record<string, number> = {
        ArrowLeft: -360,
        ArrowRight: 360,
        PageUp: -1440,
        PageDown: 1440,
      };
      if (!(event.key in changes) || event.target !== viewport) return;
      event.preventDefault();
      availableThrough = Date.now();
      const first = viewStart() + changes[event.key];
      if (first > latestViewStart())
        resistFuture(((first - latestViewStart()) / viewSpan) * width);
      showTime(first + viewSpan * 0.25);
    },
    options,
  );
  const resize = new ResizeObserver(() => {
    width = viewport.clientWidth;
    if (width) showTime(firstVisibleTime + viewSpan * 0.25);
  });
  resize.observe(viewport);
  play.addEventListener(
    "click",
    () => {
      availableThrough = Date.now();
      buildRuler();
      setPlaying(timer === null);
    },
    options,
  );
  get<HTMLButtonElement>("reset").addEventListener(
    "click",
    () => {
      setPlaying(false);
      revision++;
      requested = "";
      availableThrough = Date.now();
      replayTime = rangeStart = 0;
      showTime(0);
      paintObservations();
      requestObservations();
    },
    options,
  );
  document.addEventListener(
    "visibilitychange",
    () => {
      if (document.hidden) setPlaying(false);
    },
    options,
  );
  window.addEventListener("pagehide", () => setPlaying(false), options);
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) releaseStretch();
  }, options);
  void cache
    .ensure(start, start + 86400000 - 1, availableThrough)
    .then(() => {
      if (!disposed) {
        play.disabled = false;
        paintObservations();
      }
    })
    .catch(() => {
      if (!disposed) {
        play.disabled = false;
        if (revision === 0) loadingFailed();
      }
    });
  return () => {
    disposed = true;
    revision++;
    setPlaying(false);
    listeners.abort();
    resize.disconnect();
    if (loadTimer !== null) clearTimeout(loadTimer);
    releaseStretch();
    dragFrames.forEach((frame) => cancelAnimationFrame(frame));
  };
}
