import { getSecret } from "astro:env/server";
import { unavailableCatalog, type SimulationCatalog } from "./forecast-simulations";

type SimulationPageData = {
  guestCookieConfirmed: boolean | null;
  catalog: SimulationCatalog;
  setCookie: string | null;
};

export async function loadSimulationPage(
  cookie: string | null,
  confirm: boolean,
): Promise<SimulationPageData> {
  const fallback = {
    guestCookieConfirmed: null,
    catalog: unavailableCatalog,
    setCookie: null,
  };
  const token = getSecret("SIMULATION_PAGE_TOKEN");
  if (!token) return fallback;

  try {
    const endpoint = new URL(
      "/internal/forecast-simulations/page",
      getSecret("SIMULATION_BACKEND_TARGET") || "http://127.0.0.1:3000",
    );
    if (confirm) endpoint.searchParams.set("confirm", "1");
    const response = await fetch(endpoint, {
      headers: {
        Authorization: `Bearer ${token}`,
        ...(cookie ? { Cookie: cookie } : {}),
      },
      signal: AbortSignal.timeout(6000),
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) return fallback;

    const data = await response.json();
    const catalog = data?.catalog;
    if (typeof data?.guestCookieConfirmed !== "boolean" || !catalog) return fallback;
    switch (catalog.status) {
      case "current":
      case "stale":
      case "too_old":
        if (!Number.isFinite(Date.parse(catalog.catalogCutoff))) return fallback;
        break;
      case "insufficient_history":
      case "unavailable":
        if (catalog.catalogCutoff !== null) return fallback;
        break;
      default:
        return fallback;
    }
    return {
      guestCookieConfirmed: data.guestCookieConfirmed,
      catalog,
      setCookie: response.headers.get("Set-Cookie"),
    };
  } catch {
    return fallback;
  }
}
