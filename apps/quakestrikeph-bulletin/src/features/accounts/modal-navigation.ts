import { navigate } from 'astro:transitions/client';

// Public view state stays in the mounted DOM, never in history or browser storage.
let origin: { href: string; focus: HTMLElement | null; scroll: number } | null = null;

export function closeAccountSettings() {
  if (origin && history.state?.accountIndex > 0) history.go(-history.state.accountIndex);
  else void navigate('/', { history: 'replace' });
}

export function installAccountModalNavigation() {
  document.addEventListener('astro:before-swap', event => {
    const previous = document.querySelector<HTMLElement>('#bulletin-view');
    const incoming = event.newDocument.querySelector<HTMLElement>('#bulletin-view');
    const fromAccount = document.body.hasAttribute('data-account-page');
    const toAccount = event.newDocument.body.hasAttribute('data-account-page');
    if (!fromAccount && toAccount) {
      origin = { href: event.from.pathname + event.from.search + event.from.hash,
        focus: document.activeElement instanceof HTMLElement ? document.activeElement : null, scroll: scrollY };
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
