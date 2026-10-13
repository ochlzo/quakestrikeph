from dataclasses import dataclass

SESSION_LIFETIME_MS = 4 * 60 * 60 * 1000
CONTROL_RETENTION_MS = 24 * 60 * 60 * 1000


class SessionConflict(Exception):
    """The owning session changed, or closed-session cleanup is incomplete."""


@dataclass(frozen=True)
class Session:
    session_id: str
    started_at_ms: int
    expires_at_ms: int
    lifecycle: str
    cleanup: str
    server_time_ms: int

    @property
    def status(self) -> str:
        if self.cleanup == "failed":
            return "cleanup-failure"
        if self.lifecycle == "expired":
            return "expired"
        if self.lifecycle == "closed":
            return "ended" if self.cleanup == "complete" else "ending"
        return "active"

    def response(self) -> dict[str, str | int]:
        return {
            "status": self.status,
            "session_id": self.session_id,
            "started_at_ms": self.started_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "server_time_ms": self.server_time_ms,
            "cleanup": self.cleanup,
        }
