import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createContext, runInContext } from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Run the component's handlers and effects without a DOM or a WebGL context.
function component(name, imports = {}, globals = {}) {
  const states = [], refs = [], effects = [], layouts = [];
  let stateIndex = 0, refIndex = 0;
  const react = {
    useState(initial) {
      const index = stateIndex++;
      if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
      return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
    },
    useRef(initial) {
      const index = refIndex++;
      return refs[index] ?? (refs[index] = { current: initial });
    },
    useEffect(callback, deps) { effects.push({ callback, deps }); },
    useLayoutEffect(callback) { layouts.push(callback); },
  };
  const jsx = (type, props) => ({ type, props });
  const source = readFileSync(new URL(`../src/components/${name}.tsx`, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  const context = createContext({ exports: {}, ...globals, require(id) {
    if (id === 'react') return react;
    if (id === 'react/jsx-runtime') return { jsx, jsxs: jsx };
    return imports[id] ?? new Proxy({}, { get: (_, key) => key });
  } });
  runInContext(compiled, context);
  return { states, refs, effects, layouts, render(props = {}) {
    stateIndex = refIndex = effects.length = layouts.length = 0;
    return context.exports.default(props);
  } };
}

function find(node, predicate) {
  if (!node || typeof node !== 'object') return;
  if (predicate(node)) return node;
  for (const child of [node.props?.children].flat(Infinity)) {
    const found = find(child, predicate);
    if (found) return found;
  }
}

const earthquake = { eventId: 'selected', longitude: 123, latitude: 12 };

test('a capped drawer reveals the forecast on an upward swipe without raising its height limit', () => {
  const date = { year: 2026, month: 10, day: 4, compare: () => 0, subtract() { return this; } };
  const h = component('Bulletin', {
    '../hooks/use-mobile': { useIsMobile: () => true },
    '../features/event-results/useEventResults': { useEventResults: () => ({
      state: { query: '', date: { value: 'all' }, magnitudes: [] }, events: [], selected: earthquake,
    }) },
    '@internationalized/date': { today: () => date },
    '@/components/ui/button': { buttonVariants: () => '' },
  });
  // The first state holds the search text, before the drawer states.
  h.states.push('', true, '234px', 'event', 234, 360);
  let tree = h.render();
  const popup = find(tree, node => node.type === 'DrawerContent');
  popup.props.onPointerDownCapture?.({ isPrimary: true, clientX: 200, clientY: 145 });
  const drawer = find(tree, node => node.type === 'Drawer');
  drawer.props.onSnapPointChange('234px', { reason: 'swipe', event: { clientX: 200, clientY: 65 } });
  tree = h.render();
  assert.equal(find(tree, node => node.props?.id === 'mobile-forecast-overview').props.hidden, false);
  assert.deepEqual(Array.from(find(tree, node => node.type === 'Drawer').props.snapPoints), ['234px']);
  const scroll = {
    scrollTop: 0,
    getBoundingClientRect: () => ({ top: 182 }),
    querySelector: () => ({ getBoundingClientRect: () => ({ top: 430 }) }),
    scrollTo({ top }) { this.scrollTop = top; },
  };
  find(tree, node => node.props?.className === 'earthquake-drawer-scroll').props.ref.current = scroll;
  for (const layout of h.layouts) layout();
  assert.equal(scroll.scrollTop, 248, 'The capped drawer must bring the newly revealed forecast into view');

  // Native touch release events use changedTouches instead of pointer coordinates.
  find(tree, node => node.type === 'DrawerContent').props.onTouchStartCapture({ touches: [{ clientX: 200, clientY: 145 }] });
  find(tree, node => node.type === 'Drawer').props.onSnapPointChange('234px', {
    reason: 'swipe', event: { changedTouches: [{ clientX: 200, clientY: 195 }] },
  });
  tree = h.render();
  assert.equal(find(tree, node => node.props?.id === 'mobile-forecast-overview').props.hidden, true);
  for (const layout of h.layouts) layout();
  assert.equal(scroll.scrollTop, 0, 'Collapsing the forecast must restore the selected card');

  for (const release of [
    { clientX: 200, clientY: 135 }, // A tap or small jitter.
    { clientX: 300, clientY: 100 }, // A mostly horizontal drag.
    { clientX: 200, clientY: 65, type: 'pointercancel' },
    { changedTouches: [{ clientX: 200, clientY: 65 }], type: 'touchcancel' },
  ]) {
    find(tree, node => node.type === 'DrawerContent').props.onPointerDownCapture({ isPrimary: true, clientX: 200, clientY: 145 });
    find(tree, node => node.type === 'Drawer').props.onSnapPointChange('234px', { reason: 'swipe', event: release });
    tree = h.render();
    assert.equal(find(tree, node => node.props?.id === 'mobile-forecast-overview').props.hidden, true);
  }
});

for (const reducedMotion of [false, true]) {
  for (const radius of [230, null]) {
    test(`resize waits for movement, then recenters once (reduced motion: ${reducedMotion}, radius: ${radius})`, t => {
      t.mock.timers.enable({ apis: ['setTimeout'] });
      let resize, moving = true;
      const listeners = new Set(), calls = [];
      const viewport = { clientHeight: 490, clientWidth: 404 };
      const map = {
        on(type, handler) { if (type === 'moveend') listeners.add(handler); },
        off(type, handler) { if (type === 'moveend') listeners.delete(handler); },
        isMoving: () => moving,
        getContainer: () => viewport,
        resize() { for (const handler of [...listeners]) handler(); return this; },
        redraw() {},
        fitBounds(bounds, options) { calls.push(['fit', options.duration]); },
        easeTo(options) { calls.push(['center', options.duration]); },
        jumpTo() { calls.push(['jump', 0]); },
      };
      const h = component('MapPanel', {
        '@/components/ui/button': { buttonVariants: () => '' },
        './ForecastOverview': { forecastRadiusKm: forecast => forecast?.activityRadiusMedianKm24h ?? null },
        '../lib/magnitude': { magnitudeBands: [] },
      }, {
        window: { matchMedia: () => ({ matches: reducedMotion }), setTimeout, clearTimeout },
        ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} disconnect() {} },
      });
      h.states.push(null, null, false, false, true);
      h.render({ events: [earthquake], selectedId: earthquake.eventId, focusRequest: 0,
        forecast: { activityRadiusMedianKm24h: radius }, forecastStatus: 'ready', overviewInDrawer: true });
      h.refs[0].current = { parentElement: viewport, closest: () => null, classList: { remove() {} }, style: { removeProperty() {} } };
      h.refs[1].current = map;
      const effect = h.effects.find(({ callback }) => callback.toString().includes('new ResizeObserver('));
      assert.ok(effect, 'MapPanel should observe map resizes');
      const cleanup = effect.callback();
      viewport.clientHeight = 232;
      resize();
      t.mock.timers.tick(80);
      assert.deepEqual(calls, [], 'Resizing must not interrupt active camera movement');
      moving = false;
      for (const handler of [...listeners]) handler();
      assert.deepEqual(calls, [[radius ? 'fit' : 'center', reducedMotion ? 0 : 220]]);
      for (const handler of [...listeners]) handler();
      assert.equal(calls.length, 1, 'A completed resize must not refit on unrelated moveend events');

      // Movement can also end before the last resize has settled.
      moving = true;
      viewport.clientHeight = 300;
      resize();
      moving = false;
      for (const handler of [...listeners]) handler();
      if (!reducedMotion) {
        assert.equal(calls.length, 1);
        t.mock.timers.tick(79);
        assert.equal(calls.length, 1);
        viewport.clientHeight = 310;
        resize();
        t.mock.timers.tick(79);
        assert.equal(calls.length, 1, 'Repeated resizes must restart the settling delay');
        t.mock.timers.tick(1);
      }
      assert.equal(calls.length, 2);

      // Cleanup removes both a deferred movement listener and a settling timer.
      moving = true;
      viewport.clientHeight = 320;
      resize();
      cleanup();
      assert.equal(listeners.size, 0);
      moving = false;
      t.mock.timers.tick(80);
      assert.equal(calls.length, 2);
    });
  }
}
