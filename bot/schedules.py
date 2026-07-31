"""
Расписания / напоминания / повторы.

Хранение: data/schedules/{user_tag}.json — отдельный файл на пользователя.

Структура задачи:
{
  "id": int,            # порядковый, уникален в пределах файла
  "type": "reminder" | "news_digest",  # action type (yt_digest removed)
  "repeat": "once" | "daily" | "interval" | "weekly",
  "time": "HH:MM",      # для daily/once с фиксированным временем
  "date": "YYYY-MM-DD", # для once
  "interval_seconds": int,  # для interval
  "weekdays": [0..6],   # для weekly (0=пн)
  "text": str,          # текст напоминания (для reminder)
  "chat_id": int,       # куда слать (личка или группа)
  "user_tag": str,
  "created_at": iso,
  "next_run_at": iso,   # ближайший запуск (UTC)
  "last_run_at": iso | null
}

Сценарии:
- /schedule_add HH:MM текст  → repeat=daily по умолчанию.
- агент через tools может создать once/interval/daily/weekly.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from bot.logger import get_logger
from bot.storage import (
    ensure_dir, get_user_tag, read_json, safe_tag, write_json,
)
from bot.config import DATA_DIR


logger = get_logger("schedules")

ACTION_TYPES = {"reminder", "news_digest"}
REPEAT_TYPES = {"once", "daily", "interval", "weekly"}


# --------- paths ---------

def _path(user_tag: str) -> Path:
    """
    Compute the path to the per‑user tasks file.  Each user or group
    has a folder under DATA_DIR named by the safe version of their tag.
    Inside that folder lives a JSON file called ``tasks.json``.
    """
    tag = safe_tag(user_tag)
    return DATA_DIR / tag / "tasks.json"


def _load(user_tag: str) -> dict[str, Any]:
    data = read_json(_path(user_tag), None)
    if not isinstance(data, dict):
        return {"user_tag": user_tag, "next_id": 1, "tasks": []}
    data.setdefault("user_tag", user_tag)
    data.setdefault("next_id", 1)
    data.setdefault("tasks", [])
    return data


def _save(user_tag: str, data: dict[str, Any]) -> None:
    # Ensure the parent directory exists (DATA_DIR/<tag>)
    path = _path(user_tag)
    ensure_dir(path.parent)
    write_json(path, data)


# --------- time ---------

def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _parse_hhmm(s: str) -> tuple[int, int] | None:
    s = (s or "").strip()
    if not s or ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        hi, mi = int(h), int(m)
        if 0 <= hi < 24 and 0 <= mi < 60:
            return hi, mi
    except ValueError:
        return None
    return None


def _next_run_for(task: dict[str, Any], now_local: dt.datetime) -> dt.datetime | None:
    """Считаем ближайший запуск задачи в локальной таймзоне."""
    repeat = task.get("repeat")
    if repeat == "once":
        # date + time
        time_s = task.get("time")
        date_s = task.get("date")
        hm = _parse_hhmm(time_s) if time_s else None
        if hm and date_s:
            try:
                d = dt.date.fromisoformat(date_s)
                local = dt.datetime.combine(d, dt.time(hm[0], hm[1])).astimezone()
                return local
            except ValueError:
                return None
        # iso run_at явный
        run_at = task.get("run_at")
        if run_at:
            try:
                return dt.datetime.fromisoformat(run_at).astimezone()
            except ValueError:
                return None
        return None

    if repeat == "daily":
        hm = _parse_hhmm(task.get("time", ""))
        if not hm:
            return None
        candidate = now_local.replace(hour=hm[0], minute=hm[1], second=0, microsecond=0)
        if candidate <= now_local:
            candidate = candidate + dt.timedelta(days=1)
        return candidate

    if repeat == "interval":
        sec = int(task.get("interval_seconds") or 0)
        if sec <= 0:
            return None
        last = task.get("last_run_at")
        if last:
            try:
                base = dt.datetime.fromisoformat(last).astimezone()
            except ValueError:
                base = now_local
        else:
            base = now_local
        nxt = base + dt.timedelta(seconds=sec)
        if nxt <= now_local:
            nxt = now_local + dt.timedelta(seconds=sec)
        return nxt

    if repeat == "weekly":
        weekdays = task.get("weekdays") or []
        hm = _parse_hhmm(task.get("time", ""))
        if not hm or not weekdays:
            return None
        for delta in range(0, 8):
            cand = (now_local + dt.timedelta(days=delta)).replace(
                hour=hm[0], minute=hm[1], second=0, microsecond=0,
            )
            if cand.weekday() in weekdays and cand > now_local:
                return cand
        return None

    return None


# --------- API ---------

def add_task(
    user_tag: str,
    chat_id: int,
    text: str,
    repeat: str = "daily",
    time_s: str | None = None,
    date_s: str | None = None,
    interval_seconds: int | None = None,
    weekdays: list[int] | None = None,
    action_type: str = "reminder",
    run_at_iso: str | None = None,
) -> dict[str, Any]:
    """Создать задачу. Возвращает добавленную задачу."""
    if action_type not in ACTION_TYPES:
        raise ValueError(f"unknown action_type: {action_type}")
    if repeat not in REPEAT_TYPES:
        raise ValueError(f"unknown repeat: {repeat}")

    data = _load(user_tag)
    task: dict[str, Any] = {
        "id": data["next_id"],
        "type": action_type,
        "repeat": repeat,
        "text": (text or "").strip(),
        "chat_id": int(chat_id),
        "user_tag": user_tag,
        "created_at": _now().isoformat(),
        "last_run_at": None,
    }
    if time_s:
        task["time"] = time_s
    if date_s:
        task["date"] = date_s
    if interval_seconds:
        task["interval_seconds"] = int(interval_seconds)
    if weekdays:
        task["weekdays"] = sorted({int(w) for w in weekdays if 0 <= int(w) <= 6})
    if run_at_iso:
        task["run_at"] = run_at_iso

    nxt = _next_run_for(task, _local_now())
    task["next_run_at"] = nxt.isoformat() if nxt else None

    data["tasks"].append(task)
    data["next_id"] = data["next_id"] + 1
    _save(user_tag, data)
    return task


def list_tasks(user_tag: str) -> list[dict[str, Any]]:
    return list(_load(user_tag).get("tasks", []))


def remove_task(user_tag: str, task_id: int) -> bool:
    data = _load(user_tag)
    before = len(data["tasks"])
    data["tasks"] = [t for t in data["tasks"] if int(t.get("id", 0)) != int(task_id)]
    changed = len(data["tasks"]) != before
    if changed:
        _save(user_tag, data)
    return changed


def edit_task(user_tag: str, task_id: int, **updates) -> dict[str, Any] | None:
    """
    Редактирует существующее напоминание.
    Поддерживает обновление: text, time, repeat, weekdays, interval_seconds и т.д.
    """
    data = _load(user_tag)
    for task in data.get("tasks", []):
        if int(task.get("id", 0)) == int(task_id):
            for key, value in updates.items():
                if value is not None:
                    if key == "weekdays" and value:
                        task["weekdays"] = sorted({int(w) for w in value if 0 <= int(w) <= 6})
                    elif key == "time" and value:
                        task["time"] = str(value)
                    else:
                        task[key] = value

            # Пересчитываем next_run_at если изменилось время
            if any(k in updates for k in ("time", "date", "weekdays", "repeat", "interval_seconds")):
                task["next_run_at"] = _compute_next_run(task)

            _save(user_tag, data)
            return task
    return None


def remove_by_index(user_tag: str, index_1based: int) -> dict[str, Any] | None:
    """Удалить по порядковому номеру в /schedule_list (1-based)."""
    data = _load(user_tag)
    tasks = data.get("tasks") or []
    if index_1based < 1 or index_1based > len(tasks):
        return None
    removed = tasks.pop(index_1based - 1)
    data["tasks"] = tasks
    _save(user_tag, data)
    return removed


def mark_ran(user_tag: str, task_id: int) -> None:
    data = _load(user_tag)
    now_local = _local_now()
    new_tasks: list[dict[str, Any]] = []
    for t in data.get("tasks", []):
        if int(t.get("id", 0)) != int(task_id):
            new_tasks.append(t)
            continue
        t["last_run_at"] = _now().isoformat()
        if t.get("repeat") == "once":
            # одноразовое — удаляем
            continue
        nxt = _next_run_for(t, now_local)
        t["next_run_at"] = nxt.isoformat() if nxt else None
        new_tasks.append(t)
    data["tasks"] = new_tasks
    _save(user_tag, data)


def all_user_tags() -> list[str]:
    """
    Список user_tag из имён директорий в DATA_DIR содержащих tasks.json.
    Это заменяет старое поведение, основанное на data/schedules.
    """
    tags: list[str] = []
    for p in DATA_DIR.iterdir():
        if not p.is_dir():
            continue
        # skip internal directories
        if p.name in {"memory", "files", "schedules", "interests"}:
            continue
        if (p / "tasks.json").exists():
            tags.append(p.name)
    return tags


def format_task_short(t: dict[str, Any]) -> str:
    """Короткое описание задачи для /schedule_list."""
    repeat = t.get("repeat", "?")
    text = t.get("text") or "(без текста)"
    if repeat == "daily":
        return f"ежедневно в {t.get('time', '?')} — {text}"
    if repeat == "once":
        when = t.get("date") or ""
        if t.get("time"):
            when = (when + " " + t["time"]).strip()
        if not when and t.get("run_at"):
            when = t["run_at"]
        return f"однократно {when} — {text}"
    if repeat == "interval":
        sec = int(t.get("interval_seconds") or 0)
        if sec >= 3600 and sec % 3600 == 0:
            human = f"каждые {sec // 3600} ч"
        elif sec >= 60 and sec % 60 == 0:
            human = f"каждые {sec // 60} мин"
        else:
            human = f"каждые {sec} сек"
        return f"{human} — {text}"
    if repeat == "weekly":
        names = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
        days = ",".join(names[i] for i in (t.get("weekdays") or []) if 0 <= i < 7)
        return f"еженедельно {days} {t.get('time', '?')} — {text}"
    return f"{repeat} — {text}"
