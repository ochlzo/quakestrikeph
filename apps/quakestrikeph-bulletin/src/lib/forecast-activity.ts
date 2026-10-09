import { loadMapRuntime } from './map-runtime';
import 'maplibre-gl/dist/maplibre-gl.css';
import type { components } from './api/schema';
import { displayTime, locationLabel, magnitude } from './events';
import { magnitudeBand } from './magnitude';
import { loadObservationWindow } from './forecast-observations';

type ActivityPoint = { eventId: string; latitude: number; longitude: number; magnitude: string; magnitudeClass: string; location: string; time: string; minutes: number; phase: string };
type ActivityData = { eventId: string; anchor: { latitude: number; longitude: number; magnitude: string; magnitudeClass: string; location: string }; windowStart: string; windowEnd: string };

function renderTimeline(items: components['schemas']['EarthquakeSummary'][] | null) {
  const list = document.querySelector<HTMLElement>('.timeline-event-list');
  const count = document.querySelector<HTMLElement>('[data-observations-count]');
  const note = document.querySelector<HTMLElement>('[data-observations-note]');
  if (!list || !count || !note) return;
  list.replaceChildren();
  list.setAttribute('aria-busy', 'false');
  count.textContent = items ? `${items.length} event${items.length === 1 ? '' : 's'}` : 'Unavailable';
  note.hidden = items === null;
  if (!items?.length) {
    const message = document.createElement('p');
    message.className = 'timeline-empty';
    message.textContent = items ? 'No observed earthquakes were recorded during this window.' : 'Observed earthquakes could not be loaded. Reload the page to try again.';
    list.append(message);
    return;
  }
  const rows = document.createDocumentFragment();
  for (const item of items) {
    const row = document.createElement('article');
    row.className = 'timeline-event-row';
    row.setAttribute('role', 'listitem');
    const values = [
      [`timeline-event-magnitude ${magnitudeBand(item.magnitude).className}`, magnitude(item.magnitude)],
      ['timeline-event-time', displayTime(item.eventTime)],
      ['timeline-event-location', locationLabel(item.locationDescription)],
    ];
    for (const [className, text] of values) {
      const span = document.createElement('span');
      span.className = className;
      span.textContent = text;
      row.append(span);
    }
    rows.append(row);
  }
  list.append(rows);
}

