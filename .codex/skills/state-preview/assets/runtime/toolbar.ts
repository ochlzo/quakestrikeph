import "./toolbar.css";

export type PreviewState = { id: string; label: string; data?: unknown; repeatLabel?: string };
export type PreviewAdapter = { target: string; selector: string; states: PreviewState[] };

export function mountToolbar(adapter: PreviewAdapter, select: (state: PreviewState | null) => void, dispose: () => void) {
  if (!adapter.states.length) throw new Error("State Preview needs at least one state.");
  const host = document.createElement("div");
  host.id = "state-preview-toolbar";
  host.className = "state-preview-toolbar";
  host.setAttribute("role", "toolbar");
  host.setAttribute("aria-label", "Temporary UI state preview");
  const label = document.createElement("span");
  label.className = "state-preview-label";
  label.textContent = "Preview";
  host.append(label);
  const button = (name: string, path: string, action: () => void) => {
    const element = document.createElement("button");
    element.type = "button";
    element.setAttribute("aria-label", name);
    element.title = name;
    element.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
    element.addEventListener("click", action);
    return element;
  };
  let index = 0;
  const menu = document.createElement("select");
  menu.setAttribute("aria-label", "UI preview state");
  adapter.states.forEach((state, position) => {
    const option = document.createElement("option");
    option.value = String(position);
    option.textContent = state.label;
    menu.append(option);
  });
  const choose = (next: number) => {
    index = (next + adapter.states.length) % adapter.states.length;
    menu.value = String(index);
    const state = adapter.states[index];
    repeat.hidden = !state.repeatLabel;
    repeat.setAttribute("aria-label", state.repeatLabel || "Repeat preview state");
    repeat.title = state.repeatLabel || "Repeat preview state";
    select(state);
  };
  const previous = button("Previous UI state", "m12 19-7-7 7-7M5 12h14", () => choose(index - 1));
  const next = button("Next UI state", "m12 5 7 7-7 7M19 12H5", () => choose(index + 1));
  const repeat = button("Repeat preview state", "M12 5v14M5 12h14", () => select(adapter.states[index]));
  const close = () => {
    select(null);
    dispose();
    host.remove();
    window.removeEventListener("pagehide", close);
  };
  const exit = button("Close preview and restore live UI", "m18 6-12 12M6 6l12 12", close);
  menu.addEventListener("change", () => choose(Number(menu.value)));
  host.append(previous, menu, next, repeat, exit);
  document.body.append(host);
  window.addEventListener("pagehide", close);
  choose(0);
  return { close };
}
