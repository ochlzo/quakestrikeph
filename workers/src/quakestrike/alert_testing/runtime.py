import argparse
import logging
import os
from pathlib import Path
from threading import Event, Thread

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from quakestrike.alert_testing.application.sessions import Sessions
from quakestrike.alert_testing.domain.sessions import SessionConflict
from quakestrike.alert_testing.infrastructure.redis import RedisSessionStore
from quakestrike.alert_testing.interface.http import PrivateServer
from quakestrike.infrastructure.logging.json_logging import configure_logging, log_event


def main() -> None:
    parser = argparse.ArgumentParser(description="Loopback-only private alert-testing controls")
    parser.add_argument("--port", type=int, default=4341)
    parser.add_argument("--origin", default=os.environ.get("ALERT_TEST_ORIGIN"))
    parser.add_argument(
        "--static-directory",
        type=Path,
        default=Path("apps/quakestrikeph-alert-testing/dist"),
    )
    args = parser.parse_args()
    redis_url = os.environ.get("ALERT_TEST_REDIS_URL")
    if not redis_url:
        parser.error(
            "Set ALERT_TEST_REDIS_URL explicitly; no runtime Redis is selected by default."
        )
    if not (args.static_directory / "index.html").is_file():
        parser.error("Build the private Astro application before starting the control server.")
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        max_connections=20,
        retry=Retry(NoBackoff(), 0),
    )
    sessions = Sessions(RedisSessionStore(client))
    server = PrivateServer(sessions, args.static_directory, args.port, args.origin)
    logger = configure_logging("alert-testing")
    stopped = Event()

    def maintain() -> None:
        while not stopped.wait(5):
            try:
                sessions.maintain()
            except RedisError:
                log_event(
                    logger,
                    logging.WARNING,
                    "Alert-testing maintenance: Redis unavailable",
                    event_code="alert_testing_dependency_unavailable",
                    context={"operation": "session_maintenance", "reason": "redis_unavailable"},
                )
            except SessionConflict:
                pass

    maintenance = Thread(target=maintain, daemon=True)
    maintenance.start()
    log_event(
        logger,
        logging.INFO,
        f"Private alert-testing controls bound to 127.0.0.1:{server.server_port}",
        event_code="alert_testing_started",
        context={"operation": "private_http", "status": "listening"},
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        server.server_close()
        maintenance.join(timeout=3)
        client.close()


if __name__ == "__main__":
    main()
