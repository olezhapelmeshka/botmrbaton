"""
Интересы пользователя.

Хранение: data/interests/{user_tag}.json
Формат: {"user_tag": str, "items": [str, ...]}.

Используется для будущих новостных/YouTube дайджестов. Сейчас — только CRUD.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bot.logger import get_logger
from bot.storage import (
    INTERESTS_DIR, ensure_dir, read_json, safe_tag, write_json,
)


logger = get_logger("interests")


def _path(user_tag: str) -> Path:
    return INTERESTS_DIR / f"{safe_tag(user_tag)}.json"


def _load(user_tag: str) -> dict[str, Any]:
    data = read_json(_path(user_tag), None)
    if not isinstance(data, dict):
        return {"user_tag": user_tag, "items": []}
    data.setdefault("user_tag", user_tag)
    data.setdefault("items", [])
    return data


def _save(user_tag: str, data: dict[str, Any]) -> None:
    ensure_dir(INTERESTS_DIR)
    write_json(_path(user_tag), data)


def add(user_tag: str, text: str) -> bool:
    text = (text or "").strip()
    if not text:
        return False
    data = _load(user_tag)
    if text in data["items"]:
        return False
    data["items"].append(text)
    _save(user_tag, data)
    return True


def list_items(user_tag: str) -> list[str]:
    return list(_load(user_tag).get("items", []))


def remove_by_index(user_tag: str, index_1based: int) -> str | None:
    data = _load(user_tag)
    items = data.get("items") or []
    if index_1based < 1 or index_1based > len(items):
        return None
    removed = items.pop(index_1based - 1)
    data["items"] = items
    _save(user_tag, data)
    return removed
