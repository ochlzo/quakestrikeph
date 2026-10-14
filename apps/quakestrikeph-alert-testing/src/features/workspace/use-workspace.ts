import { useEffect, useState } from "react";
import { navigate } from "astro:transitions/client";
import type { SessionState } from "../../lib/api";

export type Inputs = Record<
  "location" | "magnitude" | "depth" | "latitude" | "longitude" | "time" |
  "p1" | "p4" | "p5" | "count" | "radius" | "q05" | "q50" | "q95" |
  "local" | "background" | "spread" | "spillover" | "preset", string>;
type Draft = { inputs: Inputs; selected: string[]; };
export const initialInputs = (): Inputs => ({
  location: "12 km NE of Surigao City, Surigao del Norte", magnitude: "5.2", depth: "18",
  latitude: "9.86", longitude: "125.55",
  time: new Date(Date.now() + 7 * 3600000).toISOString().slice(0, 16),
  p1: "82", p4: "28", p5: "8", count: "12.4", radius: "42",
  q05: "2.8", q50: "4.2", q95: "5.6", local: "18", background: "4", spread: "20",
  spillover: "2", preset: "moderate",
});

// Astro navigates separate pages; this module retains only this tab's unfinished edits.
let state = { draft: { inputs: initialInputs(), selected: [] } as Draft, owner: "", ready: false };
const listeners = new Set<() => void>();
let initialized = false;

function accept(session: SessionState) {
  const owner = session.status === "active" ? session.session_id ?? "" : "";
  if (owner !== state.owner) state = {
    draft: { inputs: initialInputs(), selected: [] }, owner, ready: !!owner,
  };
  else state = { ...state, ready: !!owner };
  listeners.forEach(listener => listener());
}

export function useWorkspace() {
  const [view, setView] = useState(() => ({
    draft: { inputs: { ...initialInputs(), time: "" }, selected: [] as string[] }, owner: "", ready: false,
  }));
  useEffect(() => {
    if (!initialized) {
      initialized = true;
      window.addEventListener("alert-testing-session", event => accept((event as CustomEvent<SessionState>).detail));
    }
    const listener = () => setView(state);
    listeners.add(listener);
    listener();
    return () => { listeners.delete(listener); };
  }, []);
  function edit(draft: Draft) {
    if (!state.ready) return;
    state = { ...state, draft };
    listeners.forEach(listener => listener());
  }
  return { ...view, edit, navigate };
}
