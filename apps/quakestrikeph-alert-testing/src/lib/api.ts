import type { SessionState } from "../../../../packages/contracts/alert-testing/session-v1";
import type { TesterResponse } from "../../../../packages/contracts/alert-testing/testers-v1";
import type { PreparedScenario, ScenarioInputs } from "../../../../packages/contracts/alert-testing/scenarios-v1";
export type { SessionState };
import type { ScenarioResult, SubmissionRequest } from "../../../../packages/contracts/alert-testing/delivery-v1";

async function deliveryRequest(operation: string, body: object) {
  const response = await fetch(`/api/test/scenarios/${operation}`, {
    method: "POST", cache: "no-store", signal: AbortSignal.timeout(8000),
    headers: { "Content-Type": "application/json", "X-QuakeStrike-Test": "1" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error ?? "request-failed", result.fields ?? {});
  return result;
}
export const submissionRequest = (body: SubmissionRequest): Promise<ScenarioResult> => deliveryRequest("submit", body);
export const historyRequest = (session_id: string, page = 1): Promise<{ scenarios: ScenarioResult[]; page: number; pages: number }> => deliveryRequest("history", { session_id, page });
export const resultsRequest = (session_id: string, event_id: string): Promise<ScenarioResult | { missing: true }> => deliveryRequest("results", { session_id, event_id });

export class ApiError extends Error {
  constructor(public code: string, public fields: Record<string, string> = {}) { super(code); }
}

export async function preparationRequest(session_id: string, inputs: ScenarioInputs): Promise<PreparedScenario> {
  const response = await fetch("/api/test/scenarios/prepare", {
    method: "POST", cache: "no-store", signal: AbortSignal.timeout(8000),
    headers: { "Content-Type": "application/json", "X-QuakeStrike-Test": "1" },
    body: JSON.stringify({ session_id, inputs }),
  });
  const result = await response.json();
  if (!response.ok) throw new ApiError(result.error ?? "request-failed", result.fields ?? {});
  return result;
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
