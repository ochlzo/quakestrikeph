import { useEffect, useRef, useState } from "react";
import { ApiError, sessionRequest, type SessionState } from "../../lib/api";

export function useSession() {
  const [session, setSession] = useState<SessionState | null>(null);
  const [pending, setPending] = useState<"start" | "end" | "cleanup" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const busy = useRef(false);
  const mounted = useRef(true);
  const baseline = useRef({ received: 0, remaining: 0 });

  function accept(result: SessionState) {
    setSession(result);
    setError(null);
    const milliseconds = Math.max(0, (result.expires_at_ms ?? 0) - (result.server_time_ms ?? 0));
    baseline.current = { received: performance.now(), remaining: milliseconds };
    setRemaining(milliseconds);
  }

  function failure(reason: unknown) {
    const code = reason instanceof ApiError ? reason.code : "dependency-unavailable";
    setError(code === "session-conflict"
      ? "The shared session changed or cleanup is incomplete. Refresh the session before acting again."
      : code === "private-origin-required"
        ? "This origin cannot control the session. Open the configured private URL."
        : "Session status unavailable. Redis or the private server could not complete the request. Refresh to check the result.");
  }

  async function refresh() {
    if (busy.current) return;
    busy.current = true;
    try {
      const result = await sessionRequest();
      if (mounted.current) accept(result);
    } catch (reason) {
      if (mounted.current) failure(reason);
    } finally { busy.current = false; }
  }

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const poll = window.setInterval(() => void refresh(), 5000);
    const tick = window.setInterval(() => {
      setRemaining(Math.max(0, baseline.current.remaining - (performance.now() - baseline.current.received)));
    }, 1000);
    return () => {
      mounted.current = false;
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, []);

  async function act(action: "start" | "end" | "cleanup", owner = session?.session_id) {
    if (busy.current) return;
    busy.current = true;
    setPending(action);
    setError(null);
    try { accept(await sessionRequest(action, owner)); }
    catch (reason) { failure(reason); }
    finally { busy.current = false; setPending(null); }
  }

  const deadlineReached = session?.status === "active" && remaining === 0;
  const status = deadlineReached ? "expired" : session?.status;
  const canStart = !error && !!session && ["inactive", "ended", "expired"].includes(session.status)
    && (!session.cleanup || session.cleanup === "complete");
  const needsCleanup = !error && !!session && session.status !== "active"
    && session.cleanup !== "complete" && session.cleanup !== undefined;
  const state = error ? "unavailable" : pending === "start" ? "starting"
    : pending ? "closing" : status ?? "checking";

  return { session, state, pending, remaining, error, canStart, needsCleanup, refresh, act };
}
