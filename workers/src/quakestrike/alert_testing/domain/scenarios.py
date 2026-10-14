import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

EARTH_RADIUS_KM = 6371.0088
MAX_DISTANCE_KM = math.pi * EARTH_RADIUS_KM
WINDOW_MS = 86_400_000
INPUT_FIELDS = {
    "location",
    "magnitude",
    "depth",
    "latitude",
    "longitude",
    "time",
    "p1",
    "p4",
    "p5",
    "count",
    "radius",
    "q05",
    "q50",
    "q95",
    "local",
    "background",
    "spread",
    "spillover",
    "preset",
}


class ScenarioValidation(ValueError):
    def __init__(self, fields):
        self.fields = fields
        super().__init__("Invalid scenario inputs.")


@dataclass(frozen=True)
class ScenarioInputs:
    location: str
    magnitude: float
    depth: float
    latitude: float
    longitude: float
    event_time_ms: int
    p1: float
    p4: float
    p5: float
    count: float
    radius: float
    quantiles: tuple[float, float, float] | None
    local: int
    background: int
    spread: float
    spillover: int


def validate_inputs(inputs) -> ScenarioInputs:
    if not isinstance(inputs, dict) or set(inputs) != INPUT_FIELDS:
        raise ValueError("Invalid input fields.")
    if any(not isinstance(value, str) or len(value) > 250 for value in inputs.values()):
        raise ValueError("Inputs must be bounded strings.")
    errors = {}

    def number(name, lower, upper=math.inf, *, integer=False, positive=False):
        try:
            value = float(inputs[name])
            if not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError
            if (integer and not value.is_integer()) or (positive and value <= 0):
                raise ValueError
            return int(value) if integer else value
        except (ValueError, OverflowError):
            errors[name] = (
                "Enter a valid whole number."
                if integer
                else "Enter a finite value within the allowed range."
            )
            return 0

    location = inputs["location"].strip()
    if not location:
        errors["location"] = "Enter a location description."
    magnitude = number("magnitude", 1, 10)
    depth = number("depth", 0, 700)
    latitude = number("latitude", -90, 90)
    longitude = number("longitude", -180, 180)
    event_time_ms = 0
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", inputs["time"]):
            raise ValueError
        event = datetime.fromisoformat(inputs["time"]).replace(tzinfo=timezone(timedelta(hours=8)))
        event_time_ms = int(event.timestamp() * 1000)
        event + timedelta(hours=24)
    except (ValueError, OverflowError, OSError):
        errors["time"] = "Choose a valid event date and time."
    p1, p4, p5 = (number(name, 0, 100) for name in ("p1", "p4", "p5"))
    if not p1 >= p4 >= p5:
        for name in ("p1", "p4", "p5"):
            errors[name] = "Use M1.0+ ≥ M4.0+ ≥ M5.0+ probabilities."
    count = number("count", 0)
    radius = number("radius", 0, MAX_DISTANCE_KM - 0.001, positive=True)
    if "radius" in errors:
        errors["radius"] = "Use a positive radius below 20,015 km to allow observations outside it."
    quantiles = None
    names = ("q05", "q50", "q95")
    if any(inputs[name].strip() for name in names):
        quantiles = tuple(number(name, -math.inf) for name in names)
        if (
            not all(inputs[name].strip() for name in names)
            or not quantiles[0] <= quantiles[1] <= quantiles[2]
        ):
            for name in names:
                errors[name] = "Supply all three ordered estimates, or leave all three empty."
    local = number("local", 1, 100, integer=True)
    background = number("background", 0, 100, integer=True)
    spread = number("spread", 0, 100)
    spillover = number("spillover", 0, 100, integer=True)
    if spillover >= local:
        errors["spillover"] = "Keep at least one local observation inside the radius."
    if inputs["preset"] not in {"low", "moderate", "high"}:
        errors["preset"] = "Choose a forecast preset."
    if errors:
        raise ScenarioValidation(errors)
    return ScenarioInputs(
        location,
        magnitude,
        depth,
        latitude,
        longitude,
        event_time_ms,
        p1 / 100,
        p4 / 100,
        p5 / 100,
        count,
        radius,
        quantiles,
        local,
        background,
        spread,
        spillover,
    )
