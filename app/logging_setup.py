from __future__ import annotations

import logging

from uvicorn.logging import AccessFormatter, DefaultFormatter


LOG_TIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"
DEFAULT_LOG_FORMAT = "%(asctime)s %(levelprefix)s %(message)s"
ACCESS_LOG_FORMAT = (
    '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
)


def configure_uvicorn_timestamps() -> None:
    """Add timestamps to Uvicorn's default and access handlers."""
    _configure_logger(logging.getLogger("uvicorn"), DefaultFormatter, DEFAULT_LOG_FORMAT)
    _configure_logger(
        logging.getLogger("uvicorn.access"),
        AccessFormatter,
        ACCESS_LOG_FORMAT,
    )


def _configure_logger(
    logger: logging.Logger,
    formatter_type: type[logging.Formatter],
    fmt: str,
) -> None:
    for handler in logger.handlers:
        current = handler.formatter
        use_colors = getattr(current, "use_colors", None)
        handler.setFormatter(
            formatter_type(fmt=fmt, datefmt=LOG_TIME_FORMAT, use_colors=use_colors)
        )
