"""
chat_history
~~~~~~~~~~~~~~~~~

Per‑chat conversation history management.  Each chat (user or group) gets
its own folder under the global ``DATA_DIR`` (see ``bot.config``).  Within
that folder we store a JSON file named ``history.json`` containing a list
of message dictionaries.  Each entry has at minimum the keys ``role``
(either ``"user"`` or ``"assistant"``), ``text`` (the message text) and
``ts`` (an integer timestamp).

The primary entry point is ``add_message()`` which records a new message
and automatically triggers summarisation when the total number of stored
messages exceeds a threshold.  When summarising, the oldest messages
except for the most recent few are condensed into a short free‑form
summary and appended to the chat's notebook via ``bot.notebook``.  The
history is then trimmed down to keep only the most recent messages.

The purpose of this module is to satisfy the requirement that every chat
maintains its own persisted history and notebook while keeping the
internal memory used by the LLM separate.  Users can later inspect
``history.json`` and ``notebook.json`` in their personal folder.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from bot.config import DATA_DIR
from bot.logger import get_logger
from bot.storage import safe_tag


logger = get_logger("chat_history")

# Threshold after which a history summary is created and the history is
# truncated.  Once the number of messages exceeds this threshold, the
# oldest messages (all but the most recent ``KEEP_LAST`` entries) are
# summarised and removed.
SUMMARY_THRESHOLD = 20

# How many of the most recent messages to keep after summarisation.
KEEP_LAST = 5


def _chat_dir(tag: str) -> Path:
    """Return the Path for a chat's directory, creating it if necessary."""
    d = DATA_DIR / safe_tag(tag)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _history_path(tag: str) -> Path:
    """Return the Path to the history JSON file for this chat."""
    return _chat_dir(tag) / "history.json"


def _load_history(tag: str) -> dict[str, Any]:
    """Read the history JSON, returning an empty structure on failure."""
    path = _history_path(tag)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("messages"), list):
            return data
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("failed to load history %s: %s", path, e)
    return {"messages": []}


def _save_history(tag: str, data: dict[str, Any]) -> None:
    """Persist the history JSON to disk."""
    path = _history_path(tag)
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("failed to save history %s: %s", path, e)


def _summarise(messages: Iterable[dict[str, Any]]) -> str:
    """
    Generate a brief summary of a sequence of messages.  Each message is
    expected to be a dict containing at least ``role`` and ``text``.  The
    summary is a simple concatenation of the messages in human readable
    form.  This is intentionally lightweight; for more sophisticated
    summarisation the model itself should be used via a tool.
    """
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        text = (m.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        # limit length of each fragment
        if len(text) > 200:
            text = text[:200] + "…"
        prefix = "user" if role == "user" else "bot"
        lines.append(f"- {prefix}: {text}")
    summary = "\n".join(lines)
    # Cap the overall summary length to avoid runaway sizes
    if len(summary) > 4000:
        summary = summary[-4000:]
    return summary


def add_message(tag: str, role: str, text: str) -> None:
    """
    Append a new message to the history for ``tag``.  The ``role`` should
    be ``"user"`` or ``"assistant"`` and ``text`` is the content.  A
    timestamp is recorded automatically.  When the history exceeds
    ``SUMMARY_THRESHOLD`` entries, the oldest messages are summarised and
    appended to the chat's notebook.  The history file will then keep
    only the last ``KEEP_LAST`` messages.
    """
    tag = safe_tag(tag) or "user"
    data = _load_history(tag)
    msgs: list[dict[str, Any]] = data.get("messages", [])
    # normalise role to canonical names
    if role not in {"user", "assistant"}:
        role = "user" if role == "human" else "assistant"
    msgs.append({"role": role, "text": text or "", "ts": int(time.time())})

    # If threshold reached, summarise
    if len(msgs) > SUMMARY_THRESHOLD:
        to_sum = msgs[:-KEEP_LAST]
        to_keep = msgs[-KEEP_LAST:]
        summary = _summarise(to_sum)
        if summary:
            try:
                # import lazily to avoid circular import
                from bot import notebook as nb  # type: ignore
                nb.add_note_for_user(tag, summary)
            except Exception as e:
                logger.warning("failed to append summary to notebook for %s: %s", tag, e)
        msgs = to_keep
    data["messages"] = msgs
    _save_history(tag, data)


def get_messages(tag: str) -> list[dict[str, Any]]:
    """Return the list of messages for this chat."""
    return list(_load_history(tag).get("messages", []))


def clear(tag: str) -> None:
    """Remove the entire history for the given chat."""
    path = _history_path(tag)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.warning("failed to delete history %s: %s", path, e)


def list_chat_tags() -> list[str]:
    """
    Enumerate all chat directories under ``DATA_DIR`` that appear to
    contain a history file.  This is used by the scheduler to know which
    chats have tasks or histories.  Folders belonging to other
    subsystems (memory, schedules, files, etc.) are ignored.
    """
    tags: list[str] = []
    for p in DATA_DIR.iterdir():
        if not p.is_dir():
            continue
        # skip internal directories
        if p.name in {"memory", "files", "schedules", "interests"}:
            continue
        hist = p / "history.json"
        if hist.exists():
            tags.append(p.name)
    return tags