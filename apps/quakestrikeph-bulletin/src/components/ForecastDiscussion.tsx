import type { components } from "../lib/api/schema";
import { magnitude } from "../lib/events";

interface Props {
  forecast: components["schemas"]["SimulatedForecast"];
  simulated?: boolean;
}

export default function ForecastDiscussion({ forecast, simulated = false }: Props) {
  const percent = (value: number) =>
    value > 0 && value < 0.005
      ? "<1%"
      : value < 1 && value >= 0.995
        ? ">99%"
        : String(Math.round(value * 100)) + "%";
  const count = (value: number) => new Intl.NumberFormat("en-PH", { maximumFractionDigits: 2 }).format(value);
  const expectedCount = forecast.expectedM1PlusCount24h;
  const countStepBase = 10 ** Math.floor(Math.log10(Math.max(1, expectedCount / 3)));
  const countStep = [1, 2, 5, 10].find((step) => step * countStepBase >= expectedCount / 3)! * countStepBase;
  const countPosition = (expectedCount / (countStep * 3)) * 100;
  const magnitudeEstimates =
    forecast.maximumMagnitudeQ05_24h !== null &&
    forecast.maximumMagnitudeQ50_24h !== null &&
    forecast.maximumMagnitudeQ95_24h !== null
      ? [forecast.maximumMagnitudeQ05_24h, forecast.maximumMagnitudeQ50_24h, forecast.maximumMagnitudeQ95_24h]
      : [];
  const magnitudeMinimum = Math.floor((magnitudeEstimates[0] ?? 1) - 1);
  const magnitudeMaximum = Math.ceil((magnitudeEstimates[2] ?? 1) + 1);
  const magnitudePosition = (value: number) =>
    ((value - magnitudeMinimum) / (magnitudeMaximum - magnitudeMinimum)) * 100;
  const magnitudeMiddlePosition = Math.max(20, Math.min(80, magnitudePosition(magnitudeEstimates[1] ?? 1)));
  const magnitudeTicks = Array.from(
    { length: 5 },
    (_, index) => magnitudeMinimum + (index * (magnitudeMaximum - magnitudeMinimum)) / 4,
  );
  const probabilities = [
    { threshold: "1.0", value: forecast.probabilityM1Plus24h },
    { threshold: "4.0", value: forecast.probabilityM4Plus24h },
    { threshold: "5.0", value: forecast.probabilityM5Plus24h },
  ];
  let chanceBounds = { x: 0, y: 0, width: 416, height: 296 };
  const chanceBoxes = probabilities.map((item, index) => {
    const scale = Math.sqrt(item.value);
    // Keep labels readable for small probabilities and separated for similar probabilities.
    const width = Math.min(Math.max([240, 156, 96][index], 400 * scale), chanceBounds.width - 16);
    const height = Math.min(
      Math.max([176, 112, 60][index], 280 * scale),
      chanceBounds.height - (index === 0 ? 16 : 48),
    );
    const x = chanceBounds.x + chanceBounds.width - width - 8;
    const y = chanceBounds.y + chanceBounds.height - height - 8;
    chanceBounds = { x, y, width, height };
    return { ...item, ...chanceBounds };
  });
  const chanceFrame = chanceBoxes[0];
  const chanceViewBox = [
    chanceFrame.x - 8,
    chanceFrame.y - 8,
    chanceFrame.width + 16,
    chanceFrame.height + 16,
  ].join(" ");
  const magnitudeCopy =
    "These estimates describe the largest qualifying earthquake if further activity of magnitude 1.0 or higher occurs. They do not mean an earthquake is certain.";

  return (
    <>
      <section className="details-section" id="forecast-details" aria-labelledby="details-title">
        <div className="details-intro">
          <h2 id="details-title">Understand the forecast</h2>
        </div>
        <section className="explanation-section" id="forecast-panel-activity" aria-labelledby="chance-title">
          <h3 id="chance-title">Chance of at least one earthquake</h3>
          <div className="panel-columns">
            <div className="visual chance-visual">
              <svg
                className="chance-chart"
                viewBox={chanceViewBox}
                role="img"
                aria-label={
                  "Chance of at least one earthquake during the same 24-hour period: " +
                  probabilities
                    .map((item) => `magnitude ${item.threshold} or higher, ${percent(item.value)}`)
                    .join("; ")
                }
              >
                {chanceBoxes.map((box, index) => (
                  <g key={box.threshold} className={"chance-tier-" + index}>
                    <rect x={box.x} y={box.y} width={box.width} height={box.height} rx="12" />
                    <text x={box.x + 16} y={box.y + 34}>
                      {percent(box.value)}
                    </text>
                  </g>
                ))}
              </svg>
              <ul className="chance-legend" aria-label="Magnitude thresholds">
                {probabilities.map((item, index) => (
                  <li key={item.threshold}>
                    <span className={"chance-swatch chance-tier-" + index} aria-hidden="true" />
                    <span>Magnitude {item.threshold} or higher</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="explanation-copy">
              <p>
                Each percentage shows the chance of at least one earthquake of that magnitude or higher during
                the same 24-hour period.
              </p>
              <p>
                Earthquakes of magnitude 5.0 or higher also count toward the chances for magnitude 4.0 and 1.0
                or higher. The chances overlap, so do not add the percentages together.
              </p>
              <p>
                These are estimates. Even a high chance does not mean an earthquake is certain, and a low
                chance does not rule one out.
              </p>
            </div>
          </div>
        </section>
        <section className="explanation-section" id="forecast-count" aria-labelledby="count-title">
          <h3 id="count-title">Expected number of earthquakes</h3>
          <div className="panel-columns">
            <div className="visual count-visual">
              <div
                className="count-ruler"
                role="img"
                aria-label={`Estimated average: ${count(expectedCount)} earthquakes of magnitude 1.0 or higher during the 24-hour forecast window.`}
              >
                <div
                  className="count-reading"
                  style={{
                    left: `${countPosition}%`,
                    transform: `translateX(${countPosition < 25 ? "0" : countPosition > 75 ? "-100%" : "-50%"})`,
                  }}
                  aria-hidden="true"
                >
                  <strong className="count-value">{count(forecast.expectedM1PlusCount24h)}</strong>
                  <span>Estimated average</span>
                </div>
                <div className="count-axis" aria-hidden="true">
                  <span className="count-axis-line" />
                  {[0, 1, 2, 3].map((index) => (
                    <span key={index} className="count-tick" style={{ left: `${(index / 3) * 100}%` }}>
                      <span>{count(index * countStep)}</span>
                    </span>
                  ))}
                  <svg
                    className="count-continuation"
                    viewBox="0 0 24 16"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1"
                  >
                    <path d="m16 2 6 6-6 6" />
                  </svg>
                  <svg
                    className="count-marker"
                    style={{ left: `${countPosition}%` }}
                    viewBox="0 0 16 36"
                    fill="none"
                  >
                    <path d="M8 0v26" stroke="currentColor" strokeWidth="2" />
                    <path d="m1 26 7 9 7-9Z" fill="currentColor" />
                  </svg>
                </div>
              </div>
              <span>Magnitude 1.0 or higher · 24-hour window</span>
            </div>
            <div className="explanation-copy">
              <p>
                The model estimates an average of {count(expectedCount)} earthquakes during this 24-hour
                period. Actual earthquakes occur in whole numbers, so the total could be lower or higher.
              </p>
            </div>
          </div>
        </section>
        <section
          className="explanation-section"
          id="forecast-panel-magnitude"
          aria-labelledby="magnitude-title"
        >
          <h3 id="magnitude-title">Largest earthquake magnitude</h3>
          <div className="panel-columns">
            <div className="visual magnitude-visual">
              {magnitudeEstimates.length === 3 ? (
                <div
                  className="magnitude-ruler"
                  role="img"
                  aria-label={`Largest earthquake magnitude estimates: lower ${magnitude(magnitudeEstimates[0])}, middle ${magnitude(magnitudeEstimates[1])}, upper ${magnitude(magnitudeEstimates[2])}. These estimates apply if further activity of magnitude 1.0 or higher occurs during the 24-hour forecast window.`}
                >
                  <div
                    className="magnitude-reading magnitude-middle"
                    style={{ left: `${magnitudeMiddlePosition}%` }}
                    aria-hidden="true"
                  >
                    <strong>{magnitude(magnitudeEstimates[1])}</strong>
                    <span>Middle estimate</span>
                  </div>
                  <svg
                    className="magnitude-axis"
                    viewBox="0 0 1000 96"
                    preserveAspectRatio="none"
                    aria-hidden="true"
                  >
                    <rect
                      className="magnitude-band"
                      x={magnitudePosition(magnitudeEstimates[0]) * 10}
                      y="14"
                      width={
                        (magnitudePosition(magnitudeEstimates[2]) -
                          magnitudePosition(magnitudeEstimates[0])) *
                        10
                      }
                      height="20"
                      rx="4"
                    />
                    <path d="M0 24h1000M8 18l-8 6 8 6m984-12 8 6-8 6" />
                    {magnitudeTicks.map((_, index) => (
                      <path key={index} d={`M${index * 250} 36v6`} />
                    ))}
                    {[0, 2].map((index) => (
                      <path
                        key={index}
                        className="magnitude-end-marker"
                        d={`M${magnitudePosition(magnitudeEstimates[index]) * 10} 10v28`}
                      />
                    ))}
                    <path
                      className="magnitude-middle-marker"
                      d={`M${magnitudeMiddlePosition * 10} -10L${magnitudePosition(magnitudeEstimates[1]) * 10} 14v24`}
                    />
                  </svg>
                  <div className="magnitude-ticks" aria-hidden="true">
                    {magnitudeTicks.map((value, index) => (
                      <span key={index} style={{ left: `${index * 25}%` }}>
                        {count(value)}
                      </span>
                    ))}
                  </div>
                  <div className="magnitude-bounds" aria-hidden="true">
                    {[0, 2].map((index) => (
                      <div key={index} className="magnitude-bound">
                        <strong>{magnitude(magnitudeEstimates[index])}</strong>
                        <span>{index === 0 ? "Lower estimate" : "Upper estimate"}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p>The magnitude estimates are unavailable.</p>
              )}
            </div>
            <div className="explanation-copy">
              <h4>What the estimates tell you</h4>
              {magnitudeEstimates.length === 3 ? (
                <>
                  <p>
                    If further earthquakes of magnitude 1.0 or higher occur during the 24-hour period, the
                    model’s middle estimate for the largest is magnitude {magnitudeEstimates[1].toFixed(1)}.
                  </p>
                  <p>
                    The lower estimate of {magnitudeEstimates[0].toFixed(1)} and upper estimate of{" "}
                    {magnitudeEstimates[2].toFixed(1)} show uncertainty around that estimate. The largest
                    earthquake could fall outside these values.
                  </p>
                  <p>These estimates do not mean an earthquake will occur.</p>
                </>
              ) : (
                <p>{magnitudeCopy}</p>
              )}
            </div>
          </div>
        </section>
        <section className="explanation-section" id="forecast-panel-area" aria-labelledby="area-title">
          <h3 id="area-title">Distance from the {simulated ? "simulated" : "observed"} earthquake</h3>
          <div className="panel-columns">
            {forecast.activityRadiusMedianKm24h === null ? (
              <div className="visual">
                <p>The activity radius is unavailable.</p>
              </div>
            ) : (
              <div className="visual area-visual">
                <svg
                  viewBox="0 0 300 300"
                  role="img"
                  aria-label={
                    "Conceptual radius diagram: " +
                    count(forecast.activityRadiusMedianKm24h) +
                    " kilometres from the " +
                    (simulated ? "simulated" : "original") +
                    " earthquake’s epicenter to the dashed boundary; not a geographic map"
                  }
                >
                  <circle className="area-boundary" cx="150" cy="150" r="138" />
                  <path className="area-radius" d="M150 150h138m0-6v12" />
                  <circle className="area-epicenter" cx="150" cy="150" r="6" />
                </svg>
                <div className="area-reading">
                  <strong>
                    {count(forecast.activityRadiusMedianKm24h)} <span>km</span>
                  </strong>
                  <span>Estimated activity radius</span>
                </div>
                <span className="area-origin">
                  {simulated ? "Simulated" : "Original"} earthquake’s epicenter
                </span>
              </div>
            )}
            <div className="explanation-copy">
              <h4>What the radius means</h4>
              <p>
                If further earthquakes of magnitude 1.0 or higher occur during the 24-hour period, the model
                estimates their typical spread from the {simulated ? "simulated" : "original"} earthquake’s
                epicenter.
              </p>
              {forecast.activityRadiusMedianKm24h !== null && (
                <p>
                  The estimated radius is <strong>{count(forecast.activityRadiusMedianKm24h)} km</strong>.
                  Further earthquakes may occur beyond this distance.
                </p>
              )}
              <p>
                This radius does not show how far shaking reaches, where damage occurs, or where people are
                safe.
              </p>
            </div>
          </div>
        </section>
      </section>
    </>
  );
}
