from quakestrike.alert_testing.application.submissions import submitted_record
from quakestrike.alert_testing.domain.scenarios import INPUT_FIELDS, validate_inputs
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.domain.testers import identity, selection


class Workspaces:
    def __init__(self, sessions, store, signer):
        self.sessions, self.store, self.signer = sessions, store, signer

    def _active(self, owner):
        session = self.sessions.read()
        if session.get("status") != "active" or session.get("session_id") != owner:
            raise SessionConflict
        return session

    def read(self, session_id, workspace_id):
        owner, workspace = identity(session_id), identity(workspace_id)
        self._active(owner)
        return self.store.read(owner, workspace)

    def save(self, session_id, workspace_id, revision, inputs, selected, scenario):
        owner, workspace = identity(session_id), identity(workspace_id)
        session = self._active(owner)
        if type(revision) is not int or not 0 <= revision < 1_000_000_000:
            raise ValueError("Invalid workspace revision.")
        if not isinstance(inputs, dict) or set(inputs) != INPUT_FIELDS:
            raise ValueError("Invalid workspace inputs.")
        if any(not isinstance(value, str) or len(value) > 250 for value in inputs.values()):
            raise ValueError("Inputs must be bounded strings.")
        selected = selection(selected)
        preview = None
        if scenario is not None:
            validate_inputs(inputs)
            self.signer.verify(scenario, inputs)
            identity(scenario["event_id"])
            if (
                scenario["session_id"] != owner
                or scenario["expires_at_ms"] != session["expires_at_ms"]
                or not session["started_at_ms"]
                <= scenario["prepared_at_ms"]
                <= session["server_time_ms"]
            ):
                raise ValueError("Stale preparation.")
            preview = submitted_record(scenario, session["server_time_ms"])
            preview.pop("submitted")
            preview["preview"] = True
            preview["saved_at_ms"] = preview.pop("submitted_at_ms")
        return self.store.save(
            owner,
            workspace,
            revision,
            {"inputs": inputs, "selected": selected, "prepared": scenario},
            preview,
        )
