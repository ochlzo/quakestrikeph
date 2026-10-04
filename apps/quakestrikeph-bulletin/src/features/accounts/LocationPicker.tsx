import { useEffect, useMemo, useRef, useState } from 'react';
import type { Map, Marker } from 'maplibre-gl';
import { Label } from 'react-aria-components';
import { LocateFixed, MapPin } from 'lucide-react';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Field, FieldLabel, FieldError } from '../../components/ui/field';
import { Combobox, ComboboxContent, ComboboxItem, ComboboxList } from '../../components/ui/combobox';
import { loadMapRuntime } from '../../lib/map-runtime';
import type { Preferences } from './api';
import 'maplibre-gl/dist/maplibre-gl.css';

type Place = [string, string, number, number, string];
const normalized = (s: string) => s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
let placeRequest: Promise<Place[]> | undefined;
function places() {
  return placeRequest ??= fetch('/assets/accounts/philippine-places.json').then(r => {
    if (!r.ok) throw new Error('Place search unavailable'); return r.json() as Promise<Place[]>;
  }).catch(error => { placeRequest = undefined; throw error; });
}
export function locationLabel(latitude: number | null, longitude: number | null, list: Place[]) {
  if (latitude === null || longitude === null) return 'Choose your alert location';
  let closest: Place | undefined, distance = Infinity;
  for (const p of list) {
    const d = (p[2] - latitude) ** 2 + ((p[3] - longitude) * Math.cos(latitude * Math.PI / 180)) ** 2;
    if (d < distance) { distance = d; closest = p; }
  }
  return closest ? `${distance > 0.000001 ? 'Pin near ' : ''}${closest[0]}, ${closest[1]}` : 'Your selected map pin';
}
export function usePlaces() {
  const [list, setList] = useState<Place[]>([]);
  const [error, setError] = useState('');
  useEffect(() => { let active = true; places().then(x => { if (active) setList(x); }).catch(() => {
    if (active) setError('Place search is unavailable. You can still choose a map pin.');
  }); return () => { active = false; }; }, []);
  return { list, error };
}
function radius(latitude: number, longitude: number, km: number): GeoJSON.Feature<GeoJSON.Polygon> {
  const rad = Math.PI / 180, a = km / 6371.0088, lat = latitude * rad, lng = longitude * rad;
  const points: number[][] = [];
  for (let i = 0; i <= 80; i++) {
    const bearing = i / 80 * Math.PI * 2;
    const y = Math.asin(Math.sin(lat) * Math.cos(a) + Math.cos(lat) * Math.sin(a) * Math.cos(bearing));
    const x = lng + Math.atan2(Math.sin(bearing) * Math.sin(a) * Math.cos(lat), Math.cos(a) - Math.sin(lat) * Math.sin(y));
    points.push([x / rad, y / rad]);
  }
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [points] } };
}
function fitRadius(map: Map, point: [number, number], km: number) {
  const lat = km / 111.2, lng = lat / Math.max(0.1, Math.cos(point[0] * Math.PI / 180));
  map.fitBounds([[point[1] - lng, Math.max(-85, point[0] - lat)], [point[1] + lng, Math.min(85, point[0] + lat)]],
    { padding: 24, maxZoom: 12, duration: 0 });
}

