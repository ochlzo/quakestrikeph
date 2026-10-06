// Loaded only by the isolated Vite fixture, never by Astro.
const outcome = new URLSearchParams(location.search).get('resume-test');
if (outcome) {
  let savedAccount: Record<string, unknown> | null = null;
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href);
    if (outcome === 'signup-profile' && url.pathname === '/api/v1/account/profile' && init?.method === 'PUT') {
      const body = JSON.parse(String(init.body));
      savedAccount = { userId: 'fixture-user', displayName: body.displayName, email: 'fixture@example.invalid',
        phone: null, status: 'active', onboardingCompleted: false, emailEnabled: false, smsEnabled: false,
        magnitude: 4.5, nearbyOnly: false, latitude: null, longitude: null, distanceKm: null };
      console.info(`fixture:signup:saved-name:${body.displayName}`);
      return Response.json(savedAccount);
    }
    if (url.pathname !== '/api/v1/account') return originalFetch(input, init);
    await new Promise(resolve => setTimeout(resolve, 800));
    return outcome === 'failure'
      ? Response.json({ error: { code: 'UNAVAILABLE', message: 'Fixture account unavailable.' } }, { status: 503 })
      : Response.json({ account: savedAccount, pending: null, nextStep: savedAccount ? 'channels' : 'profile', deliveryAvailable: false });
  };
  new MutationObserver(() => {
    if (document.body.textContent?.includes('Account settings unavailable'))
      console.info('fixture:resume:unavailable');
    if (document.querySelector('#form-title')?.textContent === 'Complete your profile')
      console.info('fixture:resume:profile');
  }).observe(document.body, { childList: true, subtree: true });
}
