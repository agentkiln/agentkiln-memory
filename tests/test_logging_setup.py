import io
import logging
import re

from uvicorn.logging import AccessFormatter, DefaultFormatter

from app.logging_setup import ACCESS_LOG_FORMAT, DEFAULT_LOG_FORMAT, _configure_logger


TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def test_default_logger_formatter_includes_timestamp() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("test.agentkiln.default")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(DefaultFormatter(fmt=DEFAULT_LOG_FORMAT, use_colors=False))
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    _configure_logger(logger, DefaultFormatter, DEFAULT_LOG_FORMAT)
    logger.info("hello")

    assert TIMESTAMP_PATTERN.match(stream.getvalue())


def test_access_logger_formatter_includes_timestamp() -> None:
    stream = io.StringIO()
    logger = logging.getLogger("test.agentkiln.access")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter(fmt=ACCESS_LOG_FORMAT, use_colors=False))
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    _configure_logger(logger, AccessFormatter, ACCESS_LOG_FORMAT)
    logger.info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:1234",
        "GET",
        "/health",
        "1.1",
        200,
    )

    assert TIMESTAMP_PATTERN.match(stream.getvalue())
