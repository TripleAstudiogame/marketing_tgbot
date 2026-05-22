from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import Settings


def configure_logging(settings: Settings) -> None:
    settings.logs_path.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if getattr(root, "_marketing_bot_configured", False):
        return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    app_file = RotatingFileHandler(
        settings.logs_path / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    app_file.setFormatter(formatter)
    root.addHandler(app_file)

    error_file = RotatingFileHandler(
        settings.logs_path / "error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_file.setLevel(logging.ERROR)
    error_file.setFormatter(formatter)
    root.addHandler(error_file)

    root._marketing_bot_configured = True  # type: ignore[attr-defined]

