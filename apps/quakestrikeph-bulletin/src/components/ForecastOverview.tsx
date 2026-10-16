import { X } from "lucide-react";
import { Button } from "./ui/button";
import { likelihoodLevel, type Forecast } from "../lib/events";

export function forecastRadiusKm(forecast: Forecast | null) {
  const radius = forecast?.activityRadiusMedianKm24h;
  return radius !== null && radius !== undefined && Number.isFinite(radius) && radius >= 0
    ? radius
    : null;
}

function chance(value: number) {
  if (value > 0 && value < 0.005) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function forecastEnd(value: string) {
  return `${new Intl.DateTimeFormat("en-PH", {
    timeZone: "Asia/Manila", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", hour12: true,
  }).format(new Date(value))} PHT`;
}

export default function ForecastOverview({ forecast, status, onClose }: {
  forecast: Forecast | null;
  status: "loading" | "ready" | "error";
  onClose?: () => void;
}) {
  const radius = forecastRadiusKm(forecast);
  return (
    <div className="forecast-map-annotation" role="status" aria-live="polite">
      {onClose && (
        <Button variant="ghost" size="icon-xs" className="forecast-map-close"
          aria-label="Close forecast overview" onPress={onClose}>
          <X aria-hidden="true" />
        </Button>
      )}
      {status === "loading" ? (
        <span>Loading forecast…</span>
      ) : status === "error" ? (
        <span>Forecast details are unavailable right now.</span>
      ) : forecast ? (
        <>
          <h3 className="forecast-map-heading">Forecast Overview</h3>
          <span className="forecast-map-period">
            24-hour forecast {forecast.expired ? "ended" : "through"}{" "}
            {forecastEnd(forecast.windowEnd)}
          </span>
          <div className="forecast-map-occurrence">
            <span className="forecast-map-metric">
              <strong>{likelihoodLevel(forecast.probabilityM1Plus24h)}</strong>{" "}
              <strong>({chance(forecast.probabilityM1Plus24h)})</strong>
            </span>
            <p>Chance of at least one further earthquake near the epicenter.</p>
          </div>
          <div className="forecast-map-distance">
            <strong className="forecast-map-metric">
              {radius === null ? "Estimated activity radius unavailable"
                : `Estimated activity radius: ${Math.round(radius)} km`}
            </strong>
            {radius !== null && radius > 0 && (
              <p>
                The circle shows the system’s estimated reach of further activity
                from this earthquake over the 24-hour forecast window.
              </p>
            )}
          </div>
        </>
      ) : (
        <span>No forecast is available for this earthquake.</span>
      )}
    </div>
  );
}
