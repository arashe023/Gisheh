"""App Logging shared by Gisheh components."""

from __future__ import annotations
import logging
import os
import sys
from gettext import gettext as _
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any
from .constants import (
    APP_ID,
)


_APP_LOGGER: logging.Logger | None = None


class PrivateRotatingFileHandler(RotatingFileHandler):
    """Rotating log whose active file always remains private to the user."""

    def _open(self) -> Any:
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o600)
        except OSError:
            pass
        return stream


def application_log_file() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )
    return base / APP_ID / "gisheh.log"


def application_logger() -> logging.Logger:
    global _APP_LOGGER
    if _APP_LOGGER is not None:
        return _APP_LOGGER

    logger = logging.getLogger(APP_ID)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    try:
        destination = application_log_file()
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(destination.parent, 0o700)
        file_handler = PrivateRotatingFileHandler(
            destination,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError as error:
        logger.warning("File logging is unavailable: %s", error)
    _APP_LOGGER = logger
    return logger


def read_application_log(max_bytes: int = 250_000) -> str:
    path = application_log_file()
    try:
        with path.open("rb") as source:
            source.seek(0, os.SEEK_END)
            size = source.tell()
            source.seek(max(0, size - max_bytes))
            content = source.read()
    except FileNotFoundError:
        return _("No log entries yet.")
    except OSError as error:
        return _("Could not read the application log: {error}").format(error=error)
    text = content.decode("utf-8", errors="replace")
    if size > max_bytes:
        text = text.split("\n", 1)[-1]
    return text or _("No log entries yet.")


def clear_application_logs() -> None:
    """Close active file handlers and remove the log plus rotated copies."""
    global _APP_LOGGER
    if _APP_LOGGER is not None:
        for handler in tuple(_APP_LOGGER.handlers):
            _APP_LOGGER.removeHandler(handler)
            handler.close()
        _APP_LOGGER = None
    destination = application_log_file()
    for path in destination.parent.glob(f"{destination.name}*"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
