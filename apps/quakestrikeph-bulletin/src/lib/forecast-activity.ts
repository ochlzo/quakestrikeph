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
  const speed = get<HTMLButtonElement>("playback-speed");
  const zoom = get<HTMLButtonElement>("timeline-zoom");
  const status = get<HTMLSpanElement>("replay-load-status");
  const future = get<HTMLDivElement>("time-future");
  const nowLabel = get<HTMLTimeElement>("time-now");
  const visibleDates = get<HTMLParagraphElement>("timeline-dates");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  history.replaceChildren(replay.querySelector("svg")!.cloneNode(true));
  const start = Date.parse(event.forecast.windowStart);
  const endMinutes = (Date.parse(event.forecast.windowEnd) - start) / 60000;
  const cache = new ForecastObservationCache(start, loadObservationWindow);
  // Refresh Now during interactions rather than polling during playback.
  let availableThrough = Date.now();
  let replayTime = 0, rangeStart = 0;
  let playbackSpeed = 1;
  const zoomLevels = [360, 1440, 2880, 5760];
  const minZoomMinutes = zoomLevels[0], maxZoomMinutes = zoomLevels[3];
  let zoomMinutes = 1440, viewSpan = 1440;
  let requestedZoomMinutes = zoomMinutes;
  let zoomFrame = 0;
  let finishZoom: (() => void) | null = null;
  let playbackScrollFrame = 0;
  let fittedView = true;
  let firstVisibleTime = 0;
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
  const offsetFormat = new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 });
  const visibleDateFormat = new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", month: "long", day: "numeric",
  });
  const visibleYearFormat = new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", month: "long", day: "numeric", year: "numeric",
  });
  const yearFormat = new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", year: "numeric",
  });
  const x = (minutes: number) => ((minutes - canvasStart) / viewSpan) * width;
  const viewStart = () =>
    canvasStart + (viewport.scrollLeft / width) * viewSpan;
  const nowMinutes = () => (availableThrough - start) / 60000;
  const playbackEnd = () =>
    replayTime < endMinutes ? Math.min(endMinutes, nowMinutes()) : nowMinutes();
  const rulerFraction = () => width >= 560 ? 0.75 : 0.65;
  const edgeMinutes = () => 8 * viewSpan / width;
  const latestViewStart = () => Math.max(-edgeMinutes(), nowMinutes() - viewSpan * rulerFraction());

  function updateVisibleDates() {
    if (!width) return;
    const first = viewStart();
    const from = date(first);
    const to = date(Math.max(first, Math.min(first + viewSpan, nowMinutes())));
    const format = yearFormat.format(from) === yearFormat.format(to)
      ? visibleDateFormat : visibleYearFormat;
    const label = format.formatRange(from, to);
    if (visibleDates.textContent !== label) visibleDates.textContent = label;
  }

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
    cancelPlaybackScroll();
    finishZoom?.();
    fittedView = false;
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
    updateVisibleDates();
  }
  function buildRuler() {
    canvas.style.width = `${width * 5}px`;
    const ruler = get<HTMLDivElement>("ruler");
    ruler.replaceChildren();
    const originHour = start / 3600000;
    // Align ticks to real Philippine clock hours, including non-midnight anchors.
    const tickHours = zoomMinutes < 1440 ? 1 : 2;
    const first = Math.ceil((originHour + canvasStart / 60 + 8) / tickHours) * tickHours;
    const pixelsPerHour = width * 60 / viewSpan;
    const labelHours = [1, 2, 3, 6, 12, 24, 48].find(hours => hours * pixelsPerHour >= 100) ?? 48;
    const dateDays = Math.ceil(120 / (pixelsPerHour * 24));
    for (
      let localHour = first;
      localHour < originHour + (canvasStart + viewSpan * 5) / 60 + 8 &&
        (localHour - 8) * 3600000 <= availableThrough;
      localHour += tickHours
    ) {
      const minutes = (localHour - 8 - originHour) * 60;
      const tick = document.createElement("span");
      tick.className = `ruler-tick${localHour % labelHours === 0 ? " major" : ""}${localHour % 24 === 0 ? " midnight" : ""}`;
      tick.style.left = `${x(minutes)}px`;
      if (localHour % 24 === 0 && Math.floor(localHour / 24) % dateDays === 0) {
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
        offset.textContent = `${hours < 0 ? "−" : hours > 0 ? "+" : ""}${offsetFormat.format(Math.abs(hours))}h`;
        label.append(time, offset);
        tick.append(label);
      }
      ruler.append(tick);
    }
    render();
  }
  function positionView(first: number) {
    cancelPlaybackScroll();
    firstVisibleTime = Math.min(first, latestViewStart());
    canvasStart = firstVisibleTime - viewSpan * 2;
    buildRuler();
    viewport.scrollLeft = width * 2;
    updateVisibleDates();
  }
  function showTime(minutes: number) {
    finishZoom?.();
    fittedView = false;
    positionView(minutes - viewSpan * 0.25);
  }
  function updateScale(minutes = zoomMinutes) {
    viewSpan = minutes * width / Math.max(1, width - 16);
    const nextMinutes = zoomLevels[(zoomLevels.indexOf(zoomMinutes) + 1) % zoomLevels.length];
    zoom.querySelector("span")!.textContent = `${zoomMinutes / 60}h view`;
    zoom.setAttribute("aria-label", `Timeline zoom, ${zoomMinutes / 60}h view. Switch to ${nextMinutes / 60}h view.`);
    zoom.title = `Switch to ${nextMinutes / 60}h view`;
  }
  function animateZoom(anchorPixels: number, anchorTime: number, fit = false) {
    cancelPlaybackScroll();
    cancelAnimationFrame(zoomFrame);
    const fromSpan = viewSpan, fromStart = viewStart();
    const toSpan = zoomMinutes * width / Math.max(1, width - 16);
    const toStart = fit ? -8 * toSpan / width : anchorTime - anchorPixels / width * toSpan;
    const started = performance.now();
    const apply = (progress: number) => {
      viewSpan = progress === 1 ? toSpan : fromSpan * Math.pow(toSpan / fromSpan, progress);
      positionView(fit
        ? fromStart + (toStart - fromStart) * progress
        : anchorTime - anchorPixels / width * viewSpan);
    };
    finishZoom = () => {
      cancelAnimationFrame(zoomFrame);
      finishZoom = null;
      apply(1);
    };
    updateScale(fromSpan * Math.max(1, width - 16) / width);
    if (reducedMotion.matches) {
      finishZoom();
      return;
    }
    const step = (time: number) => {
      const progress = Math.min(1, (time - started) / 250);
      if (progress === 1) {
        finishZoom?.();
        return;
      }
      apply(1 - Math.pow(2, -10 * progress));
      zoomFrame = requestAnimationFrame(step);
    };
    zoomFrame = requestAnimationFrame(step);
  }
  function zoomTo(minutes: number, anchorPixels: number, anchorTime = viewStart() + anchorPixels / width * viewSpan) {
    if (!width) return;
    availableThrough = Date.now();
    fittedView = false;
    releaseStretch();
    // Accumulate gesture movement before choosing a level, including small trackpad deltas.
    requestedZoomMinutes = Math.max(minZoomMinutes, Math.min(maxZoomMinutes, minutes));
    const next = zoomLevels.reduce((closest, duration) =>
      Math.abs(Math.log(duration / requestedZoomMinutes)) < Math.abs(Math.log(closest / requestedZoomMinutes)) ? duration : closest);
    if (next === zoomMinutes) return;
    zoomMinutes = next;
    animateZoom(anchorPixels, anchorTime);
  }
  function cycleZoom() {
    const minutes = zoomLevels[(zoomLevels.indexOf(zoomMinutes) + 1) % zoomLevels.length];
    if (minutes === endMinutes) {
      fitForecast(true);
      return;
    }
    const selectedPosition = x(replayTime) - viewport.scrollLeft;
    zoomTo(minutes, selectedPosition >= 0 && selectedPosition <= width ? selectedPosition : width / 2);
  }
  function fitForecast(animate = false) {
    availableThrough = Date.now();
    zoomMinutes = endMinutes;
    requestedZoomMinutes = zoomMinutes;
    releaseStretch();
    if (animate) animateZoom(0, 0, true);
    else {
      finishZoom?.();
      updateScale();
      positionView(-edgeMinutes());
    }
    fittedView = true;
  }
  function cancelPlaybackScroll() {
    cancelAnimationFrame(playbackScrollFrame);
    playbackScrollFrame = 0;
  }
  function keepInView() {
    if (finishZoom || playbackScrollFrame || !width) return;
    const first = viewStart();
    if (replayTime >= first + viewSpan * 0.08 &&
        replayTime <= first + viewSpan * 0.9) return;
    if (reducedMotion.matches) {
      showTime(replayTime);
      return;
    }
    fittedView = false;
    const target = Math.min(replayTime - viewSpan * 0.25, latestViewStart());
    const started = performance.now();
    const step = (time: number) => {
      const progress = Math.min(1, (time - started) / 250);
      const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
      const next = first + (target - first) * eased;
      viewport.scrollLeft = x(Math.min(next, latestViewStart()));
      firstVisibleTime = viewStart();
      updateVisibleDates();
      playbackScrollFrame = progress === 1 ? 0 : requestAnimationFrame(step);
    };
    playbackScrollFrame = requestAnimationFrame(step);
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
    cancelPlaybackScroll();
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
        const limit = playbackEnd();
        const next = Math.min(replayTime + 6 * playbackSpeed, limit);
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
        if (replayTime >= limit) {
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
  const cancelDrags: (() => void)[] = [];
  let pinch: { distance: number; minutes: number; time: number } | null = null;
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
        if (event.button !== 0 || pinch) return;
        event.preventDefault();
        cancelPlaybackScroll();
        finishZoom?.();
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
    cancelDrags.push(endDrag);
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
        event.button !== 0 || pinch ||
        (event.target as Element).closest("button")
      )
        return;
      if (event.pointerType === "mouse") event.preventDefault();
      cancelPlaybackScroll();
      finishZoom?.();
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
      if (event.pointerId !== panPointer || pinch) return;
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
  const touchGeometry = (touches: TouchList) => {
    const first = touches[0], second = touches[1];
    return {
      distance: Math.hypot(second.clientX - first.clientX, second.clientY - first.clientY),
      midpoint: (first.clientX + second.clientX) / 2 - viewport.getBoundingClientRect().left - viewport.clientLeft,
    };
  };
  viewport.addEventListener("touchstart", (event) => {
    if (event.touches.length !== 2) return;
    event.preventDefault();
    cancelPlaybackScroll();
    cancelDrags.forEach(cancel => cancel());
    panPointer = null;
    viewport.classList.remove("is-dragging");
    const { distance, midpoint } = touchGeometry(event.touches);
    pinch = { distance: Math.max(1, distance), minutes: viewSpan * Math.max(1, width - 16) / width, time: viewStart() + midpoint / width * viewSpan };
  }, { ...options, passive: false });
  viewport.addEventListener("touchmove", (event) => {
    if (!pinch || event.touches.length !== 2) return;
    event.preventDefault();
    const { distance, midpoint } = touchGeometry(event.touches);
    zoomTo(pinch.minutes * pinch.distance / Math.max(1, distance), midpoint, pinch.time);
  }, { ...options, passive: false });
  for (const name of ["touchend", "touchcancel"] as const)
    viewport.addEventListener(name, (event) => {
      if (event.touches.length < 2) pinch = null;
    }, options);
  viewport.addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey) {
        event.preventDefault();
        const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? width : 1;
        zoomTo(requestedZoomMinutes * Math.exp(Math.max(-1, Math.min(1, event.deltaY * unit * 0.003))),
          Math.max(0, Math.min(width, event.clientX - viewport.getBoundingClientRect().left - viewport.clientLeft)));
        return;
      }
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
      updateVisibleDates();
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
    cancelPlaybackScroll();
    finishZoom?.();
    width = viewport.clientWidth;
    if (!width) return;
    updateScale();
    if (fittedView) fitForecast();
    else positionView(firstVisibleTime);
  });
  resize.observe(viewport);
  function setPlaybackSpeed(value: 1 | 2) {
    playbackSpeed = value;
    const next = value === 1 ? 2 : 1;
    speed.querySelector("span")!.textContent = `${value}x`;
    speed.setAttribute("aria-label", `Playback speed, ${value}x. Switch to ${next}x.`);
    speed.title = `Switch to ${next}x playback speed`;
  }
  setPlaybackSpeed(1);
  speed.addEventListener("click", () => {
    setPlaybackSpeed(playbackSpeed === 1 ? 2 : 1);
  }, options);
  zoom.addEventListener("click", cycleZoom, options);
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
      if (document.hidden) {
        finishZoom?.();
        setPlaying(false);
      }
    },
    options,
  );
  window.addEventListener("pagehide", () => setPlaying(false), options);
  reducedMotion.addEventListener("change", () => {
    if (reducedMotion.matches) {
      cancelPlaybackScroll();
      finishZoom?.();
      releaseStretch();
      if (timer !== null) keepInView();
    }
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
    cancelAnimationFrame(zoomFrame);
    finishZoom = null;
    dragFrames.forEach((frame) => cancelAnimationFrame(frame));
  };
}
