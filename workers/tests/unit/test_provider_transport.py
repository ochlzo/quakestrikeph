"""Public provider boundaries against credential-free loopback HTTP."""

import json
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from test_iprog_delivery import Response, submission

from quakestrike.application.alerts import SmsSupportUnavailable
from quakestrike.infrastructure.email.brevo import BrevoEmailProvider
from quakestrike.infrastructure.sms.iprog import IprogAlertProvider, IprogSmsSupport


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="Production deadline requires Linux.")
@pytest.mark.parametrize(
    "kind,mode",
    [
        ("poll", "headers"),
        ("submit", "body"),
        ("support", "body"),
        ("email", "headers"),
        *((kind, "oversize") for kind in ("poll", "submit", "support", "email")),
    ],
)
def test_provider_deadline_includes_headers_and_dripping_body(kind, mode):
    calls, responses, closed = [], [], []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            body = json.dumps(
                {"status": 200, "message_status": "completed", "message_id": "known"}
                if kind in {"poll", "submit"}
                else {"status": "success", "data": {"network": "Globe/TM", "is_smart_tnt": False}}
                if kind == "support"
                else {"messageId": "fixture@brevo"}
            )
            if mode == "oversize":
                body = body[:-1] + ', "private": "' + "x" * 16384 + '"}'
            body = body.encode()
            try:
                status = 201 if kind == "email" else 200
                if mode == "headers":
                    self.wfile.write(f"HTTP/1.1 {status} OK\r\nX-Drip: ".encode())
                    self.wfile.flush()
                    for _ in range(26):
                        time.sleep(0.5)
                        self.wfile.write(b"x")
                        self.wfile.flush()
                    self.wfile.write(f"\r\nContent-Length: {len(body)}\r\n\r\n".encode())
                    self.wfile.write(body)
                elif mode == "body":
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    for byte in body[:26]:
                        time.sleep(0.5)
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                    self.wfile.write(body[26:])
                else:
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

        do_POST = do_GET

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def request(url, **options):
        method = "GET" if kind == "poll" else "POST"
        response = requests.request(
            method, f"http://127.0.0.1:{server.server_port}/fixture", **options
        )
        responses.append(response)
        original_close = response.close

        def close():
            closed.append(response)
            original_close()

        response.close = close
        return response

    try:
        previous = signal.getsignal(signal.SIGALRM)
        started = time.monotonic()
        if kind == "poll":
            result = IprogAlertProvider("TEST_ONLY", get=request).poll("known")
        elif kind == "submit":
            result = IprogAlertProvider("TEST_ONLY", post=request).submit(submission())
        elif kind == "email":
            result = BrevoEmailProvider(
                "TEST_ONLY", "alerts@example.invalid", "Fixture", request=request
            ).submit(submission())
        else:
            with pytest.raises(SmsSupportUnavailable) as failure:
                IprogSmsSupport("TEST_ONLY", request=request).supported("+639171234567")
            result = failure.value
        elapsed = time.monotonic() - started
        if kind != "support":
            assert result.status == "unknown"
            assert result.error_code == (
                "provider_invalid_response"
                if mode == "oversize"
                else "provider_transport_uncertain"
            )
        if mode == "oversize" and kind in {"submit", "email"}:
            assert result.evidence["http_status"] == (201 if kind == "email" else 200)
            assert result.reference is None
            assert "private" not in repr(result)
        assert closed == responses
        assert elapsed < 12.8
        assert signal.getsignal(signal.SIGALRM) is previous
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert len(calls) == 1
        assert "TEST_ONLY" not in repr(result)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="Production deadline requires Linux.")
def test_provider_restores_signal_handler_and_preserves_another_owners_timer():
    previous = signal.getsignal(signal.SIGALRM)
    calls, closed = [], []

    def owner(signum, frame):
        pytest.fail("Provider must not invoke another owner's alarm.")

    def get(*args, **options):
        calls.append(True)
        response = Response({"status": 200, "message_status": "completed"})
        response.close = lambda: closed.append(True)
        return response

    try:
        signal.signal(signal.SIGALRM, owner)
        provider = IprogAlertProvider("TEST_ONLY", get=get)
        assert provider.poll("known").status == "delivered"
        assert signal.getsignal(signal.SIGALRM) is owner
        assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)
        assert closed == [True]
        signal.setitimer(signal.ITIMER_REAL, 30)
        assert provider.poll("known").status == "unknown"
        assert 0 < signal.getitimer(signal.ITIMER_REAL)[0] <= 30
        assert signal.getsignal(signal.SIGALRM) is owner
        assert calls == [True]
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_default_provider_transport_fails_closed_outside_supported_main_thread(monkeypatch):
    calls, results = [], []

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("Unsupported deadline execution must not start transport.")

    monkeypatch.setattr(requests.Session, "request", forbidden)
    thread = threading.Thread(
        target=lambda: results.append(IprogAlertProvider("TEST_ONLY").poll("known"))
    )
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert results[0].status == "unknown"
    assert results[0].error_code == "provider_transport_uncertain"
    assert calls == []
