import { navigate } from 'astro:transitions/client';

// Public view state stays in the mounted DOM, never in history or browser storage.
let origin: { href: string; focus: HTMLElement | null; scroll: number; page: Document } | null = null;
let defaultBulletin: Document | null = null;
const preloaded = new Set<string>();
const settingsShells = new Map<string, Document>();
const settingsPaths = new Set(['/alerts', '/location', '/account', '/account/phone', '/account/password',
  '/account/phone/remove', '/account/devices', '/account/email', '/account/remove']);

function preloadDestination(href: string) {
  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;
  if (connection?.saveData || /(^|-)2g$/.test(connection?.effectiveType ?? '')) return;

  // Download resources without mounting settings or starting an account session.
  void fetch(href, { priority: 'low' }).then(async response => {
    if (!response.ok || response.redirected) return;
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    if (href === '/') defaultBulletin = page;
    const resources = new Map<string, 'style' | 'script'>();
    const styles: Promise<void>[] = [];
    page.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]').forEach(link => {
      resources.set(link.getAttribute('href')!, 'style');
    });
    page.querySelectorAll('astro-island').forEach(island => {
      for (const attribute of ['component-url', 'renderer-url']) {
        const url = island.getAttribute(attribute);
        if (url) resources.set(url, 'script');
      }
    });
    for (const [href, type] of resources) {
      const url = new URL(href, response.url);
      if (url.origin !== location.origin || [...document.querySelectorAll('link')].some(link => link.href === url.href)) continue;
      const link = document.createElement('link');
      link.rel = type === 'script' ? 'modulepreload' : 'preload';
      if (type === 'style') {
        link.as = 'style';
        styles.push(new Promise(resolve => { link.onload = link.onerror = () => resolve(); }));
      }
      link.href = url.href;
      document.head.append(link);
    }
    await Promise.all(styles);
    // Dev HTML needs Astro's client-only style preparation before reuse.
    if (href !== '/' && !import.meta.env.DEV && page.body.hasAttribute('data-account-settings')) settingsShells.set(href, page);
  }).catch(() => { /* Normal navigation retries when preloading is unavailable. */ });
}

export function closeAccountSettings() {
  if (origin && history.state?.accountIndex > 0) history.go(-history.state.accountIndex);
  else void navigate('/', { history: 'replace' });
}

export function installAccountModalNavigation() {
  const schedule = () => {
    const accountPage = document.body.hasAttribute('data-account-page');
    if (accountPage && origin) return;
    if (accountPage && !/^\/(alerts|location|account)(\/|$)/.test(location.pathname)) return;
    const href = accountPage ? '/' : '/alerts';
    if (preloaded.has(href)) return;
    preloaded.add(href);
    const preload = () => preloadDestination(href);
    if ('requestIdleCallback' in window) window.requestIdleCallback(preload);
    else setTimeout(preload, 0);
  };
  if (document.readyState === 'complete') schedule();
  else window.addEventListener('load', schedule, { once: true });
  document.addEventListener('astro:page-load', schedule);
  document.addEventListener('astro:before-preparation', event => {
    if (event.formData || event.to.origin !== location.origin) return;
    const shell = settingsShells.get(event.to.pathname.replace(/\/$/, '') + event.to.search);
    if (shell) {
      event.loader = async () => { event.newDocument = shell.cloneNode(true) as Document; };
      return;
    }
    if (!document.body.hasAttribute('data-account-page')) return;
    if ((origin?.href ?? '/') !== event.to.pathname + event.to.search + event.to.hash) return;
    const page = origin?.page ?? defaultBulletin;
    if (!page) return;
    event.loader = async () => { event.newDocument = page.cloneNode(true) as Document; };
  });
  document.addEventListener('astro:before-swap', event => {
    const previous = document.querySelector<HTMLElement>('#bulletin-view');
    const incoming = event.newDocument.querySelector<HTMLElement>('#bulletin-view');
    const fromAccount = document.body.hasAttribute('data-account-page');
    const toAccount = event.newDocument.body.hasAttribute('data-account-page');
    const settingsPath = event.to.pathname.replace(/\/$/, '');
    if (settingsPaths.has(settingsPath) && event.newDocument.body.hasAttribute('data-account-settings')) {
      // Cache only incoming server HTML, before React mounts or public styles are copied.
      settingsShells.set(settingsPath + event.to.search, event.newDocument.cloneNode(true) as Document);
    }
    if (!fromAccount && toAccount) {
      origin = { href: event.from.pathname + event.from.search + event.from.hash,
        focus: document.activeElement instanceof HTMLElement ? document.activeElement : null, scroll: scrollY,
        page: document.cloneNode(true) as Document };
      // The live public view is persisted separately; only its document shell is needed.
      origin.page.querySelector('#bulletin-view')?.replaceChildren();
    }
    const returning = fromAccount && !toAccount && (origin?.href ?? '/') === event.to.pathname + event.to.search + event.to.hash;
    const persist = !!previous && !!incoming && (toAccount || returning);
    for (const element of [previous, incoming]) {
      if (persist) element?.setAttribute('data-astro-transition-persist', 'bulletin-view');
      else element?.removeAttribute('data-astro-transition-persist');
    }
    if (persist && toAccount) {
      // Retain the public view's styles while its DOM remains behind settings.
      for (const style of document.head.querySelectorAll('link[rel="stylesheet"], style')) {
        if (![...event.newDocument.head.children].some(next => next.isEqualNode(style)))
          event.newDocument.head.append(style.cloneNode(true));
      }
    }
    if (!toAccount && !returning) origin = null;
  });
  document.addEventListener('astro:page-load', () => {
    if (document.body.hasAttribute('data-account-page') || !origin) return;
    if (origin.href === location.pathname + location.search + location.hash) {
      window.scrollTo({ top: origin.scroll, behavior: 'instant' });
      if (origin.focus?.isConnected) origin.focus.focus({ preventScroll: true });
    }
    origin = null;
  });
}
