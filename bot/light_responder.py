"""
LightCasualResponder — лёгкий путь для обычных семейных сообщений.

Цель:
- Для 80-90% реплик в семейной группе (болтовня, рофлы, мемы, короткие реакции)
  давать быстрый, характерный ответ Мистера Батона, не таща весь тяжёлый
  tool-loop и огромный промпт с требованиями web_search.
- При пустых ответах от GLM — 1-2 ретрая с деградацией + честный fallback на Claude.

Используется после GroupGate + LLMResponseDecider, когда тот сказал "casual".
"""

from __future__ import annotations

import time
from typing import Any, Optional

from bot import openai_client
from bot.config import (
    OPENAI_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    MAX_TOKENS,
    TEMPERATURE,
)
from bot.logger import get_logger
from bot.memory import load_chat_memory
from bot.prompts import GROUP_CASUAL_SYSTEM_PROMPT
from bot.utils import clean_model_output

logger = get_logger("light")

# Простой in-memory circuit breaker per chat.
# При 2+ пустых ответах GLM подряд в течение TTL минут — переключаемся на Claude для этого чата.
_CASUAL_FALLBACK: dict[str, dict[str, Any]] = {}
_GLM_EMPTY_THRESHOLD = 2
_CLAUDE_FALLBACK_TTL = 15 * 60  # 15 минут


def _get_time_directive() -> str:
    """Мини-версия time directive (чтобы не зависеть от приватных имён в prompts)."""
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo("Europe/Moscow"))
        tz = "MSK"
    except Exception:
        now = dt.datetime.utcnow() + dt.timedelta(hours=3)
        tz = "MSK"
    return f"[ТЕКУЩЕЕ ВРЕМЯ — ИСПОЛЬЗУЙ ТОЛЬКО ЕГО]\nСейчас: {now.day} {now.strftime('%B %Y')}, {now.strftime('%H:%M')} {tz}\n"


def _get_fallback_model(chat_id: int | str) -> str:
    """Возвращает 'claude' если для этого чата включён временный fallback, иначе 'glm'."""
    key = str(chat_id)
    state = _CASUAL_FALLBACK.get(key)
    if not state:
        return "glm"
    if time.time() - state.get("switched_at", 0) > _CLAUDE_FALLBACK_TTL:
        _CASUAL_FALLBACK.pop(key, None)
        return "glm"
    return "claude"


def _record_glm_empty(chat_id: int | str) -> bool:
    """Увеличивает счётчик пустых GLM. Возвращает True, если пора переключаться на Claude."""
    key = str(chat_id)
    now = time.time()
    state = _CASUAL_FALLBACK.setdefault(key, {"count": 0, "switched_at": 0})
    state["count"] = state.get("count", 0) + 1
    if state["count"] >= _GLM_EMPTY_THRESHOLD:
        state["switched_at"] = now
        logger.warning("light: chat=%s GLM пустой %d раз подряд — временно переключаемся на Claude",
                       chat_id, state["count"])
        return True
    return False


def _build_light_context(memory_obj: dict[str, Any] | None, max_msgs: int = 6) -> str:
    """Собирает очень компактный контекст только из per-chat memory (summary + последние сообщения)."""
    if not memory_obj:
        return ""
    parts: list[str] = []
    summary = (memory_obj.get("summary") or "").strip()
    if summary:
        parts.append("Краткая сводка предыдущего:\n" + summary[:1500])

    msgs = memory_obj.get("messages") or []
    if msgs:
        recent = msgs[-max_msgs:]
        lines = ["Последние сообщения в чате (в основном реплики пользователей):"]
        shown_bot = 0
        for m in recent:
            role = m.get("role")
            txt = (m.get("text") or "").strip().replace("\n", " ")[:140]
            if not txt:
                continue
            if role == "user":
                lines.append(f"user: {txt}")
            elif role == "assistant" and shown_bot < 1:
                lines.append(f"бот (недавно): {txt}")
                shown_bot += 1
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
    Возвращает готовый текст ответа (с характером, маленькой буквы и т.д.).
    Никогда не вызывает инструменты.
    """
    user_text = (user_text or "").strip()
    if not user_text:
        return "[молчу]"

    # 1. Контекст (лёгкий)
    context_block = _build_light_context(chat_memory or {}, max_msgs=6)
    preamble = ""
    if context_block:
        preamble = "[context]\n" + context_block + "\n\n"

    # 2. System prompt (лёгкий + время)
    sys_prompt = _get_time_directive() + GROUP_CASUAL_SYSTEM_PROMPT

    # 3. Выбор модели (с учётом circuit breaker)
    use_claude = _get_fallback_model(chat_id) == "claude"
    model_name = "claude (fallback)" if use_claude else OPENAI_MODEL

    messages = [
        {"role": "user", "content": preamble + user_text}
    ]

    final_text = ""
    attempts = 2 if not use_claude else 1   # на Claude обычно не пустит

    for attempt in range(attempts):
        try:
            if use_claude or not (OPENAI_API_KEY and OPENAI_BASE_URL):
                # Fallback на Claude (Haiku предпочтительнее для скорости/цены)
                # Claude support was removed. This should not be reached.
                raise RuntimeError("Claude client removed. Only OpenAI-compatible path supported.")
            else:
                temp = 0.75 if attempt == 0 else 0.55   # небольшая деградация на ретрае
                resp = openai_client.create_message(
                    messages=messages,
                    system=sys_prompt,
                    tools=None,
                    model=OPENAI_MODEL,
                    max_tokens=max_tokens,
                )

            # Извлекаем текст
            text = ""
            for b in (resp.content or []):
                if isinstance(b, dict) and b.get("type") == "text":
                    text = b.get("text", "") or ""
                elif hasattr(b, "text"):
                    text = getattr(b, "text", "") or ""
            final_text = clean_model_output(text or "")

            if final_text:
                break

            # Пустой ответ
            if not use_claude:
                switched = _record_glm_empty(chat_id)
                if switched:
                    use_claude = True
                    logger.info("light: переключился на Claude для chat=%s", chat_id)
            logger.warning("light: пустой ответ на попытке %d (model=%s)", attempt + 1, model_name)

        except Exception as e:
            logger.exception("light: ошибка вызова модели (attempt %d): %s", attempt + 1, e)
            if attempt == attempts - 1:
                final_text = ""

    # 4. Если совсем ничего не получилось — честный фоллбэк с характером
    if not final_text:
        final_text = "чот сегодня я туповат. переформулируй чуть проще."

    # 5. Обработка специальных маркеров
    low = final_text.lower().strip()
    if low in {"[молчу]", "молчу", "[молчу.]"}:
        return "[молчу]"

    # 6. Лёгкая нормализация (маленькая буква) — финальный пост-процесс сделает main.py,
    # но для надёжности делаем здесь тоже.
    if final_text and final_text[0].isupper():
        final_text = final_text[0].lower() + final_text[1:]

    logger.info("light: ответ chat=%s len=%d via=%s", chat_id, len(final_text), "claude" if use_claude else "glm")
    return final_text.strip()