export async function initForecastActivity() {

  const mapHost = document.querySelector<HTMLElement>('[data-activity-map]');
  const activityDataElement = document.querySelector<HTMLScriptElement>('#activity-map-data');
  const playButton = document.querySelector<HTMLButtonElement>('[data-activity-play]');
  const range = document.querySelector<HTMLInputElement>('[data-activity-range]');
  const playhead = document.querySelector<HTMLElement>('[data-activity-playhead]');
  const activityStatus = document.querySelector<HTMLElement>('[data-activity-status]');
  if (mapHost && activityDataElement && range && playhead) {
    const activityData = JSON.parse(activityDataElement.textContent ?? '{}') as ActivityData;
    const start = Date.parse(activityData.windowStart);
    const during = loadObservationWindow(activityData.windowStart, activityData.windowEnd);
    void during.then(items => renderTimeline(items), () => renderTimeline(null));
    const laterEnd = new Date(Date.parse(activityData.windowEnd) + 86400000).toISOString();
    const observations = Promise.allSettled([during, loadObservationWindow(activityData.windowEnd, laterEnd)]);
    void observations.then(results => {
      const warning = document.querySelector<HTMLElement>('[data-observations-warning]');
      if (warning) warning.hidden = results.every(result => result.status === 'fulfilled');
    });
    try {
      const maplibregl = await loadMapRuntime();
      const center: [number, number] = activityData.anchor ? [activityData.anchor.longitude, activityData.anchor.latitude] : [121, 13];
      const map = new maplibregl.Map({ container: mapHost, style: 'https://tiles.openfreemap.org/styles/liberty', center, zoom: 7.2, attributionControl: false });
      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');
      const renderedMarkers: Array<{ point: ActivityPoint; element: HTMLButtonElement }> = [];
      if (activityData.anchor) {
        const anchorElement = document.createElement('span');
        anchorElement.className = `activity-marker activity-marker-anchor ${activityData.anchor.magnitudeClass}`;
        anchorElement.ariaLabel = `Anchor earthquake ${activityData.anchor.magnitude}, ${activityData.anchor.location}`;
        new maplibregl.Marker({ element: anchorElement }).setLngLat(center).addTo(map);
      }
      map.on('load', () => map.resize());
      const results = await observations;
      const points = results.flatMap((result, index): ActivityPoint[] => result.status === 'fulfilled'
        ? result.value.filter(item => item.eventId !== activityData.eventId).map(item => ({
            eventId: item.eventId, latitude: item.latitude, longitude: item.longitude,
            magnitude: magnitude(item.magnitude), magnitudeClass: magnitudeBand(item.magnitude).className,
            location: locationLabel(item.locationDescription), time: displayTime(item.eventTime),
            minutes: (Date.parse(item.eventTime) - start) / 60000, phase: index === 0 ? 'forecast' : 'later',
          })) : []);
      if (results.every(result => result.status === 'rejected')) {
        if (activityStatus) activityStatus.textContent = 'Observed earthquakes unavailable';
        return;
      }
      range.disabled = false;
      if (playButton) playButton.disabled = false;
      for (const point of points) {
        const element = document.createElement('button');
        element.className = `activity-marker activity-marker-${point.phase} ${point.magnitudeClass}`;
        element.type = 'button';
        element.ariaLabel = `${point.magnitude} at ${point.time}, ${point.location}`;
        new maplibregl.Marker({ element }).setLngLat([point.longitude, point.latitude]).addTo(map);
        renderedMarkers.push({ point, element });
      }
      const formatReplayTime = (minutes: number) => new Intl.DateTimeFormat('en-PH', { timeZone: 'Asia/Manila', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(start + minutes * 60000)) + ' PHT';
      const updateReplay = (value: string) => {
        const minutes = Number(value);
        playhead.style.left = `${(minutes / 2880) * 100}%`;
        if (activityStatus) activityStatus.textContent = formatReplayTime(minutes);
        let nearest: typeof renderedMarkers[number] | null = null;
        for (const item of renderedMarkers) {
          const visible = item.point.minutes <= minutes;
          item.element.classList.toggle('is-visible', visible);
          item.element.classList.toggle('is-latest', false);
          item.element.tabIndex = visible ? 0 : -1;
          if (visible && (!nearest || item.point.minutes > nearest.point.minutes)) nearest = item;
        }
        if (nearest) nearest.element.classList.add('is-latest');
      };
      range.addEventListener('input', () => updateReplay(range.value));
      renderedMarkers.forEach(({ point, element }) => element.addEventListener('click', () => { range.value = String(Math.ceil(point.minutes)); updateReplay(range.value); }));
      updateReplay(range.value);
      let playing = false;
      let lastFrame = 0;
      const animate = (timestamp: number) => {
        if (!playing) return;
        if (!lastFrame) lastFrame = timestamp;
        const elapsed = timestamp - lastFrame;
        if (elapsed > 50) {
          range.value = String(Math.min(2880, Number(range.value) + elapsed / 100));
          updateReplay(range.value);
          lastFrame = timestamp;
        }
        if (Number(range.value) >= 2880) { playing = false; playButton?.classList.remove('is-playing'); if (playButton) { playButton.textContent = '▶'; playButton.setAttribute('aria-label', 'Play earthquake activity replay'); } return; }
        requestAnimationFrame(animate);
      };
      playButton?.addEventListener('click', () => {
        playing = !playing;
        playButton.setAttribute('aria-label', playing ? 'Pause earthquake activity replay' : 'Play earthquake activity replay');
        playButton.classList.toggle('is-playing', playing);
        playButton.textContent = playing ? 'Ⅱ' : '▶';
        if (playing) { if (Number(range.value) >= 2880) range.value = '0'; lastFrame = 0; requestAnimationFrame(animate); }
      });
    } catch {
      if (activityStatus) activityStatus.textContent = 'Activity map unavailable';
      if (playButton) playButton.disabled = true;
      range.disabled = true;
    }
  }
}
