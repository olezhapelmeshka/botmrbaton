"""
LightCasualResponder — лёгкий путь для обычных групповых сообщений.

Цель:
- Для большинства реплик (болтовня, рофлы, мемы, короткие реакции)
  давать быстрый характерный ответ, не таща тяжёлый tool-loop.
- При пустых ответах от модели — 1-2 ретрая с деградацией температуры.

Используется после GroupGate + LLMResponseDecider, когда тот сказал "casual".
"""

from __future__ import annotations

from typing import Any

from bot import openai_client
from bot.config import (
    OPENAI_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    MAX_TOKENS,
)
from bot.logger import get_logger
from bot.prompts import GROUP_CASUAL_SYSTEM_PROMPT
from bot.utils import clean_model_output

logger = get_logger("light")


def _get_time_directive() -> str:
    """Мини-версия time directive."""
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo("Europe/Moscow"))
        tz = "MSK"
    except Exception:
        now = dt.datetime.utcnow() + dt.timedelta(hours=3)
        tz = "MSK"
    return f"[ТЕКУЩЕЕ ВРЕМЯ — ИСПОЛЬЗУЙ ТОЛЬКО ЕГО]\nСейчас: {now.day} {now.strftime('%B %Y')}, {now.strftime('%H:%M')} {tz}\n"


def _build_light_context(memory_obj: dict[str, Any] | None, max_msgs: int | None = None) -> str:
    """Собирает компактный контекст: user-only history + sanitized summary (без bot-мемов)."""
    from bot.config import MAX_HISTORY_MESSAGES_PER_CHAT
    from bot.memory import sanitize_summary_for_context

    if not memory_obj:
        return ""
    if max_msgs is None:
        max_msgs = MAX_HISTORY_MESSAGES_PER_CHAT

    parts: list[str] = []
    summary = sanitize_summary_for_context(
        (memory_obj.get("summary") or "").strip(),
        max_chars=800,
    )
    if summary:
        parts.append("Краткая сводка предыдущего:\n" + summary)

    msgs = memory_obj.get("messages") or []
    if msgs:
        recent = msgs[-max_msgs:]
        lines = ["Последние сообщения в чате (реплики пользователей):"]
        for m in recent:
            if m.get("role") != "user":
                continue
            txt = (m.get("text") or "").strip().replace("\n", " ")[:140]
            if not txt:
                continue
            who = m.get("username") or m.get("first_name") or "user"
            lines.append(f"{who}: {txt}")
        if len(lines) > 1:
            parts.append("\n".join(lines))
    return "\n\n".join(parts)


def handle_light_chat(
    chat_id: int | str,
    user_text: str,
    chat_memory: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """
    Главная точка входа лёгкого пути.
    Возвращает готовый текст ответа. Никогда не вызывает инструменты.
    """
    del user_context  # reserved for future context injection
    user_text = (user_text or "").strip()
    if not user_text:
        return "[молчу]"

    if not (OPENAI_API_KEY and OPENAI_BASE_URL):
        logger.error("light: OPENAI_API_KEY/BASE_URL not configured")
        return "чот сегодня я туповат. переформулируй чуть проще."

    context_block = _build_light_context(chat_memory or {}, max_msgs=6)
    preamble = ""
    if context_block:
        preamble = "[context]\n" + context_block + "\n\n"

    sys_prompt = _get_time_directive() + GROUP_CASUAL_SYSTEM_PROMPT
    messages = [{"role": "user", "content": preamble + user_text}]

    final_text = ""
    attempts = 2

    for attempt in range(attempts):
        try:
            resp = openai_client.create_message(
                messages=messages,
                system=sys_prompt,
                tools=None,
                model=OPENAI_MODEL,
                max_tokens=max_tokens,
            )

            text = ""
            for b in (resp.content or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    text = b.get("text", "") or ""
                elif hasattr(b, "text"):
                    text = getattr(b, "text", "") or ""
            final_text = clean_model_output(text or "")

            if final_text:
                break

            logger.warning(
                "light: пустой ответ на попытке %d (model=%s chat=%s)",
                attempt + 1, OPENAI_MODEL, chat_id,
            )

        except Exception as e:
            logger.exception("light: ошибка вызова модели (attempt %d): %s", attempt + 1, e)
            if attempt == attempts - 1:
                final_text = ""

    if not final_text:
        final_text = "чот сегодня я туповат. переформулируй чуть проще."

    low = final_text.lower().strip()
    if low in {"[молчу]", "молчу", "[молчу.]"}:
        return "[молчу]"

    if final_text and final_text[0].isupper():
        final_text = final_text[0].lower() + final_text[1:]

    logger.info("light: ответ chat=%s len=%d via=%s", chat_id, len(final_text), OPENAI_MODEL)
    return final_text.strip()
