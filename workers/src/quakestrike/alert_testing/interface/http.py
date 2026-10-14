import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import unquote, urlsplit
from uuid import UUID

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.domain.scenarios import ScenarioValidation
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.accounts import AccountAccessUnavailable

API_PATH = "/api/test/session"


def validate_origin(origin: str) -> str:
    url = urlsplit(origin)
    if url.path or url.query or url.fragment or url.username or url.password:
        raise ValueError("Use an exact origin without a path or credentials.")
    loopback = url.scheme == "http" and url.hostname == "127.0.0.1"
    tailnet = (
        url.scheme == "https"
        and bool(re.fullmatch(r"[a-z0-9.-]+\.ts\.net", url.hostname or ""))
        and url.port in {None, 443, 8443}
    )
    if not (loopback or tailnet):
        raise ValueError("The origin must use loopback HTTP or private Tailscale HTTPS.")
    return origin


class PrivateServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(
        self,
        sessions: Sessions,
        static_directory: Path,
        port: int = 4341,
        origin: str | None = None,
        testers=None,
        scenarios=None,
        submissions=None,
    ):
        self.sessions = sessions
        self.testers = testers
        self.scenarios = scenarios
        self.submissions = submissions
        self.static_directory = static_directory.resolve()
        self.slots = BoundedSemaphore(16)
        if origin is not None:
            validate_origin(origin)
        super().__init__(("127.0.0.1", port), PrivateHandler)
        self.origin = origin or f"http://127.0.0.1:{self.server_port}"
        self.authority = urlsplit(self.origin).netloc

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(8)
        return connection, address

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class PrivateHandler(BaseHTTPRequestHandler):
    server: PrivateServer
    server_version = "QuakeStrikePrivate"
    sys_version = ""

    def log_message(self, format, *args):
        # The tool has no need to retain request paths or operator information.
        pass

    def _respond(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._respond(status, json.dumps(data).encode(), "application/json")

    def _private_host(self) -> bool:
        if self.headers.get_all("Host") != [self.server.authority]:
            self._json(403, {"error": "private-origin-required"})
            return False
        return True

    def _workflow(self, action, *args) -> None:
        try:
            self._json(200, action(*args))
        except SessionConflict:
            self._json(409, {"error": "session-conflict"})
        except ScenarioValidation as error:
            self._json(400, {"error": "invalid-scenario", "fields": error.fields})
        except ValueError:
            self._json(400, {"error": "invalid-request"})
        except (SQLAlchemyError, AccountAccessUnavailable):
            self._json(503, {"error": "dependency-unavailable", "dependency": "Accounts"})
        except RedisError:
            self._json(503, {"error": "dependency-unavailable", "dependency": "Redis"})

    def do_GET(self):
        if not self._private_host():
            return
        if self.path == API_PATH:
            self._workflow(self.server.sessions.read)
            return
        path = unquote(urlsplit(self.path).path)
        pages = {
            "/": "index.html",
            "/testers": "testers/index.html",
            "/history": "history/index.html",
        }
        relative = pages.get(path.rstrip("/") or "/")
        if re.fullmatch(r"/results/[0-9a-f-]{36}/?", path):
            relative = "results/index.html"
        if relative is None and path.startswith("/_astro/"):
            relative = path.lstrip("/")
        if relative is None:
            self._json(404, {"error": "not-found"})
            return
        target = (self.server.static_directory / relative).resolve()
        if not target.is_relative_to(self.server.static_directory) or not target.is_file():
            self._json(404, {"error": "not-found"})
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        # Windows can register JavaScript as text/plain, which nosniff rejects.
        if target.suffix == ".js":
            content_type = "text/javascript"
        self._respond(200, target.read_bytes(), content_type)

    def do_POST(self):
        if not self._private_host():
            return
        if (
            self.headers.get_all("Origin") != [self.server.origin]
            or self.headers.get_all("X-QuakeStrike-Test") != ["1"]
            or self.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            self._json(403, {"error": "private-origin-required"})
            return
        actions = {
            API_PATH + "/start": self.server.sessions.start,
            API_PATH + "/end": self.server.sessions.end,
            API_PATH + "/cleanup": self.server.sessions.retry_cleanup,
        }
        account_action = self.path == "/api/test/testers"
        preparation_action = self.path == "/api/test/scenarios/prepare"
        submission_action = self.path in {
            "/api/test/scenarios/submit",
            "/api/test/scenarios/history",
            "/api/test/scenarios/results",
        }
        if (
            self.path not in actions
            and not account_action
            and not preparation_action
            and not submission_action
        ):
            self._json(404, {"error": "not-found"})
            return
        try:
            if self.headers.get("Transfer-Encoding") is not None:
                raise ValueError
            if len(self.headers.get_all("Content-Length") or []) != 1:
                raise ValueError
            length = int(self.headers["Content-Length"])
            limit = (
                262144
                if self.path.endswith("/submit")
                else 65536
                if account_action
                else 8192
                if preparation_action
                else 512
            )
            if not 0 < length <= limit:
                raise ValueError
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ValueError
            body = json.loads(self.rfile.read(length))
            if submission_action:
                operation = self.path.rsplit("/", 1)[1]
                fields = (
                    {"session_id", "inputs", "scenario", "selected"}
                    if operation == "submit"
                    else {"session_id", "event_id"}
                    if operation == "results"
                    else {"session_id"}
                )
                if operation == "history" and isinstance(body, dict) and "page" in body:
                    fields.add("page")
                if not isinstance(body, dict) or set(body) != fields:
                    raise ValueError
                workflow = self.server.submissions
                if workflow is None:
                    self._json(503, {"error": "dependency-unavailable"})
                    return
                action = getattr(workflow, operation)
                args = tuple(
                    body[key]
                    for key in (
                        ("session_id", "inputs", "scenario", "selected")
                        if operation == "submit"
                        else ("session_id", "event_id")
                        if operation == "results"
                        else ("session_id",)
                    )
                )
                if operation == "history":
                    args = (body["session_id"], body.get("page", 1))
            elif preparation_action:
                if not isinstance(body, dict) or set(body) != {"session_id", "inputs"}:
                    raise ValueError
                workflow = self.server.scenarios
                action = workflow.prepare if workflow is not None else None
                args = (body["session_id"], body["inputs"])
                if action is None:
                    self._json(503, {"error": "dependency-unavailable"})
                    return
            elif account_action:
                fields = {"session_id", "query", "selected", "page", "size", "event"}
                if not isinstance(body, dict) or set(body) != fields:
                    raise ValueError
                workflow = self.server.testers
                action = workflow.search if workflow is not None else None
                args = tuple(
                    body[key]
                    for key in ("session_id", "query", "selected", "page", "size", "event")
                )
                if action is None:
                    self._json(503, {"error": "dependency-unavailable"})
                    return
            elif self.path.endswith("/start"):
                if body != {}:
                    raise ValueError
                args = ()
            else:
                if not isinstance(body, dict) or set(body) != {"session_id"}:
                    raise ValueError
                session_id = body["session_id"]
                if not isinstance(session_id, str) or str(UUID(session_id)) != session_id:
                    raise ValueError
                args = (session_id,)
        except (ValueError, TypeError, RecursionError):
            self._json(400, {"error": "invalid-request"})
            return
        self._workflow(
            action
            if account_action or preparation_action or submission_action
            else actions[self.path],
            *args,
        )

    def do_OPTIONS(self):
        self._json(405, {"error": "method-not-allowed"})
