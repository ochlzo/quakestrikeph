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
    calls_until_ms: int = 0
    closed_at_ms: int = 0
    cleanup_completed_at_ms: int = 0

    @property
    def closure_phase(self) -> str:
        if self.lifecycle == "active":
            return "none"
        if self.cleanup in {"failed", "complete"}:
            return self.cleanup
        return "waiting" if self.calls_until_ms > self.server_time_ms else "deleting"

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
            "closure_phase": self.closure_phase,
            "calls_until_ms": self.calls_until_ms,
            "closed_at_ms": self.closed_at_ms,
            "cleanup_completed_at_ms": self.cleanup_completed_at_ms,
        }
