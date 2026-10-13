from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.ports import SessionStore


class Sessions:
    def __init__(self, store: SessionStore):
        self.store = store

    def read(self) -> dict[str, str | int]:
        session = self.store.read()
        return session.response() if session else {"status": "inactive"}

    def start(self) -> dict[str, str | int]:
        return self.store.start().response()

    def end(self, session_id: str) -> dict[str, str | int]:
        self.store.close(session_id)
        return self.store.cleanup(session_id).response()

    def retry_cleanup(self, session_id: str) -> dict[str, str | int]:
        session = self.store.read()
        if not session or session.session_id != session_id or session.lifecycle == "active":
            raise SessionConflict
        return self.store.cleanup(session_id).response()

    def maintain(self) -> None:
        session = self.store.read()
        if session and session.lifecycle != "active" and session.cleanup in {"pending", "running"}:
            self.store.cleanup(session.session_id)
