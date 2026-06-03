"""
Минимальный клиент Telegram Bot API на requests.
Long polling + отправка текста/документов + скачивание файлов.
"""

from __future__ import annotations

from typing import Any

import requests

from bot.config import REQUEST_TIMEOUT, TELEGRAM_TOKEN
from bot.logger import get_logger
from bot.utils import split_for_telegram


logger = get_logger("telegram")

_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
_FILE_API = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}"


# ---------- polling ----------

def get_updates(offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"timeout": timeout}
    if offset is not None:
        params["offset"] = offset
    try:
        r = requests.get(f"{_API}/getUpdates", params=params, timeout=timeout + 10)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            logger.warning("getUpdates not ok: %s", data.get("description"))
            return []
        return data.get("result", [])
    except requests.RequestException as e:
        logger.warning("getUpdates сетевая ошибка: %s", e.__class__.__name__)
        return []
    except ValueError as e:
        logger.warning("getUpdates невалидный JSON: %s", e)
        return []


# ---------- send ----------

def send_message(chat_id: int, text: str, reply_to: int | None = None) -> None:
    if not text:
        return
    for i, part in enumerate(split_for_telegram(text)):
        payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
        if reply_to is not None and i == 0:
            payload["reply_to_message_id"] = reply_to
        try:
            requests.post(f"{_API}/sendMessage", json=payload, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            logger.warning("sendMessage упал: %s", e.__class__.__name__)


def send_message_with_keyboard(
    chat_id: int,
    text: str,
    inline_keyboard: list[list[dict[str, str]]],
) -> None:
    """Отправить сообщение с inline-кнопками."""
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {"inline_keyboard": inline_keyboard},
    }
    try:
        requests.post(f"{_API}/sendMessage", json=payload, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logger.warning("sendMessage+keyboard упал: %s", e.__class__.__name__)


def delete_message(chat_id: int, message_id: int) -> None:
    """Удалить сообщение по id (полезно для временных статусов)."""
    try:
        requests.post(
            f"{_API}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.warning("deleteMessage упал: %s", e.__class__.__name__)


def send_temp_status(chat_id: int, text: str) -> int | None:
    """Отправить временное статусное сообщение и вернуть его message_id для последующего удаления."""
    if not text:
        return None
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(f"{_API}/sendMessage", json=payload, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        if data.get("ok"):
            return data["result"]["message_id"]
    except Exception as e:
        logger.warning("send_temp_status упал: %s", e.__class__.__name__)
    return None


def answer_callback_query(callback_query_id: str, text: str = "") -> None:
    """Ответить на нажатие inline-кнопки (убирает «часики» у кнопки)."""
    try:
        requests.post(
            f"{_API}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
            timeout=10,
        )
    except requests.RequestException as e:
        logger.warning("answerCallbackQuery упал: %s", e.__class__.__name__)


def send_document(
    chat_id: int,
    file_bytes: bytes,
    filename: str,
    caption: str | None = None,
) -> None:
    try:
        files = {"document": (filename, file_bytes)}
        data: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption[:1000]
        requests.post(
            f"{_API}/sendDocument",
            data=data,
            files=files,
            timeout=REQUEST_TIMEOUT,
        )
        logger.info("sendDocument: chat=%s name=%s size=%dKB", chat_id, filename, len(file_bytes) // 1024)
    except requests.RequestException as e:
        logger.warning("sendDocument упал: %s", e.__class__.__name__)


def send_chat_action(chat_id: int, action: str = "typing") -> None:
    try:
        requests.post(
            f"{_API}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
            timeout=10,
        )
    except requests.RequestException:
        pass


# ---------- files ----------

def get_file_info(file_id: str) -> dict[str, Any] | None:
    """Возвращает {file_id, file_path, file_size, ...} или None."""
    try:
        r = requests.get(f"{_API}/getFile", params={"file_id": file_id}, timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("ok"):
            return data.get("result")
        logger.warning("getFile not ok: %s", data.get("description"))
    except requests.RequestException as e:
        logger.warning("getFile упал: %s", e.__class__.__name__)
    return None


def download_file(file_path: str, max_bytes: int) -> bytes | None:
    """
    Скачать файл по file_path (из getFile). Лимит max_bytes.
    Возвращает bytes или None при ошибке/превышении лимита.
    """
    url = f"{_FILE_API}/{file_path}"
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        r.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in r.iter_content(chunk_size=65536):
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                logger.warning("download_file превысил лимит %dMB", max_bytes // (1024 * 1024))
                return None
        return b"".join(chunks)
    except requests.RequestException as e:
        logger.warning("download_file упал: %s", e.__class__.__name__)
        return None


# ---------- meta ----------

def get_me() -> dict[str, Any] | None:
    try:
        r = requests.get(f"{_API}/getMe", timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get("ok"):
            return data.get("result")
    except requests.RequestException as e:
        logger.warning("getMe упал: %s", e.__class__.__name__)
    return None
