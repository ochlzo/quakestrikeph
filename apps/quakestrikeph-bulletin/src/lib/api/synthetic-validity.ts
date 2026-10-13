// Synthetic pages cannot keep cached success after their temporary session ends.
export function monitorSyntheticForecast() {
  const eventId = document.body.dataset.syntheticEvent;
  const deadline = Date.parse(document.body.dataset.syntheticExpiry ?? '');
  if (!eventId || !Number.isFinite(deadline)) return;
  let checking = false;
  let ended = false;
  const listeners = new AbortController();
  const invalidate = () => {
    if (ended) return;
    ended = true;
    document.querySelector('main')?.setAttribute('hidden', '');
    document.querySelector('footer')?.setAttribute('hidden', '');
    window.dispatchEvent(new Event('synthetic-forecast-invalidated'));
    stop();
    window.location.reload();
  };
  const check = async () => {
    if (ended || checking) return;
    if (Date.now() >= deadline) { invalidate(); return; }
    checking = true;
    try {
      const response = await fetch(`/api/v1/earthquakes/${encodeURIComponent(eventId)}?test=true`, {
        cache: 'no-store', signal: AbortSignal.timeout(2500),
      });
      if (!response.ok) invalidate();
    } catch { invalidate(); }
    finally { checking = false; }
  };
  const interval = setInterval(() => void check(), 15000);
  const expiry = setTimeout(invalidate, Math.max(0, deadline - Date.now()));
  const stop = () => { clearInterval(interval); clearTimeout(expiry); listeners.abort(); };
  window.addEventListener('focus', () => void check(), { signal: listeners.signal });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void check(); }, { signal: listeners.signal });
  // Keep this listener through pagehide so back/forward cache restoration revalidates.
  window.addEventListener('pageshow', event => { if (event.persisted) invalidate(); });
  window.addEventListener('synthetic-forecast-unavailable', invalidate, { signal: listeners.signal });
  window.addEventListener('pagehide', stop, { once: true });
  void check();
}
