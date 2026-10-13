import math
from dataclasses import dataclass
from uuid import UUID, uuid5

from quakestrike.alert_testing.domain.scenarios import (
    EARTH_RADIUS_KM,
    MAX_DISTANCE_KM,
    WINDOW_MS,
    ScenarioInputs,
)


@dataclass(frozen=True)
class Observation:
    event_id: str
    event_time_ms: int
    latitude: float
    longitude: float
    magnitude: float
    depth_km: float
    location_description: str
    kind: str
    distance_km: float
    bearing_radians: float


def generate_observations(
    inputs: ScenarioInputs, now_ms: int, random, event_id: str
) -> tuple[Observation, ...]:
    """Generate once from supplied time/randomness; readers retain these exact values."""
    start = inputs.event_time_ms
    end = start + WINDOW_MS
    # Past anchors replay immediately; future anchors stay hidden until their clock arrives.
    replay_end = min(end, now_ms) if now_ms > start else end
    latitude, longitude = math.radians(inputs.latitude), math.radians(inputs.longitude)
    remaining_spillover = inputs.spillover
    observations = []
    for index in range(inputs.local + inputs.background):
        distant = index >= inputs.local
        spillover = not distant and random() < remaining_spillover / (inputs.local - index)
        if spillover:
            remaining_spillover -= 1
        bearing, radial = random() * math.tau, random()
        if distant:
            minimum = min(
                inputs.radius * 3 + 200, inputs.radius + (MAX_DISTANCE_KM - inputs.radius) * 0.5
            )
            maximum = min(minimum + 500, minimum + (MAX_DISTANCE_KM - minimum) * 0.9)
            distance = minimum + radial * (maximum - minimum)
        elif spillover:
            distance = inputs.radius + min(
                inputs.radius * (0.05 + radial * 0.17), (MAX_DISTANCE_KM - inputs.radius) * 0.9
            )
        else:
            distance = inputs.radius * (0.05 + 0.9 * radial ** (1.8 - inputs.spread * 0.008))
        angular = distance / EARTH_RADIUS_KM
        next_latitude = math.asin(
            max(
                -1,
                min(
                    1,
                    math.sin(latitude) * math.cos(angular)
                    + math.cos(latitude) * math.sin(angular) * math.cos(bearing),
                ),
            )
        )
        next_longitude = longitude + math.atan2(
            math.sin(bearing) * math.sin(angular) * math.cos(latitude),
            math.cos(angular) - math.sin(latitude) * math.sin(next_latitude),
        )
        magnitude, depth = round(1 + random() * 4, 1), round(5 + random() * 55, 1)
        timestamp = start + max(1, math.ceil((0.001 + random() * 0.999) * (replay_end - start)))
        observations.append(
            Observation(
                str(uuid5(UUID(event_id), str(index))),
                timestamp,
                math.degrees(next_latitude),
                (math.degrees(next_longitude) + 180) % 360 - 180,
                magnitude,
                depth,
                "Distant background observation" if distant else f"Near {inputs.location}",
                "background" if distant else "spillover" if spillover else "inside",
                distance,
                bearing,
            )
        )
    return tuple(
        sorted(
            observations, key=lambda observation: (observation.event_time_ms, observation.event_id)
        )
    )
