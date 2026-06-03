"""
Простой in-process scheduler.

- Запускается фоновым daemon-потоком из main.py через start().
- Раз в CHECK_INTERVAL секунд обходит все файлы data/schedules/*.json
  и для каждого пользователя проверяет, не пора ли сработать задаче.
- Действия:
    reminder    → отправляем text через telegram_api.send_message
    news_digest → (опционально) дайджест новостей по интересам пользователя
- Логи дружелюбные: user_tag, chat_id, что сработало.
- Не спамит каждые N секунд "tick" — лог пишется только если что-то сделано.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from bot import schedules, telegram_api
from bot.logger import get_logger

logger = get_logger("scheduler")

CHECK_INTERVAL_SEC = 60  # проверка раз в минуту, как просил пользователь

_thread: threading.Thread | None = None
_stop_event = threading.Event()


def _local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def _is_due(task: dict[str, Any], now_local: dt.datetime) -> bool:
    nra = task.get("next_run_at")
    if not nra:
        return False
    try:
        nxt = dt.datetime.fromisoformat(nra).astimezone()
    except ValueError:
        return False
    # допустимое окно: задача "просрочена" — тоже срабатываем
    return nxt <= now_local


def _run_action(task: dict[str, Any]) -> bool:
    """Возвращает True, если действие отработало (даже если канал не доступен)."""
    action = task.get("type") or "reminder"
    chat_id = task.get("chat_id")
    text = task.get("text") or ""

    if not chat_id:
        logger.warning("[SCHED] task id=%s без chat_id, пропускаю", task.get("id"))
        return True  # помечаем «отработал», чтобы не зацикливаться

    if action == "reminder":
        try:
            telegram_api.send_message(int(chat_id), text or "🔔 напоминание")
            return True
        except Exception as e:
            logger.warning("[SCHED] send_message упал: %s", e.__class__.__name__)
            return False

    if action == "news_digest":
        # news_digest — используем web_search если он доступен
        try:
            from bot import web_search as ws_mod  # noqa: PLC0415
            from bot import agent  # noqa: PLC0415
            from bot import interests as interests_mod  # noqa: PLC0415
            user_tag = task.get("user_tag") or str(chat_id)
            user_interests = interests_mod.list_items(user_tag)
            topic = (", ".join(user_interests[:5])) if user_interests else "главные новости дня"
            results = ws_mod.search(f"последние новости {topic}", limit=5)
            items = results if isinstance(results, list) else []
            if not items:
                telegram_api.send_message(int(chat_id), "📭 не удалось получить новости сейчас.")
                return True
            news_text = "\n".join(
                f"- {r.get('title','')} {r.get('url','')}" for r in items[:5]
            )
            prompt = f"сделай краткую сводку новостей:\n{news_text}\nОтветь коротко."
            reply = agent.handle_message(int(chat_id), prompt, attachments=None, memory_obj=None)
            telegram_api.send_message(int(chat_id), reply)
            return True
        except Exception as e:
            logger.warning("[SCHED] news_digest error: %s", e)
            return False

    logger.warning("[SCHED] неизвестный action: %s", action)
    return True


def _tick() -> int:
    """Один цикл проверки. Возвращает количество сработавших задач."""
    fired = 0
    now_local = _local_now()
    for user_tag in schedules.all_user_tags():
        for task in schedules.list_tasks(user_tag):
            if not _is_due(task, now_local):
                continue
            tid = task.get("id")
            chat_id = task.get("chat_id")
            logger.info(
                "[SCHED FIRE] user=%s chat=%s id=%s type=%s repeat=%s",
                user_tag, chat_id, tid, task.get("type"), task.get("repeat"),
            )
            ok = _run_action(task)
            if ok:
                schedules.mark_ran(user_tag, tid)
                fired += 1
    return fired


def _loop() -> None:
    logger.info("Scheduler запущен (interval=%ss)", CHECK_INTERVAL_SEC)
    while not _stop_event.is_set():
        try:
            n = _tick()
            if n:
                logger.info("[SCHED] обработано задач: %d", n)
        except Exception as e:
            logger.exception("[SCHED] ошибка в цикле: %s", e)
        # просыпаемся с интервалом, но позволяем быстро остановиться
        _stop_event.wait(CHECK_INTERVAL_SEC)
    logger.info("Scheduler остановлен")


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_loop, name="scheduler", daemon=True)
    _thread.start()


def stop() -> None:
    _stop_event.set()
