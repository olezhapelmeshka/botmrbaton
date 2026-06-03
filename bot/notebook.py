"""
Блокнот заметок — простое JSON‑хранилище.

По умолчанию раньше существовал один общий блокнот (``NOTEBOOK_FILE``).
Для соответствия новым требованиям каждый пользователь или группа теперь
имеет собственный блокнот в директории ``DATA_DIR/<user_tag>/`` под
именем ``notebook.json``.  Функции в этом модуле работают и в новом,
многопользовательском режиме (через *user_tag*) и, для обратной
совместимости, на глобальном файле, если *user_tag* не указан.

Структура файла: ``{"next_id": int, "notes": [{id, text, created_at}, ...]}``.
"""

from __future__ import annotations

from typing import Any
from pathlib import Path
import time

from bot.config import NOTEBOOK_FILE, DATA_DIR
from bot.utils import load_json, save_json
from bot.storage import safe_tag

# For logging summarisation and note operations
from bot.logger import get_logger

_logger = get_logger("notebook")


def _empty() -> dict[str, Any]:
    """Return a new empty notebook structure."""
    return {"next_id": 1, "notes": []}


def _load_global() -> dict[str, Any]:
    """
    Load the global notebook file.  This is retained for backward
    compatibility but should not be used for per‑user notebooks.
    """
    data = load_json(NOTEBOOK_FILE, _empty())
    if not isinstance(data, dict) or "notes" not in data:
        return _empty()
    return data


def _save_global(data: dict[str, Any]) -> None:
    """Persist the global notebook data."""
    save_json(NOTEBOOK_FILE, data)


def _path_for_user(user_tag: str) -> Path:
    """Return the path to the notebook for the given user tag."""
    tag = safe_tag(user_tag) or "user"
    return (DATA_DIR / tag / "notebook.json")


def _load_user(user_tag: str) -> dict[str, Any]:
    """Load a per‑user notebook, creating an empty one on failure."""
    path = _path_for_user(user_tag)
    try:
        data = load_json(path, None)
        if isinstance(data, dict) and isinstance(data.get("notes"), list):
            return data
    except Exception as e:  # pragma: no cover
        _logger.warning("failed to load notebook %s: %s", path, e)
    return _empty()


def _save_user(user_tag: str, data: dict[str, Any]) -> None:
    """Save a per‑user notebook."""
    path = _path_for_user(user_tag)
    # ensure parent directory exists
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, data)
    except Exception as e:  # pragma: no cover
        _logger.warning("failed to save notebook %s: %s", path, e)


def add_note_for_user(user_tag: str, text: str) -> dict[str, Any]:
    """
    Append a new note to the notebook for ``user_tag``.  Whitespace is
    stripped and empty notes are not allowed.  The returned dict
    contains the note ``id``, ``text`` and ``created_at`` timestamp.
    """
    if not text or not str(text).strip():
        raise ValueError("Пустая заметка")
    text = str(text).strip()
    data = _load_user(user_tag)
    note = {
        "id": data.get("next_id", 1),
        "text": text,
        "created_at": int(time.time()),
    }
    data["next_id"] = int(data.get("next_id", 1)) + 1
    notes = data.setdefault("notes", [])
    notes.append(note)
    _save_user(user_tag, data)
    return note


def list_notes_for_user(user_tag: str, query: str | None = None) -> list[dict[str, Any]]:
    """
    Return a list of notes for ``user_tag``.  If ``query`` is provided
    (case‑insensitive substring), only notes whose text contains
    ``query`` are returned.
    """
    data = _load_user(user_tag)
    notes = list(data.get("notes", []))
    if query:
        q = query.lower().strip()
        notes = [n for n in notes if q in (n.get("text") or "").lower()]
    return notes


def delete_note_for_user(user_tag: str, note_id: int) -> bool:
    """Delete a note by id for the given user tag.  Returns True if deleted."""
    data = _load_user(user_tag)
    notes = list(data.get("notes", []))
    before = len(notes)
    notes = [n for n in notes if int(n.get("id", -1)) != int(note_id)]
    if len(notes) == before:
        return False
    data["notes"] = notes
    _save_user(user_tag, data)
    return True


def count_for_user(user_tag: str) -> int:
    """Return the number of notes for a given user tag."""
    return len(_load_user(user_tag).get("notes", []))


# ---------------------------------------------------------------------------
# Legacy global API
# ---------------------------------------------------------------------------
def add_note(text: str) -> dict[str, Any]:  # pragma: no cover
    """
    Legacy function to add a note to the global notebook.  Prefer
    ``add_note_for_user`` when possible.  This simply delegates to
    ``add_note_for_user`` with a fixed tag of ``"global"``.
    """
    return add_note_for_user("global", text)


def list_notes(query: str | None = None) -> list[dict[str, Any]]:  # pragma: no cover
    """Legacy: list notes from the global notebook."""
    return list_notes_for_user("global", query)


def delete_note(note_id: int) -> bool:  # pragma: no cover
    """Legacy: delete a note in the global notebook."""
    return delete_note_for_user("global", note_id)


def count() -> int:  # pragma: no cover
    """Legacy: count notes in the global notebook."""
    return count_for_user("global")
