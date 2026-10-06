// Test-only persistence simulates saved settings across fixture reloads.
const mode = new URLSearchParams(location.search).get('channel-test') ?? sessionStorage.getItem('fixture:channel-mode');
if (mode) {
  window.addEventListener('beforeunload', () => console.info('fixture:navigation:document-unload'));
  document.addEventListener('astro:before-preparation', () => console.info('fixture:navigation:prepare'));
  document.addEventListener('astro:after-swap', () => console.info('fixture:navigation:swap'));
  document.addEventListener('click', event => {
    const link = (event.target as Element).closest('a');
    if (link) console.info(`fixture:navigation:click:${JSON.stringify({ href: link.href, prevented: event.defaultPrevented, button: event.button, target: link.target })}`);
  });
  sessionStorage.setItem('fixture:channel-mode', mode);
  const key = `fixture:channels:${mode}`;
  let account = JSON.parse(sessionStorage.getItem(key) ?? 'null') ?? {
    userId: 'fixture-user', displayName: 'Channel Test', email: 'fixture@example.invalid',
    phone: null, status: 'active', onboardingCompleted: false, emailEnabled: false,
    smsEnabled: false, magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null,
  };
  let reject = mode === 'failure' || mode === 'delayed-failure';
  const fetchOriginal = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    if (!url.pathname.startsWith('/api/v1/account')) return fetchOriginal(input, init);
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (url.pathname.endsWith('/preferences') && init?.method === 'PUT') {
      console.info(`fixture:channels:request:${JSON.stringify(body)}`);
      if (mode === 'delayed-failure' && account.onboardingCompleted) await new Promise(resolve => setTimeout(resolve, 2000));
      if (reject && account.onboardingCompleted) {
        reject = false;
        console.info('fixture:channels:failed');
        return Response.json({ error: { code: 'UNAVAILABLE', message: 'Fixture save failed. Try again.' } }, { status: 503 });
      }
      account = { ...account, ...body, onboardingCompleted: true };
      sessionStorage.setItem(key, JSON.stringify(account));
      console.info(`fixture:channels:saved:${JSON.stringify(body)}`);
      return Response.json(account);
    }
    if (url.pathname.endsWith('/phone/attempts')) {
      if (init?.method === 'DELETE') return new Response(null, { status: 204 });
      return Response.json({ id: 'fixture-attempt', phone: '+639171234567', expiresAt: new Date(Date.now() + 300000).toISOString(), resendAt: new Date().toISOString() });
    }
    if (url.pathname.endsWith('/phone/verify')) {
      account = { ...account, phone: '+639171234567' };
      return Response.json(account);
    }
    return Response.json({ account, pending: null, nextStep: account.onboardingCompleted ? 'complete' : 'channels', deliveryAvailable: false });
  };
}
