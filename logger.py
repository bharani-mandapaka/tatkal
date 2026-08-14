import logging
import sys

import structlog


def force_utf8_console() -> None:
    """Windows' default console codepage (cp1252) can't encode the box-drawing
    / checkmark characters this CLI prints, or non-ASCII text IRCTC returns —
    crashing on the very first command a new user runs. Force UTF-8 on
    stdout/stderr regardless of what codepage the terminal negotiated."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and stream.encoding and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")


def setup_logging(log_file: str = "") -> None:
    force_utf8_console()
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%H:%M:%S"),
        structlog.dev.ConsoleRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(level=logging.INFO, handlers=handlers)


def get_logger():
    return structlog.get_logger()