export default function LocationPicker({ draft, onUse, onCancel }: {
  draft: Preferences; onUse: (location: Pick<Preferences, 'latitude' | 'longitude' | 'distanceKm'>) => void; onCancel: () => void;
}) {
  const { list, error: searchError } = usePlaces();
  const [query, setQuery] = useState('');
  const searchAnchor = useRef<HTMLDivElement>(null);
  const [point, setPoint] = useState<[number, number] | null>(draft.latitude == null || draft.longitude == null ? null : [draft.latitude, draft.longitude]);
  const [distance, setDistance] = useState(String(draft.distanceKm ?? 50));
  const [error, setError] = useState('');
  const [locating, setLocating] = useState(false);
  const [mapReady, setMapReady] = useState(false);
  const container = useRef<HTMLDivElement>(null), map = useRef<Map | null>(null), marker = useRef<Marker | null>(null);
  const pointRef = useRef(point); pointRef.current = point;
  const distanceRef = useRef(distance); distanceRef.current = distance;
  const matches = useMemo(() => {
    const terms = normalized(query.trim()).split(/\s+/);
    const text = normalized(query.trim());
    const rank = (p: Place) => normalized(p[0]) === text ? 0 : normalized(p[0]).startsWith(text) ? 1 : normalized(p[0]).includes(text) ? 2 : 3;
    return query.trim().length < 2 ? [] : list.map((p, index) => ({ p, index })).filter(({ p }) =>
      terms.every(t => normalized(`${p[0]} ${p[1]} ${p[4]}`).includes(t))).sort((a, b) => rank(a.p) - rank(b.p)).slice(0, 20);
  }, [query, list]);
  useEffect(() => {
    let active = true;
    loadMapRuntime().then(lib => {
      if (!active || !container.current) return;
      const initial = pointRef.current;
      const instance = new lib.Map({ container: container.current, style: 'https://tiles.openfreemap.org/styles/liberty',
        center: initial ? [initial[1], initial[0]] : [121, 12.4], zoom: initial ? 9 : 4.5, attributionControl: { compact: false } });
      map.current = instance;
      instance.addControl(new lib.NavigationControl({ showCompass: false }), 'top-right');
      const pin = new lib.Marker({ color: '#0e6873', draggable: true }); marker.current = pin;
      pin.on('dragend', () => { const position = pin.getLngLat(); setPoint([position.lat, position.lng]); });
      instance.on('click', event => setPoint([event.lngLat.lat, event.lngLat.lng]));
      instance.on('error', () => setError('Map tiles could not load. Place search and Use my location are still available.'));
      instance.on('idle', () => setMapReady(Boolean(instance.isStyleLoaded() && instance.areTilesLoaded())));
      instance.on('load', () => {
        const current = pointRef.current, km = Number(distanceRef.current);
        instance.addSource('alert-radius', { type: 'geojson', data: current && Number.isFinite(km) && km >= 1 && km <= 1000
          ? radius(current[0], current[1], km) : { type: 'FeatureCollection', features: [] } });
        instance.addLayer({ id: 'alert-radius-fill', type: 'fill', source: 'alert-radius', paint: { 'fill-color': '#0e6873', 'fill-opacity': 0.13 } });
        instance.addLayer({ id: 'alert-radius-line', type: 'line', source: 'alert-radius', paint: { 'line-color': '#0e6873', 'line-width': 2 } });
        refresh();
        if (current && Number.isFinite(km) && km >= 1 && km <= 1000) fitRadius(instance, current, km);
      });
      function refresh() {
        const current = pointRef.current;
        if (current) pin.setLngLat([current[1], current[0]]).addTo(instance);
      }
    }).catch(() => setError('The map could not load. You can choose a place using search.'));
    return () => { active = false; marker.current?.remove(); map.current?.remove(); map.current = null; };
  }, []);
  useEffect(() => {
    if (!point || !map.current || !marker.current) return;
    marker.current.setLngLat([point[1], point[0]]).addTo(map.current);
    const source = map.current.getSource('alert-radius') as import('maplibre-gl').GeoJSONSource | undefined;
    const km = Number(distance);
    if (source && Number.isFinite(km) && km >= 1 && km <= 1000) {
      source.setData(radius(point[0], point[1], km));
      setMapReady(false); fitRadius(map.current, point, km);
    }
  }, [point, distance]);
  function choose(next: [number, number]) {
    setPoint(next); setMapReady(false);
  }
  function locate() {
    setLocating(true); setError('');
    if (!navigator.geolocation) { setError('Location is unavailable on this device. Search or choose a map pin.'); setLocating(false); return; }
    navigator.geolocation.getCurrentPosition(position => {
      choose([position.coords.latitude, position.coords.longitude]); setLocating(false);
    }, () => { setError('Your location could not be used. Search for a place or choose a map pin.'); setLocating(false); },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 0 });
  }
  function use() {
    const km = Number(distance);
    if (!point || !Number.isInteger(km) || km < 1 || km > 1000) { setError('Choose a location and a whole-kilometre distance of 1–1,000 km.'); return; }
    onUse({ latitude: point[0], longitude: point[1], distanceKm: km });
  }
  return <>
    <h2 id="form-title">Choose your alert location</h2>
    <p className="form-intro">Search for a place, then adjust the pin. Your device is only located when you ask.</p>
    <Combobox inputValue={query} onInputChange={setQuery} allowsCustomValue allowsEmptyCollection defaultFilter={() => true} onSelectionChange={key => {
      const match = matches.find(x => x.index === key); if (match) choose([match.p[2], match.p[3]]);
    }} menuTrigger="input">
      <div ref={searchAnchor}><Label className="location-search-label">City, town or named place</Label><Input placeholder="Search places in the Philippines" /></div>
      <ComboboxContent anchor={searchAnchor}><ComboboxList<{ p: Place; index: number }> items={matches} renderEmptyState={() => 'No matching places. Try another name or use the map.'}>
        {({ p, index }) => <ComboboxItem id={index} textValue={`${p[0]}, ${p[1]}`}><span>{p[0]}<small className="place-context">{p[1]}</small></span></ComboboxItem>}
      </ComboboxList></ComboboxContent>
    </Combobox>
    <Button className="secondary" onPress={locate} isDisabled={locating}><LocateFixed />{locating ? 'Finding your location…' : 'Use my location'}</Button>
    {searchError && <p role="status" className="support">{searchError}</p>}
    <div className="location-map" ref={container} data-map-ready={mapReady} aria-label="Choose an alert location on the map" />
    <Button variant="outline" className="secondary" onPress={() => { const center = map.current?.getCenter(); if (center) setPoint([center.lat, center.lng]); }}>Place pin at map centre</Button>
    <p className="location-summary" aria-live="polite"><MapPin />{locationLabel(point?.[0] ?? null, point?.[1] ?? null, list)}</p>
    <Field className="field"><FieldLabel htmlFor="distance">Nearby distance (km)</FieldLabel><Input id="distance" type="number" min={1} max={1000} step={1} value={distance} onChange={e => setDistance(e.target.value)} /></Field>
    {error && <FieldError>{error}</FieldError>}
    <p className="support">Search data: <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">GeoNames</a>, CC BY 4.0. Some places may be missing; you can always adjust your pin.</p>
    <Button className="primary" onPress={use}>Use this location</Button><Button className="secondary" onPress={onCancel}>Cancel</Button>
    <p className="quiet-note">Your location is saved only when you save preferences.</p>
  </>;
}
