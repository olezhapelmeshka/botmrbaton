"""
Маленькие helpers поверх bot.utils.load_json/save_json.

- get_user_tag(user_or_msg) — username без @, либо user_id (str).
- ensure_dir(path) — создать директорию.
- read_json/write_json — обёртки с понятными логами и fallback.

Не вводим базы данных, не дублируем utils — только тонкая прослойка
для расписаний и интересов, чтобы было удобно адресоваться по user_tag.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bot.config import DATA_DIR
from bot.logger import get_logger
from bot.utils import load_json, save_json


logger = get_logger("storage")

SCHEDULES_DIR: Path = DATA_DIR / "schedules"
INTERESTS_DIR: Path = DATA_DIR / "interests"


_SAFE_TAG = re.compile(r"[^A-Za-z0-9_\-\.]")


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_tag(raw: str) -> str:
    """Срезаем потенциально проблемные символы для имени файла."""
    return _SAFE_TAG.sub("_", raw or "").strip("._") or "user"


def get_user_tag(user: dict | None, fallback_id: int | str | None = None) -> str:
    """
    user_tag = username без @, иначе str(user_id).
    Принимает либо message['from'], либо просто dict с username/id.
    """
    user = user or {}
    username = (user.get("username") or "").strip().lstrip("@")
    if username:
        return safe_tag(username)
    uid = user.get("id") or fallback_id
    if uid is None:
        return "anonymous"
    return safe_tag(str(uid))


def read_json(path: Path, default: Any) -> Any:
    try:
        return load_json(path, default)
    except Exception as e:  # на всякий случай — load_json и так не падает
        logger.warning("read_json fallback %s: %s", path.name, e.__class__.__name__)
        return default


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    save_json(path, data)
