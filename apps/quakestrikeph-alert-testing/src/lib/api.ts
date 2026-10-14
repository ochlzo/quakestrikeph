import type { SessionState } from "../../../../packages/contracts/alert-testing/session-v1";
import type { TesterResponse } from "../../../../packages/contracts/alert-testing/testers-v1";
export type { SessionState };

export class ApiError extends Error {
  constructor(public code: string) { super(code); }
}

export async function testerRequest(body: object): Promise<TesterResponse> {
  const response = await fetch("/api/test/testers", {
    method: "POST", cache: "no-store", signal: AbortSignal.timeout(8000),
    headers: { "Content-Type": "application/json", "X-QuakeStrike-Test": "1" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error ?? "request-failed");
  return result;
}

export async function sessionRequest(
  action?: "start" | "end" | "cleanup",
  sessionId?: string,
  signal?: AbortSignal,
): Promise<SessionState> {
  const response = await fetch(`/api/test/session${action ? `/${action}` : ""}`, {
    method: action ? "POST" : "GET",
    cache: "no-store",
    signal: signal ?? AbortSignal.timeout(8000),
    ...(action ? {
      headers: { "Content-Type": "application/json", "X-QuakeStrike-Test": "1" },
      body: JSON.stringify(action === "start" ? {} : { session_id: sessionId }),
    } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error ?? "request-failed");
  return result;
}
