"""
Группа: фильтр входящих сообщений ДО agent.py.

should_process_message решает, должен ли бот вообще обрабатывать сообщение
из группы/супергруппы. В private — всегда True.

Возвращает (should_process, reason, cleaned_text).
reason ∈ {"private", "mention", "reply_to_bot", "trigger_word", "ignored_group_message"}.
"""

from __future__ import annotations

import re
from typing import Iterable

from bot.config import GROUP_PROACTIVE_MODE


def _norm_username(u: str) -> str:
    return (u or "").lstrip("@").strip().lower()


def _strip_mention(text: str, bot_username: str) -> str:
    if not text or not bot_username:
        return text or ""
    pat = re.compile(r"@" + re.escape(bot_username), re.IGNORECASE)
    return pat.sub("", text).strip()


def _has_mention(text: str, bot_username: str) -> bool:
    if not text or not bot_username:
        return False
    return re.search(r"@" + re.escape(bot_username), text, re.IGNORECASE) is not None


def _has_trigger_word(text: str, trigger_words: Iterable[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    for tw in trigger_words:
        tw = (tw or "").strip().lower()
        if not tw:
            continue
        # Если триггер из нескольких слов — проверяем как substring c границами
        # на краях. Для одиночного слова — \b...\b с поддержкой кириллицы.
        if " " in tw:
            # многословные: проверяем, что вокруг — не буквы
            pat = r"(?<![\w])" + re.escape(tw) + r"(?![\w])"
        else:
            pat = r"(?<![\w])" + re.escape(tw) + r"(?![\w])"
        if re.search(pat, low, re.UNICODE):
            return True
    return False


def should_process_message(
    message: dict,
    bot_username: str,
    trigger_words: list[str],
    allow_reply_trigger: bool = True,
) -> tuple[bool, str, str]:
    """
    Решение о допуске сообщения до agent.py.
    Возвращает:
    - bool: обрабатывать или нет
    - str: причина
    - str: очищенный текст без @упоминания бота
    """
    chat = (message or {}).get("chat") or {}
    chat_type = (chat.get("type") or "").lower()
    text = message.get("text") or message.get("caption") or ""

    bot_username_norm = _norm_username(bot_username)
    cleaned = _strip_mention(text, bot_username_norm)

    # private → всегда пропускаем
    if chat_type == "private":
        return True, "private", cleaned

    # каналы и прочее не обрабатываем
    if chat_type not in ("group", "supergroup"):
        return False, "ignored_group_message", cleaned

    # 1) Явный @mention бота
    if _has_mention(text, bot_username_norm):
        return True, "mention", cleaned

    # 2) Reply на сообщение бота
    if allow_reply_trigger:
        reply_to = message.get("reply_to_message") or {}
        reply_from = reply_to.get("from") or {}

        if reply_from:
            reply_is_bot = bool(reply_from.get("is_bot"))
            reply_username = _norm_username(reply_from.get("username") or "")

            # если отвечают на сообщение любого бота — пропускаем
            # для твоей группы это надёжнее, чем жёстко сверять username
            if reply_is_bot:
                return True, "reply_to_bot", cleaned

            # запасной вариант: username совпал с нашим ботом
            if bot_username_norm and reply_username == bot_username_norm:
                return True, "reply_to_bot", cleaned

    # 3) Триггерное слово
    if _has_trigger_word(text, trigger_words):
        return True, "trigger_word", cleaned

    # 4) Proactive mode — обрабатываем почти все сообщения в группе,
    #    модель сама решает, стоит ли отвечать (включая спонтанные реплики).
    if GROUP_PROACTIVE_MODE:
        return True, "group_proactive", cleaned

    return False, "ignored_group_message", cleaned