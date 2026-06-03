"""
Логирование.

Никаких API-ключей, токенов или содержимого system prompt в логи не пишем.
Используется простой консольный stdout-логгер.
"""

from __future__ import annotations

import logging
import sys

from bot.config import LOG_LEVEL


_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FMT, _DATEFMT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # урезаем шумные библиотеки
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(name)
