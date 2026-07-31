"""
Точка входа.
Запуск: python bot/main.py

Типы апдейтов:
- text    → обычный диалог или команда
- photo   → vision (base64 в текущий запрос, плейсхолдер в memory)
- document → скачать → workspace → агент вызывает read_file сам
- остальное → вежливый отказ
"""
from __future__ import annotations

import sys
import time
import re
from pathlib import Path
from datetime import datetime, timedelta

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from bot import (
    agent, antispam, config, files as files_module,
    memory, scheduler, schedules, telegram_api, workspace,
)
from bot.group import GroupGate, GroupGateConfig
from bot.group.decision import LLMResponseDecider  # GLM as decision layer
from bot import light_responder  # новый лёгкий путь для семейной болтовни (casual)


def _looks_like_reminder_request(text: str) -> bool:
    """Простая но надёжная проверка — человек явно просит напоминание/таймер."""
    if not text:
        return False
    t = text.lower()
    if any(w in t for w in ["напомни", "поставь таймер", "поставь напоминание", "разбуди меня", "не дай забыть"]):
        return True
    # "через 5 минут ..." + действие
    if re.search(r"через\s+\d+\s*(минут|мин|час|часов)", t) and any(v in t for v in ["напомн", "скажи", "разбуди", "заставь", "сделай"]):
        return True
    # "в 21:30 ..." или "в 8 утра"
    if re.search(r"в\s+\d{1,2}[:.]\d{2}", t) and any(v in t for v in ["напомн", "скажи", "разбуди"]):
        return True
    if re.search(r"в\s+\d{1,2}\s*(утра|вечера|дня)", t) and "напомн" in t:
        return True
    return False
from bot.utils import (
    clean_model_output,
    is_near_repeat,
    recent_assistant_texts,
    sanitize_vision_denial,
)
from bot.storage import get_user_tag
from bot.config import (
    BOT_USERNAME, GROUP_ALLOW_REPLY_TRIGGER, GROUP_TRIGGER_WORDS,
    MAX_FILE_SIZE_MB, MAX_HISTORY_MESSAGES_PER_CHAT,
    MODEL_FAST, MODEL_SMART, OPENAI_MODEL,
)
from bot.logger import get_logger


logger = get_logger("main")
_MAX_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Имя бота — берём из config, при старте обновим из getMe.
_bot_username: str = config.TELEGRAM_TOKEN  # placeholder, обновится в run()

# Новый Group Gate (инициализируется в run())
_group_gate: "GroupGate | None" = None


# Паттерн для распознавания фраз с напоминаниями
_TIME_PATTERNS = [
    (r"через\s+(\d+)\s+минут", "interval_minutes"),
    (r"через\s+(\d+)\s+час(а|ов)?", "interval_hours"),
    (r"каждый день\s+(в\s+)?(ЧЧ:ММ)", "daily"),
    (r"завтра\s+(в\s+)?(ЧЧ:ММ)", "tomorrow"),
    (r"в\s+(\d{1,2}):(\d{2})", "explicit_time"),
    (r"в\s+(ЯНВАРЬ|ФЕВРАЛЬ|МАРТ|АПРЕЛЬ|МАЙ|ИЮНЬ|ИЮЛЬ|АВГУСТ|СЕНТЯБРЬ|ОКТЯБРЬ|НОЯБРЬ|ДЕКАБРЬ)\s+(\d{1,2})", "date_month"),
    (r"в\s+(\d{4})-(\d{1,2})-(\d{1,2})\s+(в\s+)?(ЧЧ:ММ)?", "explicit_date"),
]

