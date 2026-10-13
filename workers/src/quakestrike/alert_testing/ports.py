from typing import Protocol

from quakestrike.alert_testing.domain.sessions import Session


class SessionStore(Protocol):
    def read(self) -> Session | None: ...

    def start(self) -> Session: ...

    def close(self, session_id: str) -> Session: ...

    def cleanup(self, session_id: str) -> Session: ...


class AccountReader(Protocol):
    def search(self, query: str, selected: list[str] | None, page: int, size: int) -> dict: ...
