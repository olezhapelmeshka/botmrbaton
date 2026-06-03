"""
История диалогов по chat_id.

Хранится как list[ {role, content} ] в формате, который принимает
Anthropic Messages API. content может быть строкой или списком блоков
(text / tool_use / tool_result), поэтому при сериализации в JSON
SDK-объекты конвертируем в dict.

Обрезка: считаем «раунд» = последовательность сообщений до финального
ответа ассистента (без tool_use). Храним последние HISTORY_ROUNDS раундов.
Это гарантирует, что мы не разорвём пару tool_use → tool_result, иначе
Claude вернёт 400.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bot.config import HISTORY_ROUNDS, MEMORY_DIR, MEMORY_FILE
from bot.utils import load_json, save_json


# in-memory кеш, чтобы не дёргать диск каждый ход
_cache: dict[str, list[dict[str, Any]]] = {}
_loaded = False


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    raw = load_json(MEMORY_FILE, {})
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, list):
                _cache[str(k)] = v
    _loaded = True


def _persist() -> None:
    save_json(MEMORY_FILE, _cache)


def _block_to_dict(block: Any) -> Any:
    """SDK-объекты Anthropic → dict для JSON."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    if isinstance(block, dict):
        return block
    return block


def get(chat_id: int | str) -> list[dict[str, Any]]:
    _ensure_loaded()
    return list(_cache.get(str(chat_id), []))


def append_user(chat_id: int | str, content: "str | list[dict[str, Any]]") -> None:
    """
    Добавить user-сообщение в историю.
    content: str — обычный текст.
    content: list[dict] — multimodal блоки (text + image placeholders).
    Base64-данные сюда НЕ передавать — только плейсхолдеры.
    """
    _ensure_loaded()
    key = str(chat_id)
    _cache.setdefault(key, []).append({"role": "user", "content": content})
    _persist()


def append_assistant(chat_id: int | str, content_blocks: list[Any]) -> None:
    _ensure_loaded()
    key = str(chat_id)
    _cache.setdefault(key, []).append(
        {"role": "assistant", "content": [_block_to_dict(b) for b in content_blocks]}
    )
    _persist()


def append_tool_results(chat_id: int | str, tool_results: list[dict[str, Any]]) -> None:
    _ensure_loaded()
    key = str(chat_id)
    _cache.setdefault(key, []).append({"role": "user", "content": tool_results})
    _persist()


def reset(chat_id: int | str) -> None:
    _ensure_loaded()
    _cache.pop(str(chat_id), None)
    _persist()


def trim(chat_id: int | str) -> None:
    """Обрезаем историю до последних HISTORY_ROUNDS раундов."""
    _ensure_loaded()
    key = str(chat_id)
    msgs = _cache.get(key)
    if not msgs:
        return

    # Разрезаем на раунды по «финальному» ответу ассистента
    rounds: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for msg in msgs:
        current.append(msg)
        if msg["role"] == "assistant" and _is_final_assistant(msg):
            rounds.append(current)
            current = []
    if current:
        # незакрытый раунд — оставляем как есть в конце
        rounds.append(current)

    if len(rounds) > HISTORY_ROUNDS:
        rounds = rounds[-HISTORY_ROUNDS:]

    _cache[key] = [m for r in rounds for m in r]
    _persist()


def _is_final_assistant(msg: dict[str, Any]) -> bool:
    content = msg.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
            if btype == "tool_use":
                return False
        return True
    return True


def stats(chat_id: int | str) -> int:
    return len(get(chat_id))


# =====================================================================
# Per-chat memory (groups + private), parallel API.
# Не ломает существующие функции выше — просто дополнительный слой.
# Файлы: data/memory/private_<chat_id>.json и group_<chat_id>.json
# =====================================================================


def _safe_chat_id(chat_id: int | str) -> str:
    return str(chat_id).replace("/", "_").replace("\\", "_")


def get_memory_path(chat_id: int | str, chat_type: str) -> Path:
    prefix = "group" if chat_type in ("group", "supergroup") else "private"
    return MEMORY_DIR / f"{prefix}_{_safe_chat_id(chat_id)}.json"


