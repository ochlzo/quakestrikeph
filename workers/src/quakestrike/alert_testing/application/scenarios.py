from dataclasses import asdict
from random import Random
from uuid import uuid4

from quakestrike.alert_testing.domain.scenarios import WINDOW_MS, validate_inputs
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.domain.synthetic_observations import generate_observations
from quakestrike.alert_testing.domain.testers import identity


class Scenarios:
    def __init__(self, sessions, random_factory=Random, signer=None):
        self.sessions = sessions
        self.random_factory = random_factory
        self.signer = signer

    def _active(self, session_id):
        session = self.sessions.read()
        if session.get("status") != "active" or session.get("session_id") != session_id:
            raise SessionConflict
        return session

    def prepare(self, session_id, inputs):
        session_id = identity(session_id)
        session = self._active(session_id)
        values = validate_inputs(inputs)
        event_id = str(uuid4())
        observations = generate_observations(
            values, session["server_time_ms"], self.random_factory().random, event_id
        )
        # Closure, expiry, or replacement during generation makes the response unusable.
        self._active(session_id)
        scenario = {
            "version": 1,
            "session_id": session_id,
            "event_id": event_id,
            "prepared_at_ms": session["server_time_ms"],
            "expires_at_ms": session["expires_at_ms"],
            "event": {
                "location": values.location,
                "magnitude": values.magnitude,
                "depth_km": values.depth,
                "latitude": values.latitude,
                "longitude": values.longitude,
                "event_time_ms": values.event_time_ms,
            },
            "forecast": {
                "window_start_ms": values.event_time_ms,
                "window_end_ms": values.event_time_ms + WINDOW_MS,
                "p1": values.p1,
                "p4": values.p4,
                "p5": values.p5,
                "count": values.count,
                "radius_km": values.radius,
                "quantiles": values.quantiles,
            },
            "replay": {
                "local": values.local,
                "background": values.background,
                "spread": values.spread,
                "spillover": values.spillover,
            },
            "observations": [asdict(observation) for observation in observations],
        }
        if self.signer is not None:
            scenario["preparation_token"] = self.signer.token(scenario, inputs)
        return scenario
