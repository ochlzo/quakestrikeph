import type { PreparedScenario } from "../../../../../packages/contracts/alert-testing/scenarios-v1";

export function ReplayDiagram({ scenario }: { scenario: PreparedScenario }) {
  const radius = scenario.forecast.radius_km;
  const background = scenario.observations.filter(point => point.kind === "background");
  const maximum = Math.max(radius, ...background.map(point => point.distance_km));
  return (
    <svg className="replay-diagram" viewBox="0 0 280 130" role="img"
      aria-label="Prepared replay: local observations, spillover, and distant background. Diagram is not to scale.">
      <circle cx="100" cy="65" r="47" fill="#edf6f6" stroke="#8fbcc1" strokeDasharray="4 3" />
      <path d="M93 65h14m-7-7v14" stroke="#1a2c30" strokeWidth="2" />
      {scenario.observations.map(point => {
        const distant = point.kind === "background";
        const distance = point.distance_km / radius * 47;
        const scale = 0.4 + 0.6 * point.distance_km / maximum;
        return <circle key={point.event_id}
          cx={distant ? 230 + Math.sin(point.bearing_radians) * 25 * scale : 100 + Math.sin(point.bearing_radians) * distance}
          cy={distant ? 65 - Math.cos(point.bearing_radians) * 40 * scale : 65 - Math.cos(point.bearing_radians) * distance}
          r="3" fill={distant ? "#67767b" : point.kind === "spillover" ? "#ae683c" : "#0e6873"}>
          <title>{point.kind}: M{point.magnitude.toFixed(1)}, {point.distance_km.toFixed(1)} km from the main event</title>
        </circle>;
      })}
      <text x="100" y="126" textAnchor="middle" fill="#536368" fontSize="10">Predicted radius</text>
      <text x="230" y="126" textAnchor="middle" fill="#536368" fontSize="10">Distant activity</text>
    </svg>
  );
}
