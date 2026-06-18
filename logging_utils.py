from __future__ import annotations

import logging
from typing import Optional


def setup_logging(debug: bool = False) -> None:
    """
    Configure root logger with a simple, structured console format.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name or "sonar_share")

