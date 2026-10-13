from uuid import uuid4

from quakestrike.alert_testing.domain.scenarios import validate_inputs
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.domain.testers import identity, selection


class Submissions:
    def __init__(self, sessions, store, signer):
        self.sessions, self.store, self.signer = sessions, store, signer

    def _active(self, session_id):
        session = self.sessions.read()
        if session.get("status") != "active" or session.get("session_id") != session_id:
            raise SessionConflict
        return session

    def submit(self, session_id, inputs, scenario, selected):
        owner = identity(session_id)
        session = self._active(owner)
        selected = selection(selected)
        if not selected:
            raise ValueError("Select at least one tester.")
        validate_inputs(inputs)
        self.signer.verify(scenario, inputs)
        event_id = identity(scenario["event_id"])
        if (
            scenario["session_id"] != owner
            or scenario["expires_at_ms"] != session["expires_at_ms"]
            or not session["started_at_ms"]
            <= scenario["prepared_at_ms"]
            <= session["server_time_ms"]
        ):
            raise ValueError("Stale preparation.")
        # Retries load the immutable original before checking forecast age again.
        return self.store.submit(owner, event_id, scenario, inputs, selected)

    def history(self, session_id, page=1):
        owner = identity(session_id)
        if type(page) is not int or not 1 <= page <= 10000:
            raise ValueError("Invalid history page.")
        self._active(owner)
        return self.store.history(owner, page)

    def results(self, session_id, event_id):
        owner, event = identity(session_id), identity(event_id)
        self._active(owner)
        return self.store.results(owner, event)


def submitted_record(scenario, now):
    return {
        "version": 1,
        "submitted": True,
        "submitted_at_ms": now,
        "event_revision_id": str(uuid4()),
        "forecast_id": str(uuid4()),
        "model_release_id": str(uuid4()),
        "scenario": scenario,
    }
