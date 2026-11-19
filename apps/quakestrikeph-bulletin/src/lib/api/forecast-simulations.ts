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

export function readSimulationCatalog(status: unknown, cutoff: unknown): SimulationCatalog | null {
  switch (status) {
    case "current":
    case "stale":
    case "too_old":
      return typeof cutoff === "string" && Number.isFinite(Date.parse(cutoff))
        ? { status, catalogCutoff: cutoff }
        : null;
    case "insufficient_history":
    case "unavailable":
      return cutoff === null ? { status, catalogCutoff: null } : null;
    default:
      return null;
  }
}

export async function refreshSimulationPage(signal: AbortSignal, confirmOnly: boolean) {
  try {
    // Use the existing page so only the Bulletin server calls the private Backend route.
    const url = new URL(window.location.pathname, window.location.origin);
    if (confirmOnly) url.searchParams.set("confirm", "1");
    const response = await fetch(url, {
      mode: "same-origin",
      cache: "no-store",
      signal: AbortSignal.any([signal, AbortSignal.timeout(8000)]),
    });
    if (!response.ok) return null;
    const template = document.createElement("template");
    template.innerHTML = await response.text();
    const page = template.content.querySelector("#simulator");
    if (!page) return null;
    const catalog = readSimulationCatalog(
      page.getAttribute("data-catalog-status"),
      page.getAttribute("data-catalog-cutoff"),
    );
    const cookie = page.getAttribute("data-guest-cookie-confirmed");
    return catalog ? { catalog, guestCookieConfirmed: cookie === null ? null : cookie === "true" } : null;
  } catch {
    return null;
  }
}

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
