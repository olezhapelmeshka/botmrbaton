"""
Workspace per chat_id.

Каждый чат имеет свою папку data/files/{chat_id}/ и набор метаданных
в data/workspace.json. Файл на диске лежит как `{file_id}__{safe_name}`
чтобы избежать коллизий имён.

Метаданные:
{
  "{chat_id}": {
    "files": {
      "{file_id}": {id, name, path, mime, size, created_at, kind}
    }
  }
}

kind = "input"  — пользователь прислал
kind = "output" — бот сгенерировал

TTL cleanup удаляет файлы старше WORKSPACE_TTL_HOURS.
"""

from __future__ import annotations

import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from bot.config import DATA_DIR, WORKSPACE_DIR, WORKSPACE_META, WORKSPACE_TTL_HOURS
from bot.storage import safe_tag
from bot.logger import get_logger
from bot.utils import load_json, save_json


logger = get_logger("workspace")


# ---------- low-level ----------

def _load_meta(chat_id: int | str) -> dict[str, Any]:
    """
    Load workspace metadata for a given chat.  Each chat now has its own
    metadata file located at ``DATA_DIR/<tag>/workspace.json``.  If the
    metadata file does not exist or cannot be parsed, returns an
    empty structure.
    """
    tag = safe_tag(str(chat_id))
    if not tag:
        return {}
    meta_path = DATA_DIR / tag / "workspace.json"
    data = load_json(meta_path, None)
    return data if isinstance(data, dict) else {}


def _save_meta(chat_id: int | str, data: dict[str, Any]) -> None:
    """
    Persist workspace metadata for a given chat to ``DATA_DIR/<tag>/workspace.json``.
    Ensures the directory exists before writing.
    """
    tag = safe_tag(str(chat_id))
    if not tag:
        return
    meta_path = DATA_DIR / tag / "workspace.json"
    # ensure parent exists
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(meta_path, data)


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\-]+", "_", name).strip("._")
    return name[:100] or "file"


def _chat_dir(chat_id: int | str) -> Path:
    """
    Return the directory for storing files for the given chat.  Files are
    stored under ``DATA_DIR/<tag>/files`` instead of the global
    WORKSPACE_DIR.  Ensures the directory exists.
    """
    tag = safe_tag(str(chat_id))
    if not tag:
        # fallback: use numeric ID directly
        tag = str(chat_id)
    d = DATA_DIR / tag / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------- public api ----------

def save_file(
    chat_id: int | str,
    name: str,
    content: bytes,
    mime: str = "application/octet-stream",
    kind: str = "input",
) -> dict[str, Any]:
    """Сохранить файл в workspace и записать метаданные. Возвращает meta."""
    file_id = uuid.uuid4().hex[:12]
    safe = _safe_name(name)
    path = _chat_dir(chat_id) / f"{file_id}__{safe}"
    path.write_bytes(content)
    meta = {
        "id": file_id,
        "name": name,
        "path": str(path),
        "mime": mime,
        "size": len(content),
        "created_at": int(time.time()),
        "kind": kind,
    }
    # Load existing metadata for this chat
    data = _load_meta(chat_id) or {}
    files = data.setdefault("files", {})
    files[file_id] = meta
    _save_meta(chat_id, data)
    logger.info(
        "saved: chat=%s id=%s name=%s size=%dKB kind=%s",
        chat_id, file_id, name, len(content) // 1024, kind,
    )
    return meta


def list_files(chat_id: int | str) -> list[dict[str, Any]]:
    """
    Return a list of metadata entries for files belonging to the given chat.
    Files are stored in the chat-specific metadata file rather than the
    global workspace meta.
    """
    data = _load_meta(chat_id) or {}
    files = list((data.get("files") or {}).values())
    files.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return files


def get_file(chat_id: int | str, file_id: str) -> dict[str, Any] | None:
    data = _load_meta(chat_id) or {}
    return (data.get("files") or {}).get(file_id)


def find_file(chat_id: int | str, ref: str) -> dict[str, Any] | None:
    """
    Find a file in the given chat by id or name (exact/substring).  If
    multiple matches are found, return the most recent one.
    """
    if not ref:
        return None
    files = list_files(chat_id)
    # exact by id
    for f in files:
        if f.get("id") == ref:
            return f
    # exact by name
    for f in files:
        if f.get("name") == ref:
            return f
    # partial by name
    ref_low = ref.lower()
    for f in files:
        name = f.get("name") or ""
        if ref_low in name.lower():
            return f
    return None


def delete_file(chat_id: int | str, file_id: str) -> bool:
    data = _load_meta(chat_id) or {}
    files = data.get("files") or {}
    meta = files.pop(file_id, None)
    if not meta:
        return False
    try:
        Path(meta.get("path", "")).unlink(missing_ok=True)
    except OSError:
        pass
    data["files"] = files
    _save_meta(chat_id, data)
    return True


def clear(chat_id: int | str) -> int:
    """
    Delete all files for a given chat.  Removes the chat's workspace
    directory and metadata file.  Returns the number of deleted files.
    """
    data = _load_meta(chat_id) or {}
    files = data.get("files") or {}
    n = len(files)
    # Remove workspace directory
    tag = safe_tag(str(chat_id)) or str(chat_id)
    chat_dir = DATA_DIR / tag / "files"
    if chat_dir.exists():
        shutil.rmtree(chat_dir, ignore_errors=True)
    # Remove metadata file
    meta_path = DATA_DIR / tag / "workspace.json"
    try:
        meta_path.unlink()
    except OSError:
        pass
    return n


def cleanup_old() -> int:
    """
    Delete all files older than TTL across all chats.  Iterates through
    every chat directory under DATA_DIR and purges files older than
    WORKSPACE_TTL_HOURS.  Returns the number of deleted files.
    """
    cutoff = int(time.time()) - WORKSPACE_TTL_HOURS * 3600
    deleted = 0
    # Walk through all chat directories in DATA_DIR
    for chat_dir in DATA_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        # workspace files live in subfolder "files"
        files_dir = chat_dir / "files"
        meta_path = chat_dir / "workspace.json"
        # Load meta
        meta = {}
        if meta_path.exists():
            meta = load_json(meta_path, {}) or {}
        files = meta.get("files", {})
        removed_any = False
        for fid in list(files.keys()):
            meta_entry = files[fid]
            created_at = meta_entry.get("created_at", 0)
            if created_at < cutoff:
                # Delete file from disk
                try:
                    Path(meta_entry.get("path", "")).unlink(missing_ok=True)
                except OSError:
                    pass
                del files[fid]
                deleted += 1
                removed_any = True
        if removed_any:
            # Save updated meta
            meta["files"] = files
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            save_json(meta_path, meta)
        # If no files remain, delete directory and meta
        if not files:
            if files_dir.exists():
                shutil.rmtree(files_dir, ignore_errors=True)
            try:
                meta_path.unlink()
            except OSError:
                pass
    if deleted:
        logger.info("workspace cleanup: %d файлов удалено", deleted)
    return deleted


def stats() -> dict[str, int]:
    """
    Return statistics for the workspace: number of chats and total files.
    Iterates through all chat directories and counts files recorded in
    each chat's workspace metadata.
    """
    chats = 0
    total = 0
    for chat_dir in DATA_DIR.iterdir():
        if not chat_dir.is_dir():
            continue
        meta_path = chat_dir / "workspace.json"
        if meta_path.exists():
            meta = load_json(meta_path, {}) or {}
            files = meta.get("files", {}) or {}
            if files:
                chats += 1
                total += len(files)
    return {"chats": chats, "files": total}