def _parse_reminder_time(text: str) -> dict[str, Any] | None:
    """
    Распознавание времени из фразы.
    Возвращает {'repeat': 'once'|'daily'|'interval', 'time': 'ЧЧ:ММ', 'interval_seconds': int}
    или None если время не распознано.
    """
    text_lower = text.lower()
    
    # Проверяем на "каждый день"
    if "каждый день" in text_lower:
        return {"repeat": "daily"}
    
    # Проверяем на "завтра"
    if "завтра" in text_lower:
        return {"repeat": "daily"}
    
    # Проверяем на "через N минут"
    for pattern, kind in _TIME_PATTERNS:
        if re.search(pattern, text_lower):
            if kind == "interval_minutes":
                m = re.search(r"через\s+(\d+)\s+минут", text_lower)
                if m:
                    return {"repeat": "interval", "interval_seconds": int(m.group(1)) * 60}
            elif kind == "interval_hours":
                m = re.search(r"через\s+(\d+)\s+час", text_lower)
                if m:
                    return {"repeat": "interval", "interval_seconds": int(m.group(1)) * 3600}
    
    # Попытка извлечь ЧЧ:ММ
    m = re.search(r"(?:в\s+)?(\d{1,2}):(\d{2})", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return {"repeat": "daily", "time": f"{hour:02d}:{minute:02d}"}
    
    return None


def _legacy_parse_single_reminder(text: str) -> list[dict]:
    """Fallback parser for simple cases when LLM parser fails."""
    text_lower = text.lower().strip()
    now = datetime.now()

    # через N минут
    m = re.search(r"через\s+(\d+)\s+минут", text_lower)
    if m:
        minutes = int(m.group(1))
        run_time = now + timedelta(minutes=minutes)
        reminder_text = re.sub(r"через\s+\d+\s+минут\s*", "", text, flags=re.IGNORECASE).strip()
        return [{
            "repeat": "once",
            "run_at_iso": run_time.isoformat(),
            "text": reminder_text or text
        }]

    # через N часов
    m = re.search(r"через\s+(\d+)\s+час", text_lower)
    if m:
        hours = int(m.group(1))
        run_time = now + timedelta(hours=hours)
        reminder_text = re.sub(r"через\s+\d+\s+час\w*\s*", "", text, flags=re.IGNORECASE).strip()
        return [{
            "repeat": "once",
            "run_at_iso": run_time.isoformat(),
            "text": reminder_text or text
        }]

    # HH:MM
    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        reminder_text = re.sub(r"\d{1,2}:\d{2}\s*", "", text).strip()
        return [{
            "repeat": "daily",
            "time": f"{hour:02d}:{minute:02d}",
            "text": reminder_text or text
        }]

    return []


def _postprocess_group_reply(
    text: str,
    chat_memory: dict | None = None,
) -> str:
    """Лёгкий пост-процессинг ответов в группах для соблюдения стиля."""
    if not text:
        return text

    # Защита от утечек thinking-тегов из reasoning-моделей (GLM и т.п.)
    text = clean_model_output(text)

    # Жёсткая защита: никогда не показываем пользователю "я не вижу картинки"
    text = sanitize_vision_denial(text)

    # Анти-повтор мемов: почти тот же ответ что недавно → молчим
    if is_near_repeat(text, recent_assistant_texts(chat_memory, n=5)):
        return "[молчу]"

    # Принудительно маленькие буквы (кроме специальных случаев)
    if text:
        text = text[0].lower() + text[1:]

    # Обрезаем слишком длинные ответы в группе (чтобы не превращался в эссе)
    if len(text) > 450:
        # Обрезаем до последнего нормального предложения
        cut = text[:420]
        last_dot = cut.rfind(".")
        if last_dot > 200:
            text = cut[:last_dot + 1]
        else:
            text = cut.rstrip() + "..."

    return text


HELP_TEXT = (
    "привет. я Мистер Батон.\n"
    "не особо вежливый, но полезный.\n\n"
    "команды:\n"
    "/start              — приветствие\n"
    "/help               — список команд\n"
    "/reset              — очистить историю диалога\n"
    "/files              — показать файлы в workspace\n"
    "/clear              — удалить все файлы и историю\n\n"
    "расписание (новое, умное):\n"
    "Просто напиши в чат:\n"
    "• через 25 минут напомни купить хлеб\n"
    "• в 11:28 позвони маме\n"
    "• каждый понедельник в 9:00 утренняя зарядка\n"
    "Или кинь целое расписание — я разберу.\n\n"
    "Команды:\n"
    "/schedule_list             — список напоминаний\n"
    "/schedule_remove N         — удалить напоминание №N\n\n"
"что умею:\n"
    "• отвечать на вопросы и вести диалог\n"
    "• искать в интернете свежую информацию\n"
    "• читать и анализировать файлы + картинки\n"
    "• создавать документы и презентации\n"
    "• умные напоминания (просто скажи «напомни через 40 минут...» или кинь расписание)\n"
    "• анализ YouTube видео по ссылке (метаданные + субтитры)"
)

START_TEXT = (
    "привет. я Мистер Батон.\n"
    "работаю на OpenAI-совместимых моделях (GLM + vision) и умею:\n"
    "• отвечать на вопросы и искать в интернете\n"
    "• читать и создавать файлы (PDF, DOCX, XLSX...)\n"
    "• смотреть картинки (vision)\n"
    "• вести блокнот заметок\n"
    "• ставить умные напоминания\n"
    "• анализировать YouTube видео по ссылке\n\n"
    "напиши /help для полного списка команд или просто задай вопрос."
)


def _handle_command(chat_id: int, text: str, chat_type: str = "private", user: dict | None = None) -> bool:
    cmd = text.split()[0].lower().split("@")[0]
    user = user or {}
    user_tag = get_user_tag(user) if user else str(chat_id)

    if cmd == "/start":
        telegram_api.send_message(chat_id, START_TEXT)
        return True

    if cmd == "/help":
        telegram_api.send_message(chat_id, HELP_TEXT)
        return True

    if cmd == "/reset":
        memory.reset(chat_id)
        memory.reset_chat_memory(chat_id, chat_type)
        telegram_api.send_message(chat_id, "История очищена. Начнём с чистого листа. 🗑️")
        return True

    if cmd == "/files":
        file_list = workspace.list_files(chat_id)
        if not file_list:
            telegram_api.send_message(chat_id, "Workspace пуст.")
        else:
            lines = ["📁 Файлы в workspace:"]
            for f in file_list:
                size_kb = f["size"] / 1024
                kind_icon = "📥" if f["kind"] == "input" else "📤"
                lines.append(f"{kind_icon} {f['name']} ({size_kb:.1f} KB) — id: {f['id']}")
            telegram_api.send_message(chat_id, "\n".join(lines))
        return True

    if cmd == "/clear":
        n_files = workspace.clear(chat_id)
        memory.reset(chat_id)
        memory.reset_chat_memory(chat_id, chat_type)
        telegram_api.send_message(
            chat_id,
            f"Очищено: {n_files} файлов и история диалога. Начнём с нуля. 🧹",
        )
        return True

    if cmd == "/model":
        telegram_api.send_message(chat_id, "Выбор модели отключён. Сейчас используется авто-роутинг (GLM для обычных сообщений, умная модель для сложных задач).")
        return True

    # --- расписание (улучшенное) ---
    if cmd == "/schedule_add":
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            telegram_api.send_message(chat_id, "Напиши так: /schedule_add через 40 минут купить молоко\nИли: /schedule_add 11:28 позвонить маме")
            return True

        user_request = parts[1]

        from bot import reminder_parser
        now = datetime.now()
        parsed = reminder_parser.parse_reminders(user_request, now)

        if not parsed:
            # Fallback to old simple parser
            parsed = _legacy_parse_single_reminder(user_request)

        if not parsed:
            telegram_api.send_message(chat_id, "Не понял время. Примеры:\n• через 25 минут напомни про встречу\n• в 11:28 купить хлеб\n• каждый день в 09:30 зарядка")
            return True

        created_count = 0
        for task_data in parsed:
            task = schedules.add_task(
                user_tag=user_tag,
                chat_id=chat_id,
                action_type="reminder",
                repeat=task_data.get("repeat", "once"),
                time_s=task_data.get("time"),
                date=task_data.get("date"),
                weekdays=task_data.get("weekdays"),
                interval_seconds=task_data.get("interval_seconds"),
                text=task_data.get("text", user_request),
                run_at_iso=task_data.get("run_at_iso"),
            )
            if task:
                created_count += 1

        if created_count > 0:
            telegram_api.send_message(chat_id, f"Добавлено напоминаний: {created_count} ✅")
        else:
            telegram_api.send_message(chat_id, "Не удалось сохранить напоминания.")
        return True

    if cmd == "/schedule_list":
        tasks = schedules.list_tasks(user_tag)
        if not tasks:
            telegram_api.send_message(chat_id, "у тебя нет напоминаний. добавь: /schedule_add ЧЧ:ММ текст")
        else:
            lines = ["📅 напоминания:"]
            for i, t in enumerate(tasks, 1):
                lines.append(f"{i}. {schedules.format_task_short(t)}")
            telegram_api.send_message(chat_id, "\n".join(lines))
        return True

    if cmd == "/schedule_remove":
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            telegram_api.send_message(chat_id, "использование: /schedule_remove N (номер из /schedule_list)")
            return True
        removed = schedules.remove_by_index(user_tag, int(parts[1]))
        if removed is None:
            telegram_api.send_message(chat_id, "нет напоминания с таким номером. посмотри /schedule_list")
        else:
            telegram_api.send_message(chat_id, f"напоминание удалено 🗑️: {removed.get('text', '?')}")
        return True

    # неизвестная команда
    telegram_api.send_message(chat_id, "Не знаю такой команды. Просто напиши мне, что нужно — я разберусь.")
    return True


_MODEL_NAMES = {
    MODEL_FAST: f"Fast ({MODEL_FAST})",
    MODEL_SMART: f"Smart ({MODEL_SMART})",
    OPENAI_MODEL: f"Default ({OPENAI_MODEL})",
}


def _handle_model_command(chat_id: int, arg: str) -> bool:
    model_map = {
        "fast": MODEL_FAST,
        "smart": MODEL_SMART,
        "glm": OPENAI_MODEL,
        "default": OPENAI_MODEL,
    }

    if arg == "current":
        current = agent.get_user_model(chat_id)
        if current:
            telegram_api.send_message(chat_id, f"Текущая модель: {_MODEL_NAMES.get(current, current)}")
        else:
            telegram_api.send_message(chat_id, "Модель выбирается автоматически (авто-роутинг)")
        return True

    if arg in model_map:
        model = model_map[arg]
        agent.set_user_model(chat_id, model)
        telegram_api.send_message(chat_id, f"Модель: {_MODEL_NAMES.get(model, model)}")
        return True

    if arg == "auto":
        agent.set_user_model(chat_id, None)
        telegram_api.send_message(chat_id, "Авто-роутинг включён")
        return True

    keyboard = [
        [
            {"text": "Fast", "callback_data": "model:fast"},
            {"text": "Smart", "callback_data": "model:smart"},
        ],
        [
            {"text": "Default (GLM)", "callback_data": "model:glm"},
            {"text": "Auto", "callback_data": "model:auto"},
        ],
        [
            {"text": "Текущая модель", "callback_data": "model:current"},
        ],
    ]
    telegram_api.send_message_with_keyboard(
        chat_id,
        "Выбери модель:",
        keyboard,
    )
    return True


def _handle_callback_query(callback_query: dict) -> None:
    cq_id = callback_query.get("id", "")
    data = callback_query.get("data", "")
    msg = callback_query.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id: int = chat.get("id")
    if not chat_id:
        return

    if data.startswith("model:"):
        arg = data[6:]
        model_map = {
            "fast": MODEL_FAST,
            "smart": MODEL_SMART,
            "glm": OPENAI_MODEL,
            "default": OPENAI_MODEL,
            # legacy callback ids
            "haiku": MODEL_FAST,
            "sonnet": MODEL_SMART,
        }
        if arg == "current":
            current = agent.get_user_model(chat_id)
            if current:
                answer_text = f"Сейчас: {_MODEL_NAMES.get(current, current)}"
            else:
                answer_text = "Сейчас: авто-роутинг"
            telegram_api.answer_callback_query(cq_id, answer_text)
        elif arg == "auto":
            agent.set_user_model(chat_id, None)
            telegram_api.answer_callback_query(cq_id, "Авто-роутинг включён")
            telegram_api.send_message(chat_id, "Авто-роутинг включён")
        elif arg in model_map:
            model = model_map[arg]
            agent.set_user_model(chat_id, model)
            label = _MODEL_NAMES.get(model, model)
            telegram_api.answer_callback_query(cq_id, f"{label}")
            telegram_api.send_message(chat_id, f"Модель: {label}")
        else:
            telegram_api.answer_callback_query(cq_id, "Неизвестная опция")


def _download(file_id_tg: str) -> bytes | None:
    info = telegram_api.get_file_info(file_id_tg)
    if not info:
        return None
    return telegram_api.download_file(info["file_path"], _MAX_BYTES)


def _process_update(update: dict) -> None:
    # --- callback_query (нажатие inline-кнопки) ---
    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
        return

    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat = msg.get("chat") or {}
    chat_id: int = chat.get("id")
    if not chat_id:
        return
    chat_type: str = (chat.get("type") or "").lower()
    chat_title: str = chat.get("title") or chat.get("username") or ""

    user = msg.get("from") or {}
    user_id = user.get("id")
    username = user.get("username") or ""
    first_name = user.get("first_name") or ""
    label = username or first_name or str(user_id or "?")

    text: str = msg.get("text", "") or ""
    caption: str = msg.get("caption", "") or ""
    user_text = text or caption  # берём caption для фото/документов с подписью

    # --- команды ---
    if text.startswith("/"):
        logger.info("← cmd chat=%s user=%s: %s", chat_id, label, text.split()[0])
        _handle_command(chat_id, text, chat_type=chat_type, user=user)
        return

    # === GROUP GATE (новая система) ===
    processed_by_new_gate = False
    trigger_reason: str = "private"   # дефолт для личных сообщений

    if chat_type in ("group", "supergroup") and _group_gate is not None:
        gate_result = _group_gate.should_process_message(msg)
        processed_by_new_gate = True

        if not gate_result.should_process:
            snippet = (user_text or "")[:80].replace("\n", " ")
            logger.info(
                '[GROUP IGNORE] reason=%s chat="%s" user="@%s" text="%s"',
                gate_result.reason.value,
                chat_title or chat_id,
                label,
                snippet
            )
            return

        trigger_reason = gate_result.reason.value

        logger.info(
            '[GROUP HIT] reason=%s level=%s chat="%s" user="@%s"',
            gate_result.reason.value,
            gate_result.user_level.value,
            chat_title or chat_id,
            label
        )

        if gate_result.cleaned_text:
            user_text = gate_result.cleaned_text

        # Новый структурный сигнал от decider: casual (лёгкий путь) или agent (полный с инструментами)
        suggested_path = gate_result.metadata.get("suggested_path", "agent")
        is_reminder_request = bool(gate_result.metadata.get("reminder_request"))
    else:
        suggested_path = "agent"
        is_reminder_request = False

    if not processed_by_new_gate:
        if chat_type == "private":
            logger.info('[PRIVATE] user="@%s"', label)
            trigger_reason = "private"
        else:
            # Fallback на старую систему (если новый GroupGate не инициализирован)
            from bot import group_gate as old_group_gate
            should, reason, cleaned = old_group_gate.should_process_message(
                msg,
                bot_username=_bot_username,
                trigger_words=GROUP_TRIGGER_WORDS,
                allow_reply_trigger=GROUP_ALLOW_REPLY_TRIGGER,
            )
            if not should:
                snippet = (user_text or "")[:80].replace("\n", " ")
                logger.info('[GROUP IGNORE] chat="%s" user="@%s" text="%s"', chat_title or chat_id, label, snippet)
                return
            if cleaned:
                user_text = cleaned
            trigger_reason = reason
            logger.info('[GROUP HIT] reason=%s chat="%s" user="@%s"', reason, chat_title or chat_id, label)

    # === ANTISPAM (только для групп) ===
    if chat_type in ("group", "supergroup"):
        ok, why = antispam.check_and_register(chat_id, user_id or 0)
        if not ok:
            logger.info('[ANTISPAM] reason=%s chat="%s" user="@%s"', why, chat_title or chat_id, label)
            try:
                telegram_api.send_message(chat_id, "слишком часто, дай мне пару секунд 🙏")
            except Exception:
                pass
            return

    # === QUEUE (per-chat processing flag, минимально) ===
    if not antispam.start_processing(chat_id):
        logger.info('[QUEUE] chat="%s" busy', chat_title or chat_id)
        try:
            telegram_api.send_message(chat_id, "уже отвечаю на предыдущее, добавил в очередь ⏳")
        except Exception:
            pass
        # TODO: настоящая очередь требует рефакторинга polling — пока просто пропускаем
        return

    try:
        _process_message_inner(
            msg=msg, chat_id=chat_id, chat_type=chat_type, chat_title=chat_title,
            user_id=user_id, username=username, first_name=first_name, label=label,
            user_text=user_text, text=text, caption=caption,
            trigger_reason=trigger_reason,
            suggested_path=suggested_path,
            is_reminder_request=is_reminder_request,
        )
    finally:
        antispam.stop_processing(chat_id)


def _process_message_inner(
    msg: dict,
    chat_id: int,
    chat_type: str,
    chat_title: str,
    user_id,
    username: str,
    first_name: str,
    label: str,
    user_text: str,
    text: str,
    caption: str,
    trigger_reason: str,
    suggested_path: str = "agent",   # "casual" (лёгкий путь) | "agent" (полный с инструментами)
    is_reminder_request: bool = False,
) -> None:

    # --- собираем attachments ---
    attachments: list[dict] = []

    try:
        if "photo" in msg:
            # массив фото — берём самое большое (последнее)
            photo = msg["photo"][-1]
            tg_file_id = photo["file_id"]
            logger.info("← photo chat=%s user=%s size=%s", chat_id, label, photo.get("file_size"))
            data = _download(tg_file_id)
            if data is None:
                telegram_api.send_message(chat_id, "Не получилось скачать картинку. Попробуй ещё раз.")
                return
            # Сохраняем в workspace для возможного повторного просмотра
            workspace.save_file(chat_id, "photo.jpg", data, "image/jpeg", kind="input")
            attachments.append({"type": "image", "bytes": data, "mime": "image/jpeg", "name": "photo.jpg"})
            if not user_text:
                user_text = "Что изображено на картинке?"

        elif "document" in msg:
            doc = msg["document"]
            name: str = doc.get("file_name") or "document"
            mime: str = doc.get("mime_type") or files_module.guess_mime(name)
            size: int = doc.get("file_size") or 0
            logger.info("← doc chat=%s user=%s name=%s size=%d", chat_id, label, name, size)

            if not files_module.is_allowed_input(name):
                telegram_api.send_message(
                    chat_id,
                    f"Формат файла «{name}» не поддерживается.\n"
                    "Принимаю: txt, md, csv, json, pdf, docx, xlsx, png, jpg, jpeg, webp, gif.",
                )
                return
            if size > _MAX_BYTES:
                telegram_api.send_message(
                    chat_id,
                    f"Файл слишком большой ({size // (1024*1024)} MB). Лимит: {MAX_FILE_SIZE_MB} MB.",
                )
                return

            data = _download(doc["file_id"])
            if data is None:
                telegram_api.send_message(chat_id, "Не получилось скачать файл. Попробуй ещё раз.")
                return

            if files_module.is_image(name):
                workspace.save_file(chat_id, name, data, mime, kind="input")
                attachments.append({"type": "image", "bytes": data, "mime": mime, "name": name})
                if not user_text:
                    user_text = "Что изображено на картинке?"
            else:
                meta = workspace.save_file(chat_id, name, data, mime, kind="input")
                attachments.append({"type": "document", "name": name, "file_id": meta["id"]})
                if not user_text:
                    user_text = "Прочитай этот файл и кратко расскажи что в нём."

        elif msg.get("voice") or msg.get("audio") or msg.get("video"):
            telegram_api.send_message(chat_id, "Пока не умею работать с голосом, аудио и видео. 🙈")
            return

        elif not user_text:
            return  # неподдерживаемый тип, тихо пропускаем

    except Exception as e:
        logger.exception("Ошибка при обработке вложения: %s", e)
        telegram_api.send_message(chat_id, "Что-то пошло не так при обработке файла.")
        return

    logger.info("← msg chat=%s user=%s len=%d att=%d", chat_id, label, len(user_text), len(attachments))

    # === Ранний надёжный обработчик напоминаний ===
    # Делаем так, чтобы "через 5 минут напомни..." всегда реально попадало в tasks.json
    # и потом срабатывало по таймеру. Это обходит все проблемы с моделью и routing'ом.
    if _looks_like_reminder_request(user_text) and not attachments:
        try:
            from datetime import datetime as _dt
            from bot import reminder_parser
            from bot import schedules as _sched
            from bot.storage import safe_tag as _safe_tag

            parsed = reminder_parser.parse_reminders(user_text, _dt.now())
            if parsed:
                user_tag = _safe_tag(str(chat_id)) or "user"
                created = 0
                for p in parsed:
                    _sched.add_task(
                        user_tag=user_tag,
                        chat_id=chat_id,
                        action_type="reminder",
                        repeat=p.get("repeat", "once"),
                        time_s=p.get("time"),
                        date_s=p.get("date"),
                        weekdays=p.get("weekdays"),
                        interval_seconds=p.get("interval_seconds"),
                        text=p.get("text") or user_text,
                        run_at_iso=p.get("run_at_iso"),
                    )
                    created += 1
                if created > 0:
                    logger.info("[REMINDER] early direct scheduled %d chat=%s", created, chat_id)
                    reply = "ок, поставил." if created == 1 else f"ок, поставил {created}."
                    if chat_type in ("group", "supergroup"):
                        reply = _postprocess_group_reply(reply, chat_memory)
                    else:
                        reply = sanitize_vision_denial(reply)
                    telegram_api.send_message(chat_id, reply)
                    # сохраняем в память чата
                    if chat_memory:
                        try:
                            memory.append_assistant_message(chat_memory, reply)
                            memory.trim_memory(chat_memory, MAX_HISTORY_MESSAGES_PER_CHAT)
                            memory.save_chat_memory(chat_memory)
                        except Exception:
                            pass
                    return   # важно — не идём дальше в лёгкий/тяжёлый агент
        except Exception as e:
            logger.warning("early reminder handler failed, falling through: %s", e)

    # === per-chat memory (новый слой) ===
    try:
        chat_memory = memory.load_chat_memory(chat_id, chat_type, chat_title=chat_title)
        memory.append_user_message(chat_memory, msg, user_text)
        logger.info('[MEMORY] load chat=%s msgs=%d', chat_id, len(chat_memory.get("messages", [])))
    except Exception as e:
        logger.exception("[MEMORY] load/append failed: %s", e)
        chat_memory = None

    user_context = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "chat_id": chat_id,
        "chat_title": chat_title,
        "chat_type": chat_type,
        "trigger_reason": trigger_reason,
        "reminder_request": is_reminder_request,
    }

    temp_status_ids: list[int] = []

    def _on_tool_call(name: str, args: dict) -> None:
        if chat_type not in ("group", "supergroup"):
            return
        if name == "web_search":
            query = args.get("query", "")
            if query:
                msg = f"ищу в интернете: «{query}»"
                mid = telegram_api.send_temp_status(chat_id, msg)
                if mid:
                    temp_status_ids.append(mid)

    try:
        telegram_api.send_chat_action(chat_id, "typing")

        # === Структурная маршрутизация (новая система) ===
        # Для семейных групп: если decider сказал "casual" и нет вложений — идём лёгким путём
        # (без TOOLS_SCHEMA, без тяжёлого research-промпта).
        use_light = (
            chat_type in ("group", "supergroup")
            and suggested_path == "casual"
            and not attachments
        )

        if use_light:
            logger.info("light path (casual) chat=%s user=%s", chat_id, label)
            reply = light_responder.handle_light_chat(
                chat_id=chat_id,
                user_text=user_text,
                chat_memory=chat_memory,
                user_context=user_context,
            )
            # для лёгкого пути temp-статусов и tool callbacks не бывает
        else:
            # === Надёжный прямой путь для напоминаний (решает "ок напомню, но не поставил") ===
            if is_reminder_request and not attachments:
                try:
                    from datetime import datetime as _dt
                    from bot import reminder_parser
                    from bot import schedules as _sched
                    from bot.storage import safe_tag as _safe

                    parsed = reminder_parser.parse_reminders(user_text, _dt.now())
                    if parsed:
                        user_tag = _safe(str(chat_id)) or "user"
                        created = 0
                        for p in parsed:
                            _sched.add_task(
                                user_tag=user_tag,
                                chat_id=chat_id,
                                action_type="reminder",
                                repeat=p.get("repeat", "once"),
                                time_s=p.get("time"),
                                date_s=p.get("date"),
                                weekdays=p.get("weekdays"),
                                interval_seconds=p.get("interval_seconds"),
                                text=p.get("text") or user_text,
                                run_at_iso=p.get("run_at_iso"),
                            )
                            created += 1
                        if created > 0:
                            logger.info("[REMINDER] directly scheduled %d via parser chat=%s", created, chat_id)
                            reply = "ок, поставил." if created == 1 else f"ок, поставил {created}."
                            # skip heavy agent call
                        else:
                            reply = agent.handle_message(
                                chat_id, user_text,
                                attachments=attachments if attachments else None,
                                memory_obj=chat_memory,
                                user_context=user_context,
                                tool_call_callback=_on_tool_call,
                            )
                    else:
                        reply = agent.handle_message(
                            chat_id, user_text,
                            attachments=attachments if attachments else None,
                            memory_obj=chat_memory,
                            user_context=user_context,
                            tool_call_callback=_on_tool_call,
                        )
                except Exception as _e:
                    logger.warning("direct reminder path failed: %s", _e)
                    reply = agent.handle_message(
                        chat_id, user_text,
                        attachments=attachments if attachments else None,
                        memory_obj=chat_memory,
                        user_context=user_context,
                        tool_call_callback=_on_tool_call,
                    )
            else:
                reply = agent.handle_message(
                chat_id,
                user_text,
                attachments=attachments if attachments else None,
                memory_obj=chat_memory,
                user_context=user_context,
                tool_call_callback=_on_tool_call,
            )

        if chat_type in ("group", "supergroup"):
            reply = _postprocess_group_reply(reply, chat_memory)
        else:
            # Для приватных чатов тоже защищаем от vision-denial фраз
            reply = sanitize_vision_denial(reply)

        # После пост-процесса (в т.ч. anti-repeat → [молчу])
        silent = reply.strip().lower() in {"[молчу]", "молчу", "[молчу.]"}

        # Удаляем временные статусные сообщения (что искал)
        for mid in temp_status_ids:
            try:
                telegram_api.delete_message(chat_id, mid)
            except Exception:
                pass

        if silent:
            logger.info("group: молчим (модель или anti-repeat) chat=%s", chat_id)
        else:
            telegram_api.send_message(chat_id, reply)
            logger.info("→ chat=%s len=%d", chat_id, len(reply))

            # сохраняем ответ в per-chat memory + trim
            if chat_memory is not None:
                try:
                    memory.append_assistant_message(chat_memory, reply)
                    memory.trim_memory(chat_memory, MAX_HISTORY_MESSAGES_PER_CHAT)
                    memory.save_chat_memory(chat_memory)
                    logger.info('[MEMORY] saved chat=%s msgs=%d', chat_id, len(chat_memory.get("messages", [])))
                except Exception as e:
                    logger.exception("[MEMORY] save failed: %s", e)
    except Exception as e:
        logger.exception("Ошибка в agent.handle_message: %s", e)
        try:
            telegram_api.send_message(chat_id, "Что-то пошло не так. Попробуй ещё раз.")
        except Exception:
            pass


