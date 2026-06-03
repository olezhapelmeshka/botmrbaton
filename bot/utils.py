"""
Мелкие утилиты: атомарное сохранение JSON и нарезка длинных
сообщений Telegram под лимит 4096.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


TELEGRAM_LIMIT = 4096


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def split_for_telegram(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Аккуратная нарезка длинного текста под лимит Telegram."""
    if not text:
        return [""]
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return parts


def clean_model_output(text: str) -> str:
    """
    Очищает ответ модели от артефактов reasoning-моделей (GLM, DeepSeek-R1 и т.п.).

    Удаляет:
    - Полные блоки <think>...</think>
    - Одиночные теги </think> и <think>
    - Иногда модель оставляет мусор после закрывающего тега — мы берём только то, что после последнего </think>.
    """
    if not text:
        return ""

    import re

    # 1. Если есть закрывающий тег — берём всё, что после последнего </think>
    #    (многие reasoning-модели кладут финальный ответ именно после него)
    if "</think>" in text.lower():
        parts = re.split(r"</think>", text, flags=re.IGNORECASE)
        text = parts[-1].strip()

    # 2. Удаляем любые оставшиеся полные блоки <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 3. Убираем одиночные открывающие/закрывающие теги
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE)

    # 4. Чистим лишние пустые строки, которые могли остаться
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text


# === Vision denial sanitizer ===
# Никогда не даём пользователю увидеть фразы про "нет визуального доступа".
# Заменяем на короткие мемные реакции в стиле Мистера Батона (семейный чат).

_VISION_DENIAL_PHRASES: list[str] = [
    "нет доступа к визуальному",
    "не вижу никаких изображений",
    "я картинки не вижу",
    "я не вижу никаких",
    "слепой кот",
    "без визуального",
    "нет визуального восприятия",
    "не могу видеть изображ",
    "не имею доступа к картин",
    "visual perception",
    "can't see the image",
    "no access to visual",
    "i don't see any images",
    "я как слепой",
    "не вижу изображение",
    "не вижу картинку",
    "опиши сам",
    "пришли текстовое описание",
]

_FUN_FALLBACKS: list[str] = [
    "пиздец какая фотка ахах",
    "ну ты глянь на эту хуйню",
    "ахах ну и ну",
    "это было сильно",
    "согласен, мем на миллион",
    "погляди на эту ебаную красоту",
    "ладно, это уже перебор",
    "ну ты закинул",
    "епт, ахах",
    "мем века просто",
]


def sanitize_vision_denial(text: str) -> str:
    """Если в ответе есть отмазки про отсутствие зрения — заменяем на весёлый фоллбэк."""
    if not text or not text.strip():
        return text
    low = text.lower()
    for phrase in _VISION_DENIAL_PHRASES:
        if phrase in low:
            import random
            return random.choice(_FUN_FALLBACKS)
    return text
