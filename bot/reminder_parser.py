"""
LLM-powered reminder parser.

Allows users to create reminders in natural Russian:
- "через 25 минут напомни купить хлеб"
- "в 11:28 позвони маме"
- "каждый понедельник в 9:00 утренняя зарядка"
- Full schedule pasting.

Uses the fast model (GLM) to parse into structured tasks.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from bot import openai_client
from bot.logger import get_logger

logger = get_logger("reminder_parser")

PARSER_SYSTEM_PROMPT = """Ты — точный парсер напоминаний на русском языке.

Твоя задача — извлечь из текста пользователя одно или несколько напоминаний и вернуть их в строгом JSON.

Поддерживаемые типы repeat:
- "once" — один раз (нужен date + time или run_at_iso)
- "daily" — каждый день
- "weekly" — по дням недели (weekdays: 0=пн, 1=вт, ..., 6=вс)
- "interval" — периодически через N секунд

Формат ответа — **только** чистый JSON массив:

[
  {
    "text": "текст напоминания (обязательно)",
    "repeat": "daily" | "once" | "weekly" | "interval",
    "time": "HH:MM",
    "date": "YYYY-MM-DD",           // только для once
    "weekdays": [0,2,4],            // для weekly (0=пн ... 6=вс)
    "interval_seconds": 3600,       // для interval
    "run_at_iso": "2026-05-28T14:30:00+03:00"  // для once
  }
]

Правила парсинга (очень важно):
- "каждую среду", "по средам", "еженедельно по средам" → repeat="weekly", weekdays=[2]
- "каждый понедельник и пятницу", "по пн и пт" → repeat="weekly", weekdays=[0,4]
- "по будням" → weekdays=[0,1,2,3,4]
- "каждые выходные" → weekdays=[5,6]
- "через 40 минут", "через 2 часа 15 минут" → repeat="once" + посчитай run_at_iso от текущего времени
- Всегда возвращай время в формате HH:MM (24 часа)
- Если дано полное расписание — разбей на отдельные объекты
- Если не уверен — лучше пропусти напоминание, чем придумай
"""

def parse_reminders(text: str, now: datetime) -> list[dict[str, Any]]:
    """
    Parse natural language into list of reminder task dicts.
    Uses the fast model.
    """
    current_time_str = now.isoformat()

    user_prompt = f"""Текущее время: {current_time_str}

Текст пользователя:
{text}

Верни только JSON массив напоминаний."""

    try:
        resp = openai_client.create_message(
            messages=[{"role": "user", "content": user_prompt}],
            system=PARSER_SYSTEM_PROMPT,
            model="glm-4.5-flash",   # fast and cheap
            max_tokens=800,
        )

        content = ""
        if resp and resp.content:
            for block in resp.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    content += block.get("text", "")
                elif hasattr(block, "text"):
                    content += getattr(block, "text", "")

        content = content.strip()

        # Try to extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)

        if isinstance(data, dict):
            data = [data]

        valid_tasks = []
        for item in data:
            if not isinstance(item, dict) or not item.get("text"):
                continue

            # Пост-обработка: улучшаем поддержку "каждую среду", "по пн и пт" и т.д.
            text_lower = (item.get("text") or "").lower() + " " + str(item)

            if "каждую" in text_lower or "по " in text_lower or "еженедельно" in text_lower:
                if not item.get("weekdays"):
                    item["weekdays"] = _extract_weekdays_from_text(text_lower)
                if item.get("weekdays"):
                    item["repeat"] = "weekly"

            # Нормализуем weekdays
            if item.get("repeat") == "weekly" and item.get("weekdays"):
                item["weekdays"] = _normalize_weekdays(item["weekdays"])

            valid_tasks.append(item)

        return valid_tasks

    except Exception as e:
        logger.warning("Failed to parse reminders with LLM: %s", e)
        return []


# --- Вспомогательные функции ---

_WEEKDAY_MAP = {
    "пн": 0, "понедельник": 0, "понедельникам": 0,
    "вт": 1, "вторник": 1, "вторникам": 1,
    "ср": 2, "среда": 2, "среду": 2, "средам": 2,
    "чт": 3, "четверг": 3, "четвергам": 3,
    "пт": 4, "пятница": 4, "пятницу": 4, "пятницам": 4,
    "сб": 5, "суббота": 5, "субботу": 5,
    "вс": 6, "воскресенье": 6, "воскресеньям": 6,
    "будни": [0,1,2,3,4],
    "выходные": [5,6],
}

def _normalize_weekdays(weekdays: list | str) -> list[int]:
    """Приводит разные форматы к списку [0..6]"""
    if isinstance(weekdays, (int, str)):
        weekdays = [weekdays]

    result = set()
    for w in weekdays:
        if isinstance(w, int) and 0 <= w <= 6:
            result.add(w)
            continue
        if isinstance(w, str):
            w = w.lower().strip()
            if w in _WEEKDAY_MAP:
                val = _WEEKDAY_MAP[w]
                if isinstance(val, list):
                    result.update(val)
                else:
                    result.add(val)
    return sorted(result) if result else [0]  # fallback на понедельник


def _extract_weekdays_from_text(text: str) -> list[int]:
    """Пытается вытащить дни недели из текста ('каждую среду', 'по пн и пт' и т.д.)"""
    found = set()
    text = text.lower()

    for word, value in _WEEKDAY_MAP.items():
        if word in text:
            if isinstance(value, list):
                found.update(value)
            else:
                found.add(value)

    # Дополнительные эвристики
    if "будня" in text:
        found.update([0,1,2,3,4])
    if "выходн" in text:
        found.update([5,6])

    return sorted(found) if found else []

