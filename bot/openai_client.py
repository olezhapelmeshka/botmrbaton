"""
Обёртка вокруг OpenAI SDK для совместимых моделей (например, GLM‑4.5‑Flash).

Этот модуль использует официальный Python‑клиент `openai` для отправки запросов
к OpenAI‑совместимым API, таким как OpenRouter или Z.ai PaaS.  В отличие
от Anthropic, OpenAI возвращает одно сообщение с функциями (tool calls),
поэтому здесь мы адаптируем ответ к формату, который использует агентный
слой (список блоков с типами `text` и `tool_use`).

Для подключения используйте переменные окружения:
```
OPENAI_API_KEY=...
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=glm-4.5-flash
```

Если `OPENAI_API_KEY` и `OPENAI_BASE_URL` не заданы, этот модуль не
инициализируется, и агент использует только Anthropic.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

try:
    import openai  # type: ignore
except ImportError:  # pragma: no cover
    openai = None  # type: ignore

from bot.config import (
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_MODEL,
    MAX_TOKENS,
    MAX_TOKENS_DOC,
    TEMPERATURE,
    REQUEST_TIMEOUT,
)
from bot.logger import get_logger


logger = get_logger("openai")

_client: Any = None


class _OpenAIResponse:
    """Простая обёртка, имитирующая интерфейс ответа Anthropic SDK.

    Атрибуты:
        content (list[dict]): список блоков (text / tool_use).
        stop_reason (str | None): причина остановки ("tool_use" или "stop").
    """

    def __init__(self, content: List[Dict[str, Any]], stop_reason: str | None) -> None:
        self.content = content
        self.stop_reason = stop_reason


def get_client() -> Any:
    """Создать и вернуть инстанс клиента OpenAI.

    Если библиотека `openai` не установлена или переменные окружения пусты,
    вернёт None.  В таком случае следует использовать Anthropic.
    """
    global _client
    if _client is not None:
        return _client
    if not openai or not OPENAI_API_KEY or not OPENAI_BASE_URL:
        return None
    try:
        # openai>=1.14.0 поддерживает класс OpenAI
        _client = openai.OpenAI(
            api_key=OPENAI_API_KEY,
            base_url=OPENAI_BASE_URL,
            timeout=REQUEST_TIMEOUT,
        )
        logger.info("OpenAI клиент готов: base=%s model=%s", OPENAI_BASE_URL, OPENAI_MODEL)
    except Exception as exc:  # pragma: no cover
        logger.exception("Не удалось инициализировать OpenAI клиент: %s", exc)
        _client = None
    return _client


def _to_blocks(message: Any) -> List[Dict[str, Any]]:
    """
    Преобразовать ответ OpenAI/Z.ai в список блоков формата агента:
    - text
    - tool_use

    Поддерживает и dict-ответы, и объекты OpenAI SDK.
    """
    blocks: List[Dict[str, Any]] = []

    if not message:
        return blocks

    # Текст ответа
    if isinstance(message, dict):
        text = message.get("content")
        tool_calls = message.get("tool_calls")
    else:
        text = getattr(message, "content", None)
        tool_calls = getattr(message, "tool_calls", None)

    if text:
        blocks.append({"type": "text", "text": text})

    # Tool calls
    if tool_calls:
        for call in tool_calls:
            try:
                if isinstance(call, dict):
                    call_id = call.get("id", "")
                    fn = call.get("function") or {}
                    name = fn.get("name") or call.get("name") or ""
                    args_str = fn.get("arguments") or call.get("arguments") or "{}"
                else:
                    call_id = getattr(call, "id", "")
                    fn = getattr(call, "function", None)
                    name = getattr(fn, "name", "") if fn else ""
                    args_str = getattr(fn, "arguments", "{}") if fn else "{}"

                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except Exception:
                    args = {}

                blocks.append({
                    "type": "tool_use",
                    "id": call_id or "",
                    "name": name or "",
                    "input": args or {},
                })

            except Exception as ex:
                logger.exception("Ошибка обработки tool_call: %s", ex)

    return blocks

def create_message(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> _OpenAIResponse:
    """Сделать один запрос к OpenAI‑совместимому API.

    Параметры аналогичны старому Claude клиенту. Возвращает объект
    `_OpenAIResponse`.

    Дополнительно можно передать api_key и base_url — тогда будет создан
    временный клиент (удобно для отдельного vision-эндпоинта).
    """
    # Если переданы свои креды для этого вызова — создаём временный клиент
    if api_key and base_url:
        try:
            temp_client = openai.OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=REQUEST_TIMEOUT,
            )
            client = temp_client
        except Exception as exc:
            logger.exception("Не удалось создать временный OpenAI клиент для vision: %s", exc)
            raise
    else:
        client = get_client()
        if client is None:
            raise RuntimeError("OpenAI клиент не инициализирован или отсутствует ключ/base_url")
    # Подготовка сообщений: OpenAI ожидает первую system-запись отдельно
    openai_msgs: List[Dict[str, Any]] = []
    if system:
        openai_msgs.append({"role": "system", "content": system})
    # OpenAI не понимает multimodal блоки так же, как Claude, поэтому конвертируем
    for msg in messages:
        role = msg.get("role") or "user"
        content = msg.get("content")

        # OpenAI/Z.ai принимает только user/assistant/system.
        # tool_result из Claude-формата превращаем в обычный user-текст.
        if role not in ("user", "assistant", "system"):
            role = "user"

        if isinstance(content, list):
            texts: List[str] = []
            content_parts: List[Dict[str, Any]] = []
            has_image = False

            for b in content:
                if isinstance(b, dict):
                    btype = b.get("type")

                    if btype == "text":
                        txt = b.get("text") or ""
                        if txt:
                            texts.append(str(txt))
                            content_parts.append({"type": "text", "text": str(txt)})

                    elif btype == "image":
                        # Claude-style image block from agent.py → convert to OpenAI image_url
                        has_image = True
                        src = b.get("source") or {}
                        media = src.get("media_type") or "image/jpeg"
                        data = src.get("data") or ""
                        if data:
                            content_parts.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media};base64,{data}"
                                }
                            })

                    elif btype == "tool_use":
                        name = b.get("name") or "tool"
                        inp = b.get("input") or {}
                        tool_text = (
                            "[assistant requested tool "
                            + str(name)
                            + " with input "
                            + json.dumps(inp, ensure_ascii=False)
                            + "]"
                        )
                        texts.append(tool_text)
                        content_parts.append({"type": "text", "text": tool_text})

                    elif btype == "tool_result":
                        result = b.get("content") or ""
                        res_text = "[tool result]\n" + (result if isinstance(result, str) else json.dumps(result, ensure_ascii=False))
                        texts.append(res_text)
                        content_parts.append({"type": "text", "text": res_text})

                else:
                    btype = getattr(b, "type", None)

                    if btype == "text":
                        txt = getattr(b, "text", "") or ""
                        if txt:
                            texts.append(str(txt))
                            content_parts.append({"type": "text", "text": str(txt)})

                    elif btype == "image":
                        has_image = True
                        src = getattr(b, "source", None) or {}
                        if hasattr(src, "get"):
                            media = src.get("media_type") or "image/jpeg"
                            data = src.get("data") or ""
                        else:
                            media = getattr(src, "media_type", "image/jpeg") or "image/jpeg"
                            data = getattr(src, "data", "") or ""
                        if data:
                            content_parts.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{media};base64,{data}"
                                }
                            })

                    elif btype == "tool_use":
                        name = getattr(b, "name", "tool")
                        inp = getattr(b, "input", {}) or {}
                        tool_text = (
                            "[assistant requested tool "
                            + str(name)
                            + " with input "
                            + json.dumps(inp, ensure_ascii=False)
                            + "]"
                        )
                        texts.append(tool_text)
                        content_parts.append({"type": "text", "text": tool_text})

                    elif btype == "tool_result":
                        result = getattr(b, "content", "") or ""
                        res_text = "[tool result]\n" + (result if isinstance(result, str) else json.dumps(result, ensure_ascii=False))
                        texts.append(res_text)
                        content_parts.append({"type": "text", "text": res_text})

            if has_image:
                # OpenAI multimodal format — content must be a list of parts
                final_content = content_parts
            else:
                final_content = "\n".join(t for t in texts if t).strip()

        else:
            final_content = "" if content is None else str(content).strip()

        # Z.ai и многие совместимые провайдеры не любят пустые сообщения.
        # НО полное отбрасывание сообщения ломает историю разговора и часто приводит
        # к пустым completion'ам на следующем шаге. Поэтому:
        # - для user/assistant всегда отправляем сообщение;
        # - если после обработки контент пустой — шлём минимальный placeholder.
        if final_content:
            openai_msgs.append({"role": role, "content": final_content})
        elif role in ("user", "assistant"):
            # Никогда не дропаем user/assistant turns для Z.ai/GLM.
            # Пустой placeholder лучше, чем отсутствующее сообщение в истории.
            openai_msgs.append({"role": role, "content": " "})
    # Подготовка инструментов: адаптируем под формат OpenAI (functions)
    tool_definitions: List[Dict[str, Any]] = []

    if tools:
        for t in tools:
            # Уже OpenAI-формат
            if t.get("type") == "function" and isinstance(t.get("function"), dict):
                fn = t["function"]
                name = fn.get("name")
                desc = fn.get("description", "")
                params = fn.get("parameters") or {"type": "object", "properties": {}}

            # Claude/Anthropic-формат из bot/tools.py
            else:
                name = t.get("name")
                desc = t.get("description", "")
                params = t.get("input_schema") or {"type": "object", "properties": {}}

            if not name:
                continue

            if "type" not in params:
                params["type"] = "object"

            if "properties" not in params:
                params["properties"] = {}

            tool_definitions.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params,
                },
            })
    # Выбор модели и токенов
    model_name = model or OPENAI_MODEL
    limit_tokens = max_tokens or MAX_TOKENS
    try:
        logger.info("OpenAI create_message model=%s max_tokens=%s", model_name, limit_tokens)
        # When tools are provided, instruct the API to allow function
        # calling by passing the list of tool definitions along with
        # tool_choice="auto".  According to Z.AI docs the only
        # supported value for tool_choice is "auto" and it should be
        # omitted if no tools are defined.  See
        # https://docs.z.ai/guides/capabilities/function-calling for details.
        request_kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": openai_msgs,
            "temperature": TEMPERATURE,
            "max_tokens": limit_tokens,
        }
        if tool_definitions:
            request_kwargs["tools"] = tool_definitions
            # Explicitly set tool_choice; default is "auto", but some
            # providers require the parameter if tools are supplied.  Passing
            # "auto" ensures the model may choose to call a function when
            # appropriate.
            request_kwargs["tool_choice"] = "auto"

        # Debug: count how many images we are actually sending (helps verify vision fix)
        img_count = 0
        for m in openai_msgs:
            c = m.get("content")
            if isinstance(c, list):
                img_count += sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
        if img_count > 0:
            logger.info("OpenAI vision: sending %d image(s) to model=%s", img_count, model_name)

        response = client.chat.completions.create(**request_kwargs)
    except Exception as exc:
        logger.exception("OpenAI API ошибка: %s", exc)
        raise
    # Извлекаем первую choice
    choice = None
    if response and getattr(response, "choices", None):
        choice = response.choices[0]
    if not choice:
        return _OpenAIResponse([], None)
    msg = choice.message
    finish_reason = getattr(choice, "finish_reason", None)
    # Mapping OpenAI finish_reason → stop_reason
    if finish_reason in ("tool_calls", "function_call"):
        stop_reason = "tool_use"
    else:
        stop_reason = finish_reason or "stop"
    blocks = _to_blocks(msg)

    # Явная диагностика пустого completion от провайдера (частая проблема GLM на Z.ai).
    # Верхние слои (agent / light_responder) могут отреагировать ретраем или деградацией.
    if not blocks and stop_reason in (None, "stop", "length"):
        logger.warning("Empty completion from provider (no text, no tool_calls). finish_reason=%s model=%s",
                       finish_reason, model_name)

    return _OpenAIResponse(blocks, stop_reason)
