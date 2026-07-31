from __future__ import annotations
import base64
import re
from typing import Any, Callable, Optional
from bot import memory
# Основной клиент — OpenAI-совместимый (GLM + Gemini)
from bot import openai_client  # type: ignore
from bot.config import (
    DEBUG_USER_IDS, MAX_TOKENS, MAX_TOKENS_DOC,
    MAX_HISTORY_MESSAGES_PER_CHAT, MAX_CONTEXT_CHARS,
    MODEL_FAST, MODEL_SMART,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    OPENAI_VISION_API_KEY, OPENAI_VISION_BASE_URL, OPENAI_VISION_MODEL,
    RESPECT_GLM_8K_LIMIT,
)
from bot.logger import get_logger
from bot.prompts import get_system_prompt
from bot.tools import TOOLS_SCHEMA, dispatch
from bot.storage import safe_tag
from bot import chat_history
from bot.utils import clean_model_output, sanitize_vision_denial

logger = get_logger("agent")
# Limit tool iterations to avoid runaway loops.  The model can call at most
# this many tools per message.  After the limit, we force an answer.
MAX_TOOL_ITERATIONS = 3

# Helper: Trim the conversation history before sending to the LLM.  Free
# versions of Z.ai Flash throttle requests with contexts over ~8K tokens,
# so we apply two limits: (1) only the last MAX_HISTORY_MESSAGES_PER_CHAT
# messages are kept; (2) total character length of the context does not
# exceed MAX_CONTEXT_CHARS.  Messages are trimmed from the start (oldest
# first) to satisfy both limits.
def _apply_context_limits(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Return a slice of msgs respecting both MAX_HISTORY_MESSAGES_PER_CHAT and
    MAX_CONTEXT_CHARS.  Older messages are dropped first.

    Если в конфигурации `RESPECT_GLM_8K_LIMIT` установлено в False, то
    ограничения не применяются и исходный список возвращается.
    """
    if not RESPECT_GLM_8K_LIMIT:
        return list(msgs)
    # Limit by number of messages
    limited: list[dict[str, Any]] = list(msgs)
    if MAX_HISTORY_MESSAGES_PER_CHAT and len(limited) > MAX_HISTORY_MESSAGES_PER_CHAT:
        limited = limited[-MAX_HISTORY_MESSAGES_PER_CHAT:]
    # Limit by total character count (approximate tokens)
    if MAX_CONTEXT_CHARS and MAX_CONTEXT_CHARS > 0:
        total = 0
        trimmed: list[dict[str, Any]] = []
        # iterate from end (newest) to oldest
        for m in reversed(limited):
            content = m.get("content")
            length = 0
            # Estimate length of message content
            if isinstance(content, str):
                length = len(content)
            elif isinstance(content, list):
                for b in content:
                    # b may be dict or object with .text
                    if isinstance(b, dict):
                        if b.get("type") == "text":
                            length += len(b.get("text", ""))
                        else:
                            # Non-text blocks (images/tool) roughly count as short tokens
                            length += 10
                    elif hasattr(b, "text"):
                        length += len(getattr(b, "text", ""))
            # If adding this message would exceed the limit, stop
            if total + length > MAX_CONTEXT_CHARS:
                break
            total += length
            trimmed.append(m)
        limited = list(reversed(trimmed))
    return limited

# --- Per-user model store (runtime only) ---
_user_models: dict[str, str] = {}

# --- Pending opus confirmations {chat_id: {text, attachments}} ---
_pending_opus: dict[str, dict[str, Any]] = {}

# --- Keywords for routing ---
_OPUS_PATTERNS = [
    "большой рефакторинг", "полный рефакторинг", "рефакторинг всего",
    "масштабная архитектура", "массовые изменения", "переписать весь",
    "переписать всё", "опасные изменения", "перестроить архитектур",
]
_SONNET_PATTERNS = [
    "документ", "презентац", "напиши код", "напиши скрипт", "напиши класс",
    "напиши функци", "создай класс", "создай функци", "анализ", "проанализируй",
    "таблиц", "сгенерируй", "напиши приложение", "дебаг", "исправь баг",
    "find bug", "код на", "напиши тест",
]


def get_user_model(chat_id: int | str) -> str | None:
    """Вернуть вручную выбранную модель или None (→ авто-роутинг)."""
    return _user_models.get(str(chat_id))


def set_user_model(chat_id: int | str, model: str | None) -> None:
    """Установить или сбросить (None) выбор модели."""
    key = str(chat_id)
    if model is None:
        _user_models.pop(key, None)
    else:
        _user_models[key] = model
        _pending_opus.pop(key, None)  # сбросить ожидание подтверждения


def _auto_route(text: str, attachments: list | None, chat_type: str = "private") -> tuple[str, int, bool]:
    """
    Вернуть (model, max_tokens, needs_opus_confirm).

    В группах по умолчанию предпочитаем GLM (дешево при высоком количестве сообщений).
    Claude используем только когда есть картинки (vision) или очень сложная задача.
    """
    fast_model = MODEL_FAST
    if OPENAI_API_KEY and OPENAI_BASE_URL:
        fast_model = OPENAI_MODEL

    t = text.lower()

    # Vision и сложные задачи — всегда Sonnet
    if attachments or any(p in t for p in _SONNET_PATTERNS):
        if attachments:
            logger.info("attachments present → forcing MODEL_SMART for vision")
        return MODEL_SMART, MAX_TOKENS_DOC, False

    if any(p in t for p in _OPUS_PATTERNS):
        return MODEL_SMART, MAX_TOKENS_DOC, True

    # В группах (особенно proactive) — GLM как основной рабочий слой
    if chat_type in ("group", "supergroup"):
        return fast_model, MAX_TOKENS, False

    return fast_model, MAX_TOKENS, False


def _resolve_model(chat_id: int | str, text: str, attachments: list | None) -> tuple[str, int]:
    """
    Если у пользователя выбрана модель вручную — используем её.
    Иначе — авто-роутинг (без opus-confirm, это handled снаружи).
    """
    manual = get_user_model(chat_id)
    if manual:
        tok = MAX_TOKENS_DOC if manual in (MODEL_SMART) else MAX_TOKENS
        return manual, tok
    model, tok, _ = _auto_route(text, attachments, chat_type="private")
    return model, tok


def _is_opus_confirm(text: str) -> bool:
    t = text.strip().lower()
    return t in {"да", "yes", "ок", "ok", "окей", "давай", "подтверждаю", "запускай", "поехали", "конечно"}


def _is_opus_cancel(text: str) -> bool:
    t = text.strip().lower()
    return t in {"нет", "no", "отмена", "cancel", "не надо", "стоп", "stop"}


def _strip_debug(text: str, chat_id: int | str) -> str:
    """Убрать случайные JSON-блоки и debug-данные для обычных пользователей."""
    uid = int(str(chat_id)) if str(chat_id).lstrip("-").isdigit() else 0
    if uid in DEBUG_USER_IDS:
        return text
    # Убрать code-блоки с JSON если они содержат tool_use / tool_result паттерны
    cleaned = re.sub(
        r"```(?:json)?\s*\{[^`]*\"type\"\s*:\s*\"tool_(?:use|result)\"[^`]*\}[^`]*```",
        "", text, flags=re.DOTALL
    )
    return cleaned.strip()


def _build_context_preamble(
    memory_obj: dict[str, Any] | None,
    user_context: dict[str, Any] | None,
) -> str:
    """Короткий безопасный контекст для модели. Без system/tool/internal id."""
    if not memory_obj and not user_context:
        return ""
    parts: list[str] = []
    if user_context:
        chat_title = user_context.get("chat_title") or ""
        chat_type = user_context.get("chat_type") or ""
        chat_id = user_context.get("chat_id")
        username = user_context.get("username") or ""
        first_name = user_context.get("first_name") or ""
        user_id = user_context.get("user_id")
        trigger_reason = user_context.get("trigger_reason") or ""
        chat_line = f"chat: type={chat_type}"
        if chat_title:
            chat_line += f", title={chat_title}"
        if chat_id is not None:
            chat_line += f", id={chat_id}"
        parts.append(chat_line)
        u_line = "user:"
        if first_name:
            u_line += f" name={first_name}"
        if username:
            u_line += f" @{username}"
        if user_id is not None:
            u_line += f" id={user_id}"
        parts.append(u_line)
        if trigger_reason:
            parts.append(f"trigger: {trigger_reason}")
    if memory_obj:
        from bot.memory import sanitize_summary_for_context

        chat_type = ((user_context or {}).get("chat_type") or "").lower()
        is_group = chat_type in ("group", "supergroup")

        summary = sanitize_summary_for_context(
            (memory_obj.get("summary") or "").strip(),
            max_chars=800,
        )
        if summary:
            parts.append("summary of older messages:\n" + summary)

        msgs = memory_obj.get("messages") or []
        last = msgs[-MAX_HISTORY_MESSAGES_PER_CHAT:]
        # последний элемент — это только что добавленное user-сообщение,
        # не дублируем его в preamble
        last = last[:-1] if last and last[-1].get("role") == "user" else last
        if last:
            # В группах — только user-линии (0 bot), чтобы не зацикливаться на мемах.
            # В private допускаем максимум 1 последнюю реплику бота.
            lines = ["recent chat history:"]
            bot_candidates: list[str] = []
            for m in last:
                role = m.get("role")
                if role == "user":
                    who = m.get("username") or m.get("first_name") or "user"
                    txt = (m.get("text") or "").replace("\n", " ").strip()
                    if txt:
                        lines.append(f"{who}: {txt}")
                elif role == "assistant" and not is_group:
                    txt = (m.get("text") or "").replace("\n", " ").strip()[:140]
                    if txt:
                        bot_candidates.append(txt)
            if not is_group and bot_candidates:
                lines.append(f"bot (недавно): {bot_candidates[-1]}")
            if len(lines) > 1:
                parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p)


def handle_message(
    chat_id: int | str,
    user_text: str,
    attachments: list[dict[str, Any]] | None = None,
    memory_obj: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    tool_call_callback: Optional[Callable[[str, dict], None]] = None,
) -> str:
    """
    Главная точка входа агента.
    attachments:
      {"type": "image", "bytes": b"...", "mime": "image/jpeg", "name": "photo.jpg"}
      {"type": "document", "name": "file.pdf", "file_id": "abc123"}

    Vision однократен: base64 идёт только в текущий запрос Claude,
    в memory сохраняется только текстовый плейсхолдер.
    """
    user_text = (user_text or "").strip()
    # Record the user's message in chat history.  We use the safe tag derived
    # from the chat_id so that each chat (private or group) gets its own
    # directory and history file.  Only store textual content; attachments
    # are represented separately in memory.
    try:
        tag = safe_tag(str(chat_id)) or "user"
        if user_text:
            chat_history.add_message(tag, "user", user_text)
    except Exception:
        # Logging via chat_history handles its own errors.
        pass
    key = str(chat_id)

    # --- Проверяем: ждём ли подтверждения на Opus? ---
    if key in _pending_opus:
        if _is_opus_confirm(user_text):
            pending = _pending_opus.pop(key)
            return _run_agent(
                chat_id, pending["text"], pending["attachments"],
                model=MODEL_SMART, max_tokens=MAX_TOKENS_DOC,
                memory_obj=memory_obj, user_context=user_context,
                tool_call_callback=tool_call_callback,
            )
        elif _is_opus_cancel(user_text):
            _pending_opus.pop(key, None)
            return "Ок, отменяем. Чем ещё помочь?"
        else:
            # Новый запрос пришёл — сбрасываем ожидание, обрабатываем как обычно
            _pending_opus.pop(key, None)

    # --- Авто-роутинг (только если нет ручного выбора) ---
    manual = get_user_model(chat_id)
    if manual:
        sel_model = manual
        sel_tokens = MAX_TOKENS_DOC if manual in (MODEL_SMART) else MAX_TOKENS
        needs_confirm = False
    else:
        chat_type_hint = (user_context or {}).get("chat_type") or "private"
        sel_model, sel_tokens, needs_confirm = _auto_route(user_text, attachments, chat_type=chat_type_hint)

    # --- Opus требует подтверждения (только при авто-роутинге) ---
    if needs_confirm and not manual:
        _pending_opus[key] = {"text": user_text, "attachments": attachments}
        return (
            "⚠️ Похоже, это тяжёлая задача — стоит подключить Opus.\n"
            "Он медленнее и дороже, но справится лучше.\n\n"
            "Включить Opus для этого запроса? (да / нет)"
        )

    return _run_agent(
        chat_id, user_text, attachments,
        model=sel_model, max_tokens=sel_tokens,
        memory_obj=memory_obj, user_context=user_context,
        tool_call_callback=tool_call_callback,
    )


def _run_agent(
    chat_id: int | str,
    user_text: str,
    attachments: list[dict[str, Any]] | None,
    model: str,
    max_tokens: int,
    memory_obj: dict[str, Any] | None = None,
    user_context: dict[str, Any] | None = None,
    tool_call_callback: Optional[Callable[[str, dict], None]] = None,
) -> str:
    """Ядро агента: собирает контент, гоняет tool-цикл, возвращает ответ."""
    current_content: list[dict[str, Any]] = []  # для Claude (с vision)
    memory_content: list[dict[str, Any]] = []   # для memory (без base64)

    for att in (attachments or []):
        if att["type"] == "image":
            b64 = base64.b64encode(att["bytes"]).decode()
            current_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": att.get("mime", "image/jpeg"),
                    "data": b64,
                },
            })
            ph = "[Пользователь прислал изображение: " + att.get("name", "photo") + "]"
            memory_content.append({"type": "text", "text": ph})
        elif att["type"] == "document":
            intro = (
                "[Пользователь прислал файл: " + att.get("name") +
                " (file_id=" + att.get("file_id") + "). "
                "Используй read_file чтобы прочитать содержимое.]"
            )
            current_content.append({"type": "text", "text": intro})
            memory_content.append({"type": "text", "text": intro})

    # Контекстный preamble (chat/user/summary/history) — если передали
    preamble = _build_context_preamble(memory_obj, user_context)
    if preamble:
        # уходит только в текущий запрос модели, в memory не пишем
        current_content.append({"type": "text", "text": "[context]\n" + preamble})

    if user_text:
        current_content.append({"type": "text", "text": user_text})
        memory_content.append({"type": "text", "text": user_text})

    if not current_content:
        return "Пустое сообщение."

    # Сохраняем в memory без base64 (плейсхолдеры)
    if len(memory_content) == 1 and memory_content[0]["type"] == "text":
        memory.append_user(chat_id, memory_content[0]["text"])
    else:
        memory.append_user(chat_id, memory_content)

    # Упрощаем для Claude если просто текст
    if len(current_content) == 1 and current_content[0]["type"] == "text":
        current_for_claude: Any = current_content[0]["text"]
    else:
        current_for_claude = current_content

    # === Vision handling ===
    # Если явно настроен отдельный vision-эндпоинт (OPENAI_VISION_*) — используем его только для картинок.
    # Иначе — стандартное поведение: attachments → MODEL_SMART (который должен быть Claude).
    has_openai_vision = bool(
        OPENAI_VISION_BASE_URL and OPENAI_VISION_MODEL and not OPENAI_VISION_MODEL.startswith("#")
    )
    use_openai_vision_endpoint = bool(attachments and has_openai_vision)

    # === Принудительно используем vision-эндпоинт для всех картинок ===
    # Это нужно, чтобы Zenoid (и любой слабый "Claude") больше не обрабатывал изображения.
    if attachments and has_openai_vision:
        use_openai_vision_endpoint = True

    if use_openai_vision_endpoint:
        effective_model = OPENAI_VISION_MODEL
        logger.info("VISION: using separate OpenAI-compatible endpoint model=%s (images will be converted to image_url)", effective_model)
    else:
        effective_model = model

    vision_api_key = OPENAI_VISION_API_KEY if use_openai_vision_endpoint else None
    vision_base_url = OPENAI_VISION_BASE_URL if use_openai_vision_endpoint else None

    final_text = ""
    for step in range(MAX_TOOL_ITERATIONS):
        if step == 0:
            history_base = memory.get(chat_id)[:-1]
            history_to_send = history_base + [{"role": "user", "content": current_for_claude}]
        else:
            history_to_send = memory.get(chat_id)
        # Apply context limits (message count and total characters)
        history_to_send = _apply_context_limits(history_to_send)

        chat_type_for_prompt = (user_context or {}).get("chat_type") or "private"
        base_prompt = get_system_prompt(chat_type_for_prompt) or "Ты помощник."

        # Когда есть изображения — добавляем сильную инструкцию для точного описания.
        # Это решает проблему, когда модель выдаёт один и тот же шаблонный ответ на все фото.
        if attachments:
            vision_instruction = (
                "Пользователь прислал изображение(я). Ты **видишь** картинки прямо сейчас. "
                "НИКОГДА не пиши фразы вида: «у меня нет доступа к визуальному восприятию», "
                "«я не вижу никаких изображений», «опиши что на картинке», «пришли текстовое описание», "
                "«я как слепой котёнок» или любые отмазки про отсутствие зрения. "
                "Это строго запрещено. Даже если по техническим причинам картинка не дошла — "
                "всё равно реагируй короткой шуткой в стиле семейного чата, будто ты её отлично увидел "
                "(примеры: «пиздец какая фотка», «ну ты глянь на эту хуйню ахах», «мем века просто»). "
                "Если это мем/рофл — сразу шути, без длинных описаний.\n\n"
            )
            sys_prompt = vision_instruction + base_prompt
        else:
            sys_prompt = base_prompt
            # Для follow-up сообщений после фото: даём жёсткий намёк, чтобы модель не отрицала зрение
            # (история хранит только плейсхолдеры, а не сами байты картинок).
            try:
                recent_texts = []
                for m in (history_to_send or [])[-4:]:
                    c = m.get("content") if isinstance(m, dict) else None
                    if isinstance(c, str):
                        recent_texts.append(c.lower())
                    elif isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "text":
                                recent_texts.append(str(b.get("text", "")).lower())
                if any("[пользователь прислал изображение" in t for t in recent_texts):
                    sys_prompt = (
                        "В последних сообщениях чата было фото. "
                        "Ты его видел. Никогда не пиши, что у тебя нет визуального доступа или «опиши сам». "
                        "Реагируй так, будто отлично помнишь, что там было — шути конкретно и с характером. "
                    ) + sys_prompt
            except Exception:
                pass

        # Сильное давление против избегания инструментов + против зацикливания
        sys_prompt += """

ОБЯЗАТЕЛЬНОЕ ПРАВИЛО ДЛЯ АКТУАЛЬНОЙ ИНФОРМАЦИИ:
- Для любой свежей информации (погода, курс, спорт, новости и т.д.) — **ты обязан вызвать web_search**.
- Запрещено говорить "у меня нет доступа в интернет", "погугли сам" или "посмотри в приложении". Это прямое нарушение правил.
- После результатов сразу давай конкретный ответ. Не начинай с "в сниппетах не хватает данных".

АНТИ-ПОВТОР: не цепляйся за старые мемы и темы из истории чата (картошка, старые рофлы и т.п.), если пользователь не поднял их прямо сейчас. Реагируй свежо.
"""

        # Если декодер определил, что это явный запрос на напоминание — даём сильный targeted пинок
        # (без изменения основного промпта)
        if (user_context or {}).get("reminder_request"):
            sys_prompt += """
ОБЯЗАТЕЛЬНО: пользователь явно попросил поставить напоминание или таймер.
Ты **обязан** использовать инструмент create_reminder.
Правильно разбери время (поддерживает "через 5 минут", "в 21:30", "завтра в 10:00" и т.д.) и текст напоминания.
Не обещай "ок, напомню" словами — вызови инструмент.
"""
        try:
            # Выбор клиента:
            # - Если используется отдельный vision-эндпоинт (Gemini, OpenRouter и т.д.) → всегда OpenAI клиент.
            # - Иначе: если модель GLM или совпадает с OPENAI_MODEL → OpenAI клиент.
            # - В остальных случаях → Claude клиент.
            use_openai = False

            if use_openai_vision_endpoint:
                # Отдельный vision (Gemini / OpenRouter / любой OpenAI-compat) — всегда идём через openai_client
                use_openai = True
            elif OPENAI_API_KEY and OPENAI_BASE_URL:
                if effective_model == OPENAI_MODEL or str(effective_model).startswith("glm"):
                    use_openai = True

            if use_openai:
                if step > 1:
                    openai_tools = None
                resp = openai_client.create_message(
                    messages=history_to_send,
                    system=sys_prompt,
                    tools=TOOLS_SCHEMA,
                    model=effective_model,
                    max_tokens=max_tokens,
                    api_key=vision_api_key,
                    base_url=vision_base_url,
                )
            else:
                # Claude support removed. This path should no longer be reachable.
                raise RuntimeError("Anthropic client was removed. Only OpenAI-compatible path is supported.")

            # === Важный диагностический лог для vision ===
            if attachments:
                client_name = "OpenAI-compatible" if use_openai else "Claude"
                via = "separate VISION endpoint" if use_openai_vision_endpoint else "main model"
                logger.warning(
                    "VISION CALL: attachments=%d → client=%s via=%s model=%s",
                    len(attachments), client_name, via, effective_model
                )
        except Exception as e:
            # Логируем и возвращаем human‑friendly ошибку
            client_name = "OpenAI" if use_openai else "Claude"
            logger.exception("%s API ошибка: %s", client_name, e)
            return _user_facing_error(e)

        memory.append_assistant(chat_id, list(resp.content))
        stop = getattr(resp, "stop_reason", None)
        logger.info("step=%d stop=%s model=%s", step, stop, effective_model)

        if stop == "tool_use":
            # Сообщаем наверх, какие инструменты мы вызываем (для временного статуса)
            if tool_call_callback:
                for block in resp.content:
                    if (isinstance(block, dict) and block.get("type") == "tool_use") or hasattr(block, "name"):
                        name = block.get("name") if isinstance(block, dict) else getattr(block, "name", None)
                        args = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})
                        if name:
                            tool_call_callback(name, args or {})

            tool_results = _run_tools(resp.content, chat_id)
            if not tool_results:
                final_text = _extract_text(resp.content)
                break
            memory.append_tool_results(chat_id, tool_results)
            continue

        final_text = _extract_text(resp.content)
        break
    else:
        logger.warning("Превышен лимит итераций tool-цикла")

    memory.trim(chat_id)

    # === Новый чистый синтез после поиска (архитектурное улучшение) ===
    # Если в этом вызове использовался web_search — делаем отдельный качественный синтез,
    # вместо того чтобы полагаться на то, что модель наговорила в последнем шаге.
    last_tool_results = locals().get('tool_results') or []
    web_results = [r for r in last_tool_results if isinstance(r, dict) and r.get("results")]

    # Если в этом вызове были результаты web_search — делаем чистый синтез
    # вместо того, чтобы полагаться на то, что модель наговорила в последнем шаге.
    if web_results:
        latest_results = web_results[-1].get("results", [])
        if latest_results:
            chat_type = (user_context or {}).get("chat_type") or "private"
            synthesized = _synthesize_from_search_results(user_text, latest_results, chat_type)
            if synthesized and len(synthesized) > 15:
                final_text = synthesized
            else:
                # Если синтез не удался — хотя бы даём честный фоллбэк про поиск
                final_text = "Поиск не дал достаточно полезной информации. Попробуй переформулировать вопрос."

    if not final_text or not final_text.strip():
        # Последняя попытка спасти ответ — упрощённый прямой запрос
        try:
            logger.warning("Пустой ответ от модели, пробуем последний шанс прямого ответа")
            simple_prompt = (
                "Ты — Мистер Батон. Ответь коротко, по делу и с характером на вопрос пользователя. "
                "Пиши с маленькой буквы, как в телеге. Не придумывай, если не знаешь — честно скажи."
            )
            simple_history = [{"role": "user", "content": user_text}]
            # Прямой вызов через OpenAI-совместимый клиент (только GLM/Gemini)
            resp = openai_client.create_message(
                messages=simple_history,
                system=simple_prompt,
                tools=None,
                model=OPENAI_MODEL or "glm-4.5-flash",
                max_tokens=max_tokens,
            )
            final_text = _extract_text(resp.content)
        except Exception as e:
            logger.exception("Последняя попытка прямого ответа тоже упала: %s", e)
            final_text = ""

    result = final_text.strip() or "чот не получилось нормально ответить. переформулируй вопрос чуть проще или по-другому."
    # Жёсткая защита от vision-denial даже во внутренних фоллбэках
    result = sanitize_vision_denial(result)
    # Record assistant's reply into chat history.  Use safe_tag so each
    # chat has its own folder.  Do this before stripping debug to ensure
    # the full answer is preserved in history.
    try:
        tag = safe_tag(str(chat_id)) or "user"
        chat_history.add_message(tag, "assistant", result)
    except Exception:
        pass
    return _strip_debug(result, chat_id)


def _run_tools(content_blocks: list[Any], chat_id: int | str) -> list[dict[str, Any]]:
    """Выполнить вызовы инструментов, которые вернула модель.

    Поддерживает как объекты SDK Anthropic (с атрибутами .type/.name/.input),
    так и dict‑блоки (от openai_client).  Возвращает список результатов
    с типом tool_result.
    """
    results: list[dict[str, Any]] = []
    for block in content_blocks:
        # Определяем тип и параметры блока
        btype: str | None = None
        bname: str | None = None
        binput: Any = None
        bid: str | None = None
        if hasattr(block, "type"):
            btype = getattr(block, "type", None)
            bname = getattr(block, "name", None)
            binput = getattr(block, "input", None)
            bid = getattr(block, "id", None)
        elif isinstance(block, dict):
            btype = block.get("type")
            bname = block.get("name")
            binput = block.get("input")
            bid = block.get("id")
        if btype != "tool_use":
            continue
        # Исполнение инструмента
        output = dispatch(
            bname or "",
            binput or {},
            chat_id,
        )
        results.append({
            "type": "tool_result",
            "tool_use_id": bid or "",
            "content": output,
        })
    return results


def _extract_text(content_blocks: list[Any]) -> str:
    """Извлечь текстовые блоки из ответа модели.

    Поддерживает как SDK‑объекты (.text/.type), так и dict‑блоки
    с ключами "text" и "type".
    Также агрессивно чистит любые утечки tool calls в текст (проблема GLM).
    """
    import re
    parts: list[str] = []
    for b in content_blocks:
        btype = None
        btext = ""
        if hasattr(b, "type"):
            btype = getattr(b, "type", None)
            if btype == "text":
                btext = getattr(b, "text", "") or ""
        elif isinstance(b, dict):
            btype = b.get("type")
            if btype == "text":
                btext = b.get("text", "") or ""
        if btype == "text" and btext:
            parts.append(btext)

    text = "\n".join(p.strip() for p in parts if p).strip()

    # Жёсткая очистка от утечек tool calls (GLM часто пишет их текстом)
    text = re.sub(r'\[assistant requested tool.*?\]', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'```tool_call.*?```', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\{["\']?name["\']?\s*:\s*["\']?web_search["\']?.*?\}', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\n\s*\n', '\n\n', text).strip()

    # Очистка от thinking-тегов (GLM / reasoning модели иногда возвращают </think>)
    text = clean_model_output(text)

    return text


def _synthesize_from_search_results(original_question: str, search_results: list[dict], chat_type: str = "group") -> str:
    """
    Чистый синтез ответа на основе результатов поиска.
    Это отдельный шаг, чтобы слабые модели не смешивали исследование с финальным ответом.
    """
    if not search_results:
        return "Поиск не дал полезных результатов."

    # Форматируем результаты максимально структурировано для слабых моделей
    formatted_results = []
    for i, r in enumerate(search_results, 1):
        title = r.get("title", "").strip()
        snippet = (r.get("snippet", "") or r.get("content", "")).strip()
        url = r.get("url", "").strip()
        formatted_results.append(
            f"Результат {i}:\n"
            f"Заголовок: {title}\n"
            f"Текст: {snippet}\n"
            f"Ссылка: {url}"
        )

    results_text = "\n\n".join(formatted_results)

    synthesis_prompt = (
        "Ты — точный исследователь. Твоя ЕДИНСТВЕННАЯ задача — ответить на вопрос пользователя, "
        "используя ТОЛЬКО информацию из предоставленных результатов поиска.\n\n"
        f"Вопрос пользователя: {original_question}\n\n"
        "Результаты поиска:\n"
        f"{results_text}\n\n"
        "ПРАВИЛА (нарушать нельзя):\n"
        "- Извлекай конкретные цифры, факты и данные, если они есть в любом из результатов.\n"
        "- Никогда не начинай ответ с фраз про «сниппеты», «недостаточно данных» или «нужно читать полные статьи».\n"
        "- Если в результатах есть хоть какая-то полезная информация — используй её и дай лучший возможный ответ.\n"
        "- Только если результаты вообще ничего полезного не содержат — тогда честно скажи, что информации недостаточно.\n"
        "- Отвечай прямо и по делу. Избегай воды."
    )

    try:
        # Синтез всегда делаем через основной текстовый клиент (сейчас GLM)
        resp = openai_client.create_message(
            messages=[{"role": "user", "content": synthesis_prompt}],
            system="Ты — точный исследователь. Отвечай строго на основе предоставленных результатов поиска. Будь прямым и извлекай конкретные данные.",
            tools=None,
            model=OPENAI_MODEL,
            max_tokens=1500,
        )
        return _extract_text(resp.content)
    except Exception as e:
        logger.exception("Ошибка синтеза из результатов поиска: %s", e)
        return "Не удалось нормально обработать результаты поиска."


def _user_facing_error(e: Exception) -> str:
    msg = str(e).lower()
    ename = type(e).__name__.lower()
    if "401" in msg or "403" in msg or "auth" in ename:
        return "Не получилось обратиться к модели: проблема с авторизацией. Проверь OPENAI_API_KEY / OPENAI_BASE_URL."
    if "timeout" in msg or "timeout" in ename:
        return "Модель не ответила вовремя. Попробуй ещё раз."
    return "Что-то пошло не так при обращении к модели. Попробуй ещё раз позже."