def _empty_memory(chat_id: int | str, chat_type: str, chat_title: str | None) -> dict[str, Any]:
    return {
        "chat_id": str(chat_id),
        "chat_title": chat_title or "",
        "chat_type": chat_type or "",
        "summary": "",
        "facts": [],
        "messages": [],
    }


def load_chat_memory(
    chat_id: int | str,
    chat_type: str,
    chat_title: str | None = None,
) -> dict[str, Any]:
    path = get_memory_path(chat_id, chat_type)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    data = load_json(path, None)
    if not isinstance(data, dict):
        return _empty_memory(chat_id, chat_type, chat_title)
    # подтягиваем недостающие поля + актуализируем title
    base = _empty_memory(chat_id, chat_type, chat_title)
    base.update({k: v for k, v in data.items() if v is not None})
    if chat_title:
        base["chat_title"] = chat_title
    base["chat_type"] = chat_type or base.get("chat_type", "")
    base["chat_id"] = str(chat_id)
    base.setdefault("messages", [])
    base.setdefault("facts", [])
    base.setdefault("summary", "")
    return base


def save_chat_memory(memory_obj: dict[str, Any]) -> None:
    if not memory_obj:
        return
    chat_id = memory_obj.get("chat_id")
    chat_type = memory_obj.get("chat_type") or "private"
    if not chat_id:
        return
    path = get_memory_path(chat_id, chat_type)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    save_json(path, memory_obj)


def append_user_message(
    memory_obj: dict[str, Any],
    message: dict | None,
    cleaned_text: str,
) -> None:
    if memory_obj is None:
        return
    user = (message or {}).get("from") or {}
    entry = {
        "role": "user",
        "user_id": user.get("id"),
        "username": user.get("username") or "",
        "first_name": user.get("first_name") or "",
        "text": cleaned_text or "",
        "ts": (message or {}).get("date"),
    }
    memory_obj.setdefault("messages", []).append(entry)


def append_assistant_message(memory_obj: dict[str, Any], text: str) -> None:
    if memory_obj is None:
        return
    memory_obj.setdefault("messages", []).append({
        "role": "assistant",
        "text": text or "",
    })


def summarize_old_messages(old_messages: list[dict[str, Any]]) -> str:
    """
    Локальная (без вызова модели) сжимающая сводка.
    Просто склеиваем последние строки в коротком виде.
    """
    if not old_messages:
        return ""
    lines: list[str] = []
    for m in old_messages:
        role = m.get("role", "?")
        if role == "user":
            who = m.get("username") or m.get("first_name") or "user"
            txt = (m.get("text") or "").strip().replace("\n", " ")
            if len(txt) > 200:
                txt = txt[:200] + "…"
            lines.append(f"- {who}: {txt}")
        elif role == "assistant":
            txt = (m.get("text") or "").strip().replace("\n", " ")
            if len(txt) > 200:
                txt = txt[:200] + "…"
            lines.append(f"- bot: {txt}")
    summary = "\n".join(lines)
    if len(summary) > 4000:
        summary = summary[-4000:]
    return summary


def trim_memory(memory_obj: dict[str, Any], max_messages: int) -> None:
    if not memory_obj:
        return
    msgs = memory_obj.get("messages") or []
    if len(msgs) <= max_messages:
        return
    overflow = msgs[: len(msgs) - max_messages]
    keep = msgs[-max_messages:]
    add_summary = summarize_old_messages(overflow)
    if add_summary:
        prev = memory_obj.get("summary") or ""
        merged = (prev + "\n" + add_summary).strip() if prev else add_summary
        if len(merged) > 6000:
            merged = merged[-6000:]
        memory_obj["summary"] = merged
    memory_obj["messages"] = keep


def reset_chat_memory(chat_id: int | str, chat_type: str) -> bool:
    """Удалить per-chat memory файл. True если был."""
    path = get_memory_path(chat_id, chat_type)
    if path.exists():
        try:
            path.unlink()
            return True
        except Exception:
            return False
    return False
