"""Logging helpers for the Kila SIFEN platform."""

import logging


def configure_logging(level: str) -> None:
    """Configure application logging once per process."""

    root_logger = logging.getLogger()
    normalized_level = getattr(logging, level.upper(), logging.INFO)

    if root_logger.handlers:
        root_logger.setLevel(normalized_level)
        return

    logging.basicConfig(
        level=normalized_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
