import { useEffect, useState } from "react";
import { navigate } from "astro:transitions/client";
import { preparationRequest, submissionRequest, workspaceRead, workspaceSave, type SessionState } from "../../lib/api";
import { WorkspaceMemory } from "./workspace-memory";
import { WorkspacePersistence } from "./workspace-persistence";
export { initialInputs, type Inputs } from "./workspace-memory";

const memory = new WorkspaceMemory();
let initialized = false;
let persistence: WorkspacePersistence;

export function useWorkspace() {
  const [view, setView] = useState(() => ({ ...memory.state,
    // Match the server render until this island subscribes to the shared memory.
    ready: false,
    draft: { inputs: { ...memory.state.draft.inputs, time: "" }, selected: [] as string[] },
  }));
  useEffect(() => {
    if (!initialized) {
      initialized = true;
      let workspaceId: string;
      try {
        workspaceId = sessionStorage.getItem("alert-testing-workspace") ?? crypto.randomUUID();
        sessionStorage.setItem("alert-testing-workspace", workspaceId);
      } catch { workspaceId = crypto.randomUUID(); }
      persistence = new WorkspacePersistence(memory, workspaceId, workspaceRead, workspaceSave);
      window.addEventListener("alert-testing-session", event => memory.accept((event as CustomEvent<SessionState>).detail));
      window.setInterval(() => memory.expire(), 1000);
    }
    const listener = () => setView(memory.state);
    memory.listeners.add(listener);
    memory.expire();
    listener();
    return () => { memory.listeners.delete(listener); };
  }, []);
  return { ...view, ready: view.ready && !view.restoring && !view.restoreError, edit: memory.edit.bind(memory),
    retryPersistence: () => void persistence.retry(),
    newScenario: memory.newScenario.bind(memory),
    prepare: () => memory.prepare(preparationRequest),
    submit: async () => {
      await memory.submit(submissionRequest);
      if (memory.state.submission) await navigate(`/results/${memory.state.submission.event_id}`);
    }, navigate };
}
