"""Shared pooled HTTP transport for Gisheh image downloads."""

from __future__ import annotations

import atexit
import threading
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

from ..version import APP_VERSION

USER_AGENT = f"Gisheh/{APP_VERSION}"
DEFAULT_RETRY_DELAYS = (0.0, 0.5, 2.0)
_CLIENT: httpx.Client | None = None
_CLIENT_LOCK = threading.Lock()


def get_client() -> httpx.Client:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(
                    connect=4.0,
                    read=8.0,
                    write=5.0,
                    pool=4.0,
                ),
                limits=httpx.Limits(
                    max_connections=10,
                    max_keepalive_connections=8,
                    keepalive_expiry=30.0,
                ),
                headers={"User-Agent": USER_AGENT},
            )
        return _CLIENT


def close_client() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        client = _CLIENT
        _CLIENT = None
    if client is not None:
        client.close()


atexit.register(close_client)


def _is_retryable_status(status_code: int) -> bool:
    return status_code in (408, 429) or 500 <= status_code < 600


def download(
    url: str,
    destination: Path,
    *,
    client: httpx.Client | None = None,
    retry_delays: Iterable[float] = DEFAULT_RETRY_DELAYS,
    max_bytes: int | None = None,
) -> bool:
    delays = tuple(retry_delays)
    http = client or get_client()
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            response = http.get(url)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt + 1 < len(delays):
                continue
            return False
        if 200 <= response.status_code < 300:
            content = response.content
            if not content or (max_bytes is not None and len(content) > max_bytes):
                return False
            temporary = destination.with_name(
                f".{destination.name}.{threading.get_ident()}.tmp"
            )
            try:
                temporary.write_bytes(content)
                temporary.replace(destination)
            except OSError:
                try:
                    temporary.unlink()
                except OSError:
                    pass
                return False
            return True
        if not _is_retryable_status(response.status_code):
            return False
        if attempt + 1 >= len(delays):
            return False
    return False
