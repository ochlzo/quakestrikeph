"""Read-only container probes; no session creation or provider calls."""

import json
import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

CONSUMER_MARKER = Path(tempfile.gettempdir()) / "quakestrike-alert-test-consumer-health"


def check_control():
    authority = urlsplit(os.environ["ALERT_TEST_ORIGIN"]).netloc
    request = Request("http://127.0.0.1:4342/api/test/session", headers={"Host": authority})
    with urlopen(request, timeout=3) as response:
        assert response.status == 200
        assert json.load(response)["status"] in {
            "inactive",
            "active",
            "ending",
            "cleanup-failure",
            "ended",
            "expired",
        }


def check_consumer():
    os.kill(int(CONSUMER_MARKER.read_text()), 0)
    with Redis.from_url(
        os.environ["ALERT_TEST_REDIS_URL"],
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
    ) as client:
        assert client.ping()


def mark_consumer():
    CONSUMER_MARKER.write_text(str(os.getpid()))


if __name__ == "__main__":
    try:
        {"control": check_control, "consumer": check_consumer}[sys.argv[1]]()
    except Exception:
        raise SystemExit("Alert-testing health unavailable.") from None
