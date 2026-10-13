/** Private session HTTP response, version 1. Times are UTC Unix milliseconds. */
export type SessionState = {
  status: "inactive" | "active" | "ending" | "ended" | "expired" | "cleanup-failure";
  session_id?: string;
  started_at_ms?: number;
  expires_at_ms?: number;
  server_time_ms?: number;
  cleanup?: "none" | "pending" | "running" | "complete" | "failed";
  closure_phase?: "none" | "waiting" | "deleting" | "failed" | "complete";
  calls_until_ms?: number;
  closed_at_ms?: number;
  cleanup_completed_at_ms?: number;
};
