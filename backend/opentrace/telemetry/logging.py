"""Centralized logging for the application shell."""

import logging

from opentrace.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Configure a concise, source-safe process logger."""
    level = getattr(logging, settings.log_level)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    root_logger.setLevel(level)
    logging.getLogger("opentrace").setLevel(level)

