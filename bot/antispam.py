"""
Простой антиспам и per-chat processing flag.
- cooldown на (chat_id, user_id): N секунд между запросами одного юзера.
- max requests per minute на чат.
- check_processing/start/stop — флаг "идёт обработка" для очереди.
Только in-memory, без redis.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from bot.config import (
    GROUP_MAX_REQUESTS_PER_MINUTE,
    GROUP_USER_COOLDOWN_SECONDS,
)


_lock = threading.Lock()
_last_user_ts: dict[tuple[int | str, int | str], float] = {}
_chat_window: dict[int | str, deque] = {}
_processing: set[int | str] = set()


def check_and_register(chat_id: int | str, user_id: int | str) -> tuple[bool, str]:
    """
    Возвращает (allowed, reason).
    reason: "ok" | "cooldown" | "rate_limit"
    Если allowed=True — регистрирует запрос.
    """
    now = time.monotonic()
    with _lock:
        # cooldown
        key = (chat_id, user_id)
        last = _last_user_ts.get(key, 0.0)
        if GROUP_USER_COOLDOWN_SECONDS > 0 and now - last < GROUP_USER_COOLDOWN_SECONDS:
            return False, "cooldown"
        # rate limit on chat
        win = _chat_window.setdefault(chat_id, deque())
        cutoff = now - 60.0
        while win and win[0] < cutoff:
            win.popleft()
        if GROUP_MAX_REQUESTS_PER_MINUTE > 0 and len(win) >= GROUP_MAX_REQUESTS_PER_MINUTE:
            return False, "rate_limit"
        # принимаем
        _last_user_ts[key] = now
        win.append(now)
        return True, "ok"


# --- per-chat processing flag (минимальная "очередь") ---

def is_processing(chat_id: int | str) -> bool:
    with _lock:
        return chat_id in _processing


def start_processing(chat_id: int | str) -> bool:
    """True если удалось зарезервировать слот (не было занято)."""
    with _lock:
        if chat_id in _processing:
            return False
        _processing.add(chat_id)
        return True


def stop_processing(chat_id: int | str) -> None:
    with _lock:
        _processing.discard(chat_id)
