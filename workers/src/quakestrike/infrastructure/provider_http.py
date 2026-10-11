"""Synchronous provider deadlines for the Linux main/prefork worker runtime."""

import json
import signal
from contextlib import contextmanager
from threading import current_thread, main_thread
from time import monotonic

import requests

PROVIDER_TIMEOUT_SECONDS = 12
PROVIDER_RESPONSE_BYTES = 16384


@contextmanager
def provider_response(request, url, *, clock=monotonic, **options):
    deadline = clock() + PROVIDER_TIMEOUT_SECONDS
    alarm = hasattr(signal, "setitimer") and current_thread() is main_thread()
    if not alarm and request in (requests.get, requests.post):
        raise requests.Timeout("Provider deadline unavailable.")
    previous = None
    if alarm:
        # Never replace another owner's active timer.
        if signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0):
            raise requests.Timeout("Provider deadline unavailable.")
        previous = signal.getsignal(signal.SIGALRM)

        def expired(signum, frame):
            raise requests.Timeout("Provider deadline exceeded.")

        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, PROVIDER_TIMEOUT_SECONDS)
    response = None
    try:
        response = request(url, timeout=(3, 8), allow_redirects=False, stream=True, **options)
        if clock() >= deadline:
            raise requests.Timeout("Provider deadline exceeded.")
        yield response, deadline
    finally:
        if alarm:
            signal.setitimer(signal.ITIMER_REAL, 0)
        try:
            if response is not None:
                response.close()
        finally:
            if alarm:
                signal.signal(signal.SIGALRM, previous)


def provider_json(response, deadline, *, clock=monotonic):
    content_length = response.headers.get("Content-Length", "")
    if content_length.isascii() and content_length.isdigit():
        if len(content_length) > 10 or int(content_length) > PROVIDER_RESPONSE_BYTES:
            raise ValueError("Provider response exceeds limit.")
    body = bytearray()
    for chunk in response.iter_content(1024):
        if clock() >= deadline:
            raise requests.Timeout("Provider deadline exceeded.")
        body.extend(chunk)
        if len(body) > PROVIDER_RESPONSE_BYTES:
            raise ValueError("Provider response exceeds limit.")
    if clock() >= deadline:
        raise requests.Timeout("Provider deadline exceeded.")
    return json.loads(body)
