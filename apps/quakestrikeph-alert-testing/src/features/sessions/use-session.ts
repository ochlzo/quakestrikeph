import { useEffect, useRef, useState } from "react";
import { ApiError, sessionRequest, type SessionState } from "../../lib/api";
import { SessionRequests } from "./session-requests";

export function useSession() {
  const [session, setSession] = useState<SessionState | null>(null);
  const [pending, setPending] = useState<"start" | "end" | "cleanup" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [callRemaining, setCallRemaining] = useState(0);
  const mounted = useRef(true);
  const requests = useRef<SessionRequests | null>(null);
  const baseline = useRef({ received: 0, remaining: 0, callRemaining: 0 });

  function accept(result: SessionState) {
    setSession(result);
    setError(null);
    const milliseconds = Math.max(0, (result.expires_at_ms ?? 0) - (result.server_time_ms ?? 0));
    const callMilliseconds = Math.max(0, (result.calls_until_ms ?? 0) - (result.server_time_ms ?? 0));
    baseline.current = { received: performance.now(), remaining: milliseconds, callRemaining: callMilliseconds };
    setRemaining(milliseconds);
    setCallRemaining(callMilliseconds);
  }

  function failure(reason: unknown) {
    const code = reason instanceof ApiError ? reason.code : "dependency-unavailable";
    setError(code === "session-conflict"
      ? "The test session changed."
      : code === "private-origin-required"
        ? "Open the private testing URL."
        : "Could not connect to the testing tool.");
  }

  if (!requests.current) {
    requests.current = new SessionRequests(
      sessionRequest,
      result => { if (mounted.current) accept(result); },
      reason => { if (mounted.current) failure(reason); },
      action => { if (mounted.current) { setPending(action); if (action) setError(null); } },
    );
  }
  const coordinator = requests.current;
  const refresh = () => coordinator.refresh();

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const poll = window.setInterval(() => void coordinator.refresh(true), 5000);
    const tick = window.setInterval(() => {
      setRemaining(Math.max(0, baseline.current.remaining - (performance.now() - baseline.current.received)));
      setCallRemaining(Math.max(0, baseline.current.callRemaining - (performance.now() - baseline.current.received)));
    }, 1000);
    return () => {
      mounted.current = false;
      coordinator.invalidate();
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, []);

  async function act(action: "start" | "end" | "cleanup", owner = session?.session_id) {
    await coordinator.act(action, owner);
  }

  const deadlineReached = session?.status === "active" && remaining === 0;
  const status = deadlineReached ? "expired" : session?.status;
  const canStart = !error && !!session && ["inactive", "ended", "expired"].includes(session.status)
    && (!session.cleanup || session.cleanup === "complete");
  const needsCleanup = !error && session?.cleanup === "failed";
  const state = error ? "unavailable" : pending === "start" ? "starting"
    : pending ? "closing" : status ?? "checking";

  return { session, state, pending, remaining, callRemaining, error, canStart, needsCleanup, refresh, act };
}