def run() -> None:
    config.validate()
    _bot_username = config.BOT_USERNAME
    me = telegram_api.get_me()
    if me:
        uname = (me.get("username") or "").strip()
        if uname:
            _bot_username = uname

    # === Инициализация нового Group Gate + LLM Decision Layer ===
    global _group_gate
    try:
        gate_config = GroupGateConfig(
            chat_id=0,
            owner_id=config.OWNER_USER_ID,
            vip_user_id=config.VIP_USER_ID or None,
            trusted_user_ids=set(),
            interest_keywords=list(config.GROUP_INTEREST_KEYWORDS),
            enable_proactive_mode=config.GROUP_PROACTIVE_MODE,
        )
        gate_config.extra["bot_username"] = _bot_username

        # === Главное улучшение: GLM решает, отвечать ли ===
        # Каждое сообщение в proactive-группах проходит через дешёвый GLM
        # для принятия решения "стоит ли Мистеру Батону ответить?"
        response_decider = None
        if config.GROUP_PROACTIVE_MODE:
            try:
                response_decider = LLMResponseDecider(
                    model=config.OPENAI_MODEL,   # обычно glm-4.5-flash
                    temperature=0.65,
                    max_tokens=50,
                )
                logger.info("LLM Response Decider (GLM) включён — бот будет более живым")
            except Exception as e:
                logger.warning("Не удалось создать LLMResponseDecider: %s", e)

        _group_gate = GroupGate(gate_config, response_decider=response_decider)
        logger.info("GroupGate инициализирован (новая система + LLM decider)")

    except Exception as e:
        logger.exception("Не удалось инициализировать GroupGate: %s", e)
        _group_gate = None

    # Определяем дефолтное поведение
    if config.OPENAI_API_KEY and config.OPENAI_BASE_URL:
        fast = f"GLM ({config.OPENAI_MODEL})"
    else:
        fast = config.OPENAI_MODEL or "не настроено"

    vision = config.OPENAI_VISION_MODEL or "не настроено"
    default_model = f"Fast: {fast} | Vision: {vision}"

    logger.info("Бот @%s готов. Дефолт: %s", _bot_username, default_model)

    # TTL cleanup при старте
    deleted = workspace.cleanup_old()
    if deleted:
        logger.info("Startup cleanup: удалено %d устаревших файлов", deleted)

    # Запускаем фоновый scheduler
    scheduler.start()
    logger.info("Scheduler запущен")

    offset: int | None = None
    backoff = 1
    logger.info("Long polling запущен")

    while True:
        try:
            updates = telegram_api.get_updates(offset=offset, timeout=30)
            backoff = 1
            for upd in updates:
                offset = upd["update_id"] + 1
                _process_update(upd)
        except KeyboardInterrupt:
            logger.info("Остановка по Ctrl+C")
            return
        except Exception as e:
            logger.exception("Ошибка polling-цикла: %s", e)
            time.sleep(min(backoff, 30))
            backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    try:
        run()
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
