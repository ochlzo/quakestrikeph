import { adapter } from "./adapter";
import { mountToolbar, type PreviewState } from "./toolbar";

let active = false;
export function startPreview() {
  if (!import.meta.env.DEV || active || document.getElementById("state-preview-toolbar")) return;
  active = true;
  let mounted = false;
  const select = (state: PreviewState | null) => {
    window.dispatchEvent(new CustomEvent("state-preview:select", { detail: { target: adapter.target, state } }));
  };
  const connect = () => {
    window.dispatchEvent(new CustomEvent("state-preview:connect", { detail: { target: adapter.target } }));
  };
  const dispose = () => {
    observer.disconnect();
    window.removeEventListener("state-preview:ready", ready);
    window.removeEventListener("pagehide", dispose);
    active = false;
  };
  const ready = (event: Event) => {
    const detail = (event as CustomEvent).detail;
    if (mounted || detail?.target !== adapter.target || !detail.available || !document.querySelector(adapter.selector)) return;
    mounted = true;
    dispose();
    mountToolbar(adapter, select, dispose);
  };
  const observer = new MutationObserver(connect);
  observer.observe(document.body, { childList: true, subtree: true });
  window.addEventListener("state-preview:ready", ready);
  window.addEventListener("pagehide", dispose);
  connect();
}
