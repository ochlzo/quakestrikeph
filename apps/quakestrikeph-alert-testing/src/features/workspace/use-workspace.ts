import { useEffect, useState } from "react";
import { navigate } from "astro:transitions/client";
import { preparationRequest, type SessionState } from "../../lib/api";
import { WorkspaceMemory } from "./workspace-memory";
export { initialInputs, type Inputs } from "./workspace-memory";

const memory = new WorkspaceMemory();
let initialized = false;

export function useWorkspace() {
  const [view, setView] = useState(() => ({ ...memory.state,
    draft: { inputs: { ...memory.state.draft.inputs, time: "" }, selected: [] as string[] },
  }));
  useEffect(() => {
    if (!initialized) {
      initialized = true;
      window.addEventListener("alert-testing-session", event => memory.accept((event as CustomEvent<SessionState>).detail));
      window.setInterval(() => memory.expire(), 1000);
    }
    const listener = () => setView(memory.state);
    memory.listeners.add(listener);
    memory.expire();
    listener();
    return () => { memory.listeners.delete(listener); };
  }, []);
  return { ...view, edit: memory.edit.bind(memory),
    prepare: () => memory.prepare(preparationRequest), navigate };
}
