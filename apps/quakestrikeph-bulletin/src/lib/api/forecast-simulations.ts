import type { components } from "./schema";

export type SimulationScenario = components["schemas"]["ForecastSimulationScenario"];
export type SimulationResult = components["schemas"]["ForecastSimulationResult"];

export type SimulationCatalog = {
  status: "current" | "stale" | "insufficient_history" | "too_old" | "unavailable";
  catalogCutoff: string | null;
};

export const unavailableCatalog: SimulationCatalog = {
  status: "unavailable",
  catalogCutoff: null,
};

type Failure =
  | { state: "field"; field: keyof SimulationScenario; message: string }
  | { state: "limit"; retryAt: number | null }
  | { state: "catalog"; catalog: SimulationCatalog }
  | { state: "cookies" | "busy" | "quota" | "failed" | "invalid" | "unknown" };

type RunOutcome = { result: SimulationResult; catalog: SimulationCatalog } | Failure;

const dayMs = 86_400_000;

export async function runForecastSimulation(scenario: SimulationScenario): Promise<RunOutcome> {
  try {
    const response = await fetch("/api/v1/forecast-simulations", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(scenario),
    });
    // The edge can return a response without JSON, including a rate limit or timeout.
    const body = await response.json().catch(() => null);
    if (response.ok && body?.forecast && body?.scenario && Number.isFinite(Date.parse(body.catalogCutoff))) {
      const cutoff = Date.parse(body.catalogCutoff);
      const responseTime = Date.parse(response.headers.get("Date") ?? "");
      const now = Number.isFinite(responseTime) ? responseTime : Date.now();
      return {
        result: body,
        catalog: {
          status: now - cutoff > dayMs ? "stale" : "current",
          catalogCutoff: body.catalogCutoff,
        },
      };
    }
    const error = body?.error;
    if (response.status === 429) {
      return {
        state: "limit",
        retryAt: retryDeadline(response.headers.get("Retry-After"), error?.retryAt),
      };
    }
    if (response.status === 400 || response.status === 413) {
      const field: unknown = error?.field;
      if (typeof field === "string" && Object.hasOwn(scenario, field) && typeof error.message === "string") {
        return {
          state: "field",
          field: field as keyof SimulationScenario,
          message: error.message,
        };
      }
      return { state: "invalid" };
    }
    switch (error?.code) {
      case "SIMULATION_GUEST_COOKIE_REQUIRED":
        return { state: "cookies" };
      case "SIMULATION_BUSY":
        return { state: "busy" };
      case "SIMULATION_QUOTA_UNAVAILABLE":
        return { state: "quota" };
      case "SIMULATION_MODEL_FAILED":
        return { state: "failed" };
      case "SIMULATION_HISTORY_INSUFFICIENT":
        return {
          state: "catalog",
          catalog: { status: "insufficient_history", catalogCutoff: null },
        };
      case "SIMULATION_HISTORY_TOO_OLD":
        return {
          state: "catalog",
          catalog: { status: "too_old", catalogCutoff: error.catalogCutoff },
        };
      case "SIMULATION_CATALOG_UNAVAILABLE":
        return { state: "catalog", catalog: unavailableCatalog };
      default:
        return { state: "unknown" };
    }
  } catch {
    return { state: "unknown" };
  }
}

function retryDeadline(retryAfter: string | null, retryAt: unknown): number | null {
  const now = Date.now();
  // Relative seconds avoid depending on the browser clock matching the Backend clock.
  const deadline =
    retryAfter && /^\d+$/.test(retryAfter)
      ? now + Number(retryAfter) * 1000
      : Date.parse(typeof retryAt === "string" ? retryAt : (retryAfter ?? ""));
  return Number.isFinite(deadline) && deadline > now ? deadline : null;
}
