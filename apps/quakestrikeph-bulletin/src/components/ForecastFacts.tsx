import { Fragment } from "react";
import type { components } from "../lib/api/schema";
import { magnitude, likelihoodLevel } from "../lib/events";

interface Props {
  forecast: components["schemas"]["SimulatedForecast"];
  simulated?: boolean;
}

export default function ForecastFacts({ forecast, simulated = false }: Props) {
  const percent = (value: number) =>
    value > 0 && value < 0.005
      ? "<1%"
      : value < 1 && value >= 0.995
        ? ">99%"
        : String(Math.round(value * 100)) + "%";
  const count = (value: number) => new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 }).format(value);
  const probabilities = [
    { threshold: "1.0", value: forecast.probabilityM1Plus24h },
    { threshold: "4.0", value: forecast.probabilityM4Plus24h },
    { threshold: "5.0", value: forecast.probabilityM5Plus24h },
  ];
  const magnitudeCopy =
    "These estimates describe the largest qualifying earthquake if further activity of magnitude 1.0 or higher occurs. They do not mean an earthquake is certain.";
  const countCopy = `The model estimates an average of ${count(forecast.expectedM1PlusCount24h)} earthquakes of magnitude 1.0 or higher during the 24-hour forecast window. The estimate can include decimals because it is an average. The actual number of earthquakes will be a whole number and may differ from the estimate.`;
  const radiusCopy =
    forecast.activityRadiusMedianKm24h !== null
      ? `The model estimates a typical spread of ${count(forecast.activityRadiusMedianKm24h)} km from the ${simulated ? "simulated" : "original"} earthquake’s epicenter during the 24-hour forecast window. This assumes an earthquake of magnitude 1.0 or higher occurs. Earthquakes may occur beyond this radius. The radius does not show shaking, damage, or a safe boundary.`
      : "The activity radius estimate is unavailable.";

  return (
    <>
      <section className="forecast-facts" aria-labelledby="activity-chance-title">
        {probabilities.map((item, index) => {
          const Wrapper = index === 0 ? "h2" : "div";
          return (
            <Fragment key={item.threshold}>
              <Wrapper>
                <button
                  className={index === 0 ? "probability probability-primary" : "probability"}
                  aria-expanded="false"
                  aria-controls={"explain-m" + item.threshold[0]}
                >
                  <span className="probability-label">
                    {index === 0 ? (
                      <span className="probability-title" id="activity-chance-title">
                        Chance of any further activity
                      </span>
                    ) : (
                      <span>Chance of further activity</span>
                    )}
                    <span className="estimate-threshold">Magnitude {item.threshold} or higher</span>
                  </span>
                  <strong className="fact-value">
                    {percent(item.value)}
                    {index === 0 && (
                      <span className="probability-level">
                        {" "}
                        ({likelihoodLevel(item.value).replace(" likelihood", "")})
                      </span>
                    )}
                  </strong>
                  <svg
                    className="chevron"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    aria-hidden="true"
                  >
                    <path d="m6 9 6 6 6-6" />
                  </svg>
                </button>
              </Wrapper>
              <div className="probability-explanation" id={"explain-m" + item.threshold[0]} hidden>
                {index === 0 ? (
                  <p>
                    The model estimates a {percent(item.value)} chance of at least one earthquake of magnitude{" "}
                    {item.threshold} or higher during the 24-hour forecast window. This estimate does not
                    guarantee that an earthquake will occur.
                  </p>
                ) : (
                  <p>
                    The “any further activity” estimate includes earthquakes of magnitude 1.0 or higher. This
                    row focuses on magnitude {item.threshold} or higher, with a {percent(item.value)} chance
                    of at least one during the same 24-hour window. These earthquakes are also included in the
                    broader estimate, so the percentages should not be added together.
                  </p>
                )}
              </div>
            </Fragment>
          );
        })}
      </section>
      <div className="supporting-estimates">
        <h2>Activity estimates</h2>
        <details name="possible-activity">
          <summary>
            <span>
              Expected number of earthquakes
              <span className="estimate-threshold">Magnitude 1.0 or higher</span>
            </span>
            <strong className="fact-value">{count(forecast.expectedM1PlusCount24h)}</strong>
            <svg
              className="chevron"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <div className="disclosure-body">
            <p>{countCopy}</p>
          </div>
        </details>
        <details name="possible-activity">
          <summary>
            <span>Estimated largest earthquake magnitude</span>
            <strong
              className={
                forecast.maximumMagnitudeQ50_24h === null ? "fact-value unavailable-value" : "fact-value"
              }
            >
              {forecast.maximumMagnitudeQ50_24h === null
                ? "Unavailable"
                : magnitude(forecast.maximumMagnitudeQ50_24h)}
            </strong>
            <svg
              className="chevron"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <div className="disclosure-body">
            {forecast.maximumMagnitudeQ50_24h === null ? (
              <p>The middle estimate is unavailable. {magnitudeCopy}</p>
            ) : (
              <p>
                The model’s middle estimate for the largest earthquake during the 24-hour forecast window is
                magnitude {forecast.maximumMagnitudeQ50_24h.toFixed(1)}. This assumes an earthquake of
                magnitude 1.0 or higher occurs. The largest earthquake could be smaller or larger; magnitude{" "}
                {forecast.maximumMagnitudeQ50_24h.toFixed(1)} is not an upper limit.
              </p>
            )}
          </div>
        </details>
        <details name="possible-activity">
          <summary>
            <span>Estimated activity radius</span>
            <strong
              className={
                forecast.activityRadiusMedianKm24h === null ? "fact-value unavailable-value" : "fact-value"
              }
            >
              {forecast.activityRadiusMedianKm24h === null
                ? "Unavailable"
                : count(forecast.activityRadiusMedianKm24h) + " km"}
            </strong>
            <svg
              className="chevron"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              aria-hidden="true"
            >
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <div className="disclosure-body">
            <p>{radiusCopy}</p>
          </div>
        </details>
      </div>
      <p className="essential-note">Forecasts are estimates, not exact predictions.</p>
    </>
  );
}
