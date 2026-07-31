from __future__ import annotations
import json
import re
from typing import Any
from bot import files as files_module, notebook, telegram_api, web_search, workspace, schedules
from bot.config import WEB_SEARCH_RESULTS_LIMIT, WEB_SEARCH_RESULTS_LIMIT_DOC, DATA_DIR
from bot.logger import get_logger
from bot.storage import safe_tag

logger = get_logger("tools")

# YouTube URL pattern
_YT_URL_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.?be)/(watch\?v=|shorts/|v/)?([A-Za-z0-9_-]{11})",
    re.IGNORECASE
)

TOOLS_SCHEMA = [
    {"name": "web_search", "description": f"Поиск свежей информации в интернете. ВАЖНО: формулируй запрос максимально нейтрально и точно. НЕ добавляй в запрос имена гонщиков, команды или предположения (например, не пиши 'Lewis Hamilton Max Verstappen' если пользователь просто спросил кто победил). Делай запрос прямым: 'победитель Формулы 1 2026', 'чемпионат мира F1 2026 пилот чемпион'. НЕ используй для общих знаний. КАТЕГОРИЧЕСКИ НЕ используй для вопросов про текущее время. Лимит по умолчанию {WEB_SEARCH_RESULTS_LIMIT}.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "description": f"Количество результатов. По умолчанию {WEB_SEARCH_RESULTS_LIMIT}."}}, "required": ["query"]}},
    {"name": "notebook_read", "description": "Прочитать личный блокнот пользователя.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}},
    {"name": "notebook_write", "description": "Сохранить заметку. Только по явной просьбе.", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "save_note", "description": "Сохранить заметку. Псевдоним для notebook_write — используй этот tool когда пользователь просит сохранить информацию.", "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "read_notes", "description": "Прочитать все заметки из блокнота.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}},
    {"name": "search_notes", "description": "Поиск по заметкам по ключевым словам.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}},
    {"name": "list_files", "description": "Список файлов в workspace пользователя.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "read_file", "description": "Прочитать файл из workspace (txt, md, csv, json, pdf, docx, xlsx).", "input_schema": {"type": "object", "properties": {"file_id": {"type": "string", "description": "ID или имя файла"}}, "required": ["file_id"]}},
    {"name": "create_file", "description": "Создать файл и отправить пользователю. Форматы: txt, md, csv, json, docx, xlsx, pptx. Для docx — markdown (# заголовки, - списки). Для xlsx — csv. Для pptx — слайды разделяются '\\n---\\n', каждый слайд начинается с '# Заголовок', затем контент (- пункты).", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "content": {"type": "string"}, "caption": {"type": "string"}}, "required": ["name", "content"]}},
    {"name": "edit_file", "description": "Отредактировать файл из workspace и отправить новую версию.", "input_schema": {"type": "object", "properties": {"file_id": {"type": "string"}, "new_content": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["file_id", "new_content"]}},
    {"name": "create_reminder", "description": "Создать напоминание. Параметры: time (строка времени, ЧЧ:ММ или 'через N минут/часов', 'каждый день в ЧЧ:ММ', 'завтра в ЧЧ:ММ', 'в YYYY-MM-DD в ЧЧ:ММ'), text (текст напоминания), repeat (once/daily/interval/weekly по умолчанию daily), interval_seconds (для interval, сек), weekdays (список 0-6 для weekly).", "input_schema": {"type": "object", "properties": {"time": {"type": "string"}, "text": {"type": "string"}, "repeat": {"type": "string"}, "interval_seconds": {"type": "integer"}, "weekdays": {"type": "array", "items": {"type": "integer"}}, "date": {"type": "string"}, "run_at_iso": {"type": "string"}}, "required": ["time", "text"]}},
    {"name": "list_reminders", "description": "Показать список всех напоминаний пользователя.", "input_schema": {"type": "object", "properties": {}, "required": []}},
    {"name": "delete_reminder", "description": "Удалить напоминание по ID. ID можно получить через list_reminders.", "input_schema": {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]}},
    {"name": "edit_reminder", "description": "Редактировать существующее напоминание. Можно менять текст, время, тип повторения (repeat), дни недели (weekdays) и т.д. ID берётся из list_reminders.", "input_schema": {"type": "object", "properties": {"reminder_id": {"type": "integer"}, "text": {"type": "string"}, "time": {"type": "string", "description": "HH:MM"}, "repeat": {"type": "string", "enum": ["once", "daily", "weekly", "interval"]}, "weekdays": {"type": "array", "items": {"type": "integer"}}, "interval_seconds": {"type": "integer"}, "date": {"type": "string", "description": "YYYY-MM-DD для одноразовых"}}, "required": ["reminder_id"]}},
    {"name": "analyze_youtube", "description": "Проанализировать видео на YouTube. Принимает YouTube URL. Возвращает title, channel, duration, description. Если есть субтитры — очищенный текст. Без скачивания видео.", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
]

def dispatch(name, tool_input, chat_id):
    logger.info("tool call: %s args=%s", name, _short(tool_input))
    try:
        return _dispatch(name, tool_input, chat_id)
    except Exception as e:
        logger.exception("tool %s crashed: %s", name, e)
        return _r({"error": f"{e.__class__.__name__}: {e}"})

def _dispatch(name, tool_input, chat_id):
    if name == "web_search":
        q = str(tool_input.get("query", "")).strip()
        raw = tool_input.get("limit")
        limit = int(raw) if isinstance(raw, (int, float)) else WEB_SEARCH_RESULTS_LIMIT
        return _r(web_search.search(q, limit))
    if name == "notebook_read":
        # Read the user's notebook.  Uses per‑user notebooks to avoid
        # mixing notes between chats.  Supports optional substring query.
        user_tag = safe_tag(str(chat_id)) or "user"
        q = tool_input.get("query")
        query = q if isinstance(q, str) else None
        notes = notebook.list_notes_for_user(user_tag, query)
        return _r({"count": len(notes), "notes": notes})
    if name == "notebook_write":
        # Append a note to the user's notebook.  Reject empty text.
        text = str(tool_input.get("text", "")).strip()
        if not text:
            return _r({"error": "Пустой текст"})
        user_tag = safe_tag(str(chat_id)) or "user"
        note = notebook.add_note_for_user(user_tag, text)
        return _r({"saved": True, "note": note})
    if name == "save_note":
        # Alias for notebook_write.  Save a note in the user's notebook.
        text = str(tool_input.get("text", "")).strip()
        if not text:
            return _r({"error": "Пустой текст"})
        user_tag = safe_tag(str(chat_id)) or "user"
        note = notebook.add_note_for_user(user_tag, text)
        return _r({"saved": True, "note": note})
    if name == "read_notes":
        # Legacy: read notes from the user's notebook.
        user_tag = safe_tag(str(chat_id)) or "user"
        q = tool_input.get("query")
        query = q if isinstance(q, str) else None
        notes = notebook.list_notes_for_user(user_tag, query)
        return _r({"count": len(notes), "notes": notes})
    if name == "search_notes":
        # Legacy search for notes by substring.  Uses per‑user notebooks.
        user_tag = safe_tag(str(chat_id)) or "user"
        q = tool_input.get("query")
        query = q if isinstance(q, str) else None
        all_notes = notebook.list_notes_for_user(user_tag)
        if query:
            qs = query.lower()
            filtered = [n for n in all_notes if qs in (n.get("text") or "").lower()]
        else:
            filtered = all_notes
        return _r({"count": len(filtered), "notes": filtered})
    if name == "list_files":
        flist = workspace.list_files(chat_id)
        return _r({"count": len(flist), "files": [{"id": f["id"], "name": f["name"], "size_kb": round(f["size"]/1024,1), "kind": f["kind"]} for f in flist]})
    if name == "read_file":
        ref = str(tool_input.get("file_id", "")).strip()
        meta = workspace.find_file(chat_id, ref)
        if not meta: return _r({"error": f"Файл {ref!r} не найден. Используй list_files."})
        if files_module.is_image(meta["name"]): return _r({"error": "Изображение читается через vision."})
        text = files_module.extract_text(meta["path"])
        return _r({"name": meta["name"], "size_kb": round(meta["size"]/1024,1), "content": text})
    if name == "create_file":
        name_arg = str(tool_input.get("name", "")).strip()
        content = str(tool_input.get("content", ""))
        caption = tool_input.get("caption")
        if not name_arg or not content: return _r({"error": "Нужны name и content"})
        try: file_bytes, mime = files_module.generate_file(name_arg, content)
        except ValueError as e: return _r({"error": str(e)})
        meta = workspace.save_file(chat_id, name_arg, file_bytes, mime, kind="output")
        telegram_api.send_chat_action(int(chat_id), "upload_document")
        telegram_api.send_document(int(chat_id), file_bytes, name_arg, caption=str(caption) if caption else None)
        return _r({"sent": True, "file_id": meta["id"], "name": name_arg, "size_kb": round(len(file_bytes)/1024,1)})
    if name == "edit_file":
        ref = str(tool_input.get("file_id", "")).strip()
        new_content = str(tool_input.get("new_content", ""))
        new_name = tool_input.get("new_name")
        meta = workspace.find_file(chat_id, ref)
        if not meta: return _r({"error": f"Файл {ref!r} не найден."})
        out_name = str(new_name).strip() if new_name else meta["name"]
        try: file_bytes, mime = files_module.generate_file(out_name, new_content)
        except ValueError as e: return _r({"error": str(e)})
        new_meta = workspace.save_file(chat_id, out_name, file_bytes, mime, kind="output")
        telegram_api.send_chat_action(int(chat_id), "upload_document")
        telegram_api.send_document(int(chat_id), file_bytes, out_name, caption="Отредактировано")
        return _r({"sent": True, "file_id": new_meta["id"], "name": out_name})
    if name == "create_reminder":
        time_s = str(tool_input.get("time", "")).strip()
        text = str(tool_input.get("text", "")).strip()
        repeat = str(tool_input.get("repeat", "")).strip() or "daily"
        interval_sec = tool_input.get("interval_seconds")
        weekdays = tool_input.get("weekdays")
        date_s = tool_input.get("date", "").strip()
        run_at_iso = tool_input.get("run_at_iso", "").strip()
        user_tag = safe_tag(str(chat_id))
        if not time_s or not text:
            return _r({"error": "Нужны time и text"})
        try:
            task = schedules.add_task(
                user_tag=user_tag,
                chat_id=int(chat_id),
                text=text,
                repeat=repeat,
                time_s=time_s if repeat in ("once", "daily", "weekly") else None,
                date_s=date_s if repeat == "once" else None,
                interval_seconds=int(interval_sec) if interval_sec else None,
                weekdays=weekdays,
                action_type="reminder",
                run_at_iso=run_at_iso if repeat == "once" else None,
            )
            return _r({
                "success": True,
                "id": task.get("id"),
                "text": task.get("text"),
                "repeat": task.get("repeat"),
                "time": task.get("time"),
                "next_run_at": task.get("next_run_at"),
            })
        except Exception as e:
            return _r({"error": f"Ошибка создания напоминания: {e}"})
    if name == "list_reminders":
        user_tag = safe_tag(str(chat_id))
        tasks = schedules.list_tasks(user_tag)
        if not tasks:
            return _r({"count": 0, "tasks": []})
        result = []
        for t in tasks:
            result.append({
                "id": t.get("id"),
                "text": t.get("text"),
                "repeat": t.get("repeat"),
                "time": t.get("time"),
                "date": t.get("date"),
                "next_run_at": t.get("next_run_at"),
            })
        return _r({"count": len(result), "tasks": result})
    if name == "delete_reminder":
        reminder_id = tool_input.get("reminder_id")
        if reminder_id is None:
            return _r({"error": "Нужен reminder_id"})
        user_tag = safe_tag(str(chat_id))
        if schedules.remove_task(user_tag, int(reminder_id)):
            return _r({"success": True, "deleted_id": reminder_id})
        return _r({"error": "Напоминание не найдено"})

    if name == "edit_reminder":
        reminder_id = tool_input.get("reminder_id")
        if reminder_id is None:
            return _r({"error": "Нужен reminder_id"})

        updates = {}
        if "text" in tool_input:
            updates["text"] = str(tool_input["text"]).strip()
        if "time" in tool_input:
            updates["time"] = str(tool_input["time"]).strip()
        if "repeat" in tool_input:
            updates["repeat"] = str(tool_input["repeat"]).strip()
        if "weekdays" in tool_input:
            updates["weekdays"] = tool_input["weekdays"]
        if "interval_seconds" in tool_input:
            updates["interval_seconds"] = int(tool_input["interval_seconds"])
        if "date" in tool_input:
            updates["date"] = str(tool_input["date"]).strip()

        if not updates:
            return _r({"error": "Нужно передать хотя бы одно поле для изменения (text, time, repeat и т.д.)"})

        user_tag = safe_tag(str(chat_id))
        updated = schedules.edit_task(user_tag, int(reminder_id), **updates)
        if updated:
            return _r({
                "success": True,
                "id": updated.get("id"),
                "text": updated.get("text"),
                "next_run_at": updated.get("next_run_at"),
            })
        return _r({"error": "Напоминание не найдено или не удалось обновить"})
    if name == "analyze_youtube":
        url = str(tool_input.get("url", "")).strip()
        if not url:
            return _r({"error": "Нужен URL видео"})
        # Нормализуем URL
        match = _YT_URL_PATTERN.search(url)
        if not match:
            return _r({"error": "Неверный формат YouTube URL"})
        video_id = match.group(5)
        if not video_id:
            return _r({"error": "Не удалось извлечь video_id"})
        try:
            import yt_dlp
        except ImportError:
            return _r({"error": "yt-dlp не установлен. Установи: pip install yt-dlp"})
        result = {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}"}
        try:
            ydl_opts = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": False,
                "skip_download": True,
                "writeautomaticsub": True,
                "subtitleslangs": ["en", "ru"],
                "subtitlesformat": "srt",
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
                result["title"] = info.get("title", "")
                result["channel"] = info.get("channel", "")
                result["duration"] = info.get("duration", 0)
                result["description"] = info.get("description", "")[:1000] if info.get("description") else ""
                # Попытка получить субтитры
                subtitles = info.get("subtitles")
                auto_subs = info.get("automatic_subtitles", {})
                all_subs = {}
                if subtitles:
                    for lang, subs_data in subtitles.items():
                        if subs_data:
                            all_subs[lang] = subs_data
                if auto_subs:
                    for lang, subs_data in auto_subs.items():
                        if subs_data:
                            all_subs[lang] = subs_data
                if all_subs:
                    result["has_subtitles"] = True
                    # Берем первый доступный субтитр
                    for lang, subs_data in all_subs.items():
                        if subs_data and subs_data[0]:
                            try:
                                result["subtitle_text"] = subs_data[0].get("subtitles", "")
                            except Exception:
                                pass
                            break
                else:
                    result["has_subtitles"] = False
        except ImportError:
            return _r({"error": "yt-dlp не установлен"})
        except Exception as e:
            return _r({"error": f"Ошибка анализа видео: {e}"})
        return _r(result)

    return _r({"error": f"Unknown tool: {name}"})

def _r(payload): return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
def _short(data, n=120):
    s = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return s if len(s) <= n else s[:n] + "..."
