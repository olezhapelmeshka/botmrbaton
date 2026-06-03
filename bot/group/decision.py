"""
LLM-based Response Decider for groups.

This module allows using a cheap/fast model (GLM) to decide
whether the bot should respond to a message in the current group context.
This makes the bot feel much more "alive" and contextually aware.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, Protocol

from bot.group.context import MessageSnapshot

logger = logging.getLogger("group.decision")


@dataclass
class Decision:
    should_respond: bool
    reason: str
    confidence: float = 0.0  # 0.0 - 1.0 (if the model returns it)
    path: str = "agent"      # "casual" (лёгкий путь без инструментов) | "agent" (полноценный агент)
    reminder_request: bool = False  # если True — пользователь явно просил напоминание/таймер


class ResponseDecider(Protocol):
    """Interface for any decision mechanism (LLM, rules, hybrid)."""

    def should_respond(
        self,
        recent_messages: list[MessageSnapshot],
        current_message: MessageSnapshot,
        bot_name: str = "Мистер Батон",
    ) -> Decision:
        ...


class LLMResponseDecider:
    """
    Uses the fast/cheap model (usually GLM) to decide whether the bot
    should reply in a group chat.

    This is the main mechanism that makes Мистер Батон feel "alive" —
    she doesn't just react to mentions, but decides contextually
    whether she wants to join the conversation.
    """

    def __init__(
        self,
        model: str = "glm-4.5-flash",
        temperature: float = 0.65,
        max_tokens: int = 60,
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._client = None  # lazy

    def _get_client(self):
        if self._client is None:
            try:
                from bot import openai_client
                self._client = openai_client
            except Exception as e:
                logger.error("Failed to import openai_client for decision layer: %s", e)
                raise
        return self._client

    def should_respond(
        self,
        recent_messages: list[MessageSnapshot],
        current_message: MessageSnapshot,
        bot_name: str = "Мистер Батон",
    ) -> Decision:
        if not recent_messages and not current_message.text:
            return Decision(False, "empty context")

        # Build compact context for the decision model
        context_lines = []
        for msg in recent_messages[-8:]:  # last 8 messages for decision
            context_lines.append(f"{msg.user_id}: {msg.text[:200]}")

        context_lines.append(f"CURRENT: {current_message.text}")

        context_str = "\n".join(context_lines)

        prompt = f"""Ты — {bot_name}, участник семейного чата олежи и анастасии.

Это семейная группа. Твоя задача — после каждого сообщения решать, стоит ли влезать, и при этом чувствовать уместность.

**Когда отвечать YES (в порядке приоритета):**
- Пользователь прямо просит что-то проверить, найти или посмотреть ("в инете чекни", "погугли", "посмотри погоду на завтра", "найди", "какой курс" и т.п.) — это очень сильный сигнал, почти всегда YES, даже если это тот же человек, который недавно писал.
- Человек просит поставить напоминание, таймер или что-то сделать в конкретное время ("через 5 минут напомни", "в 21:30 скажи", "поставь таймер", "напомни мне через").
- К тебе обратились напрямую.
- Можно сделать короткий, остроумный или полезный комментарий в текущем рофле/обсуждении.
- Начинают обсуждать политику — можно зайти и высмеять.

**Когда отвечать NO:**
- Обычная бытовая болтовня без запроса на информацию или действие.
- Тебе нечего добавить коротко и по делу.
- Ты уже очень активно писал недавно, и текущая реплика не несёт ценности (это не запрос на поиск/информацию и не хороший рофл).

**Важно:** 
Если человек явно просит проверить что-то в интернете или получить свежую информацию — это имеет приоритет над правилами "не спамить". Такие сообщения почти всегда должны получать YES.

Важные особенности этого чата:
- "съесть" почти всегда шутка про руки.
- В семейной группе лучше быть смешным и дерзким, но не самым вульгарным и не самым ушедшим в абсурд. Если чувствуешь, что шутка уже на грани — лучше пропустить.

Примеры:

Сообщения:
олег: сегодня на солане опять лонг поставил, +40%
анастасия: вау, как ты это посчитал?
Ты должна ответить? 
→ DECISION: YES
REASON: обсуждают трейдинг, можно вставить 5 копеек

Сообщения:
олег: купил молоко
анастасия: ок
Ты должна ответить?
→ DECISION: NO
REASON: ничего интересного, обычная болтовня

Сообщения:
олег: батон что думаешь про этот рефакторинг?
Ты должна ответить?
→ DECISION: YES
REASON: прямо обратились ко мне

Сообщения:
олег: в инете чекни погоду на завтра в казани
Ты должна ответить?
 DECISION: YES
REASON: прямой запрос проверить свежую информацию

Теперь реши для текущего разговора.

Вот последние сообщения (с конца):

{context_str}

Отвечай **строго** в формате ниже, без лишнего текста:

DECISION: YES или NO
REASON: одна короткая причина на русском (максимум 15 слов)
PATH: CASUAL или AGENT

PATH:
- CASUAL — обычная семейная болтовня, рофл, реакция на мем, короткий комментарий. Инструменты не нужны, можно ответить сразу.
- AGENT — человек просит что-то найти, проверить в интернете, прочитать файл, поставить напоминание/таймер, посчитать, проанализировать. Нужен полноценный агент с инструментами.

В семейной группе при отсутствии явных слов "погугли / в инете / найди / прочитай / поставь" почти всегда CASUAL.
"""


        try:
            client = self._get_client()
            resp = client.create_message(
                messages=[{"role": "user", "content": prompt}],
                system="Ты помогаешь решить, когда участнику семейного чата стоит ответить. Будь практичным: если человека явно просят что-то проверить или найти — это обычно хороший момент ответить. Не будь излишне осторожным.",
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            text = ""
            if resp and resp.content:
                for block in resp.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                    elif hasattr(block, "text"):
                        text = getattr(block, "text", "")

            text = text.strip().upper()

            # Более устойчивое извлечение решения
            should_respond = False
            if "DECISION: YES" in text or text.startswith("YES"):
                should_respond = True
            elif "DECISION: NO" in text or text.startswith("NO"):
                should_respond = False

            reason = self._extract_reason(text)
            path = self._extract_path(text)

            current_text = current_message.text or ""
            reminder_request = False

            # === Кодовое "обучение" декодера (минимальное вмешательство в промпт) ===
            # Если явно просят поставить напоминание/таймер — принудительно шлём в полный агент,
            # даже если модель сказала CASUAL или NO. Это надёжнее, чем пытаться всё описать в промпте.
            if self._has_reminder_intent(current_text):
                should_respond = True
                path = "agent"
                reason = (reason or "llm") + " + reminder_intent"
                reminder_request = True

            logger.info(
                "LLM Decision | should_respond=%s | reason=%s | path=%s | model=%s",
                should_respond, reason, path, self.model
            )

            return Decision(
                should_respond=should_respond,
                reason=reason or ("llm_said_yes" if should_respond else "llm_said_no"),
                confidence=0.82 if should_respond else 0.65,
                path=path,
                reminder_request=reminder_request,
            )

        except Exception as e:
            logger.warning("LLM decision failed, falling back to conservative: %s", e)

            # Даже при падении модели — если человек явно просит напоминание, лучше не молчать
            current_text = current_message.text or ""
            if self._has_reminder_intent(current_text):
                return Decision(should_respond=True, reason="reminder_intent_fallback", path="agent", reminder_request=True)

            # Safe fallback: be conservative (don't respond too often)
            return Decision(False, "decision_model_error_fallback")

    def _extract_reason(self, text: str) -> str:
        for line in text.split("\n"):
            line = line.strip()
            if "REASON:" in line:
                reason = line.split("REASON:", 1)[1].strip()
                # Убираем возможные кавычки и лишнее
                reason = reason.strip('"\'').strip()
                return reason[:140]
        return "no clear reason"

    def _extract_path(self, text: str) -> str:
        """Извлекает PATH: CASUAL или AGENT. По умолчанию 'agent' (безопасно)."""
        for line in text.split("\n"):
            line = line.strip().upper()
            if "PATH:" in line:
                val = line.split("PATH:", 1)[1].strip()
                if "CASUAL" in val:
                    return "casual"
                if "AGENT" in val:
                    return "agent"
        return "agent"

    def _has_reminder_intent(self, text: str) -> bool:
        """Надёжный эвристический детектор просьб про напоминания/таймеры.
        Работает даже если модель ошиблась с PATH."""
        if not text:
            return False
        t = text.lower()

        # Прямые маркеры
        if any(w in t for w in ["напомни", "напоминание", "поставь таймер", "поставь напоминание"]):
            return True

        # Временные конструкции + действие
        time_patterns = [
            r"через\s+\d+\s*(минут|минуты|мин|час|часа|часов|секунд|сек)",
            r"в\s+\d{1,2}[:.]\d{2}",
            r"в\s+\d{1,2}\s*(утра|вечера|дня|ночи)",
            r"на\s+\d{1,2}[:.]\d{2}",
        ]
        for pat in time_patterns:
            if re.search(pat, t):
                # Проверяем, что рядом есть глагол действия
                if any(v in t for v in ["напомн", "скажи", "разбуди", "заставь", "сделай", "напиши", "позвони"]):
                    return True
                # Или просто "через 5 минут" в контексте просьбы
                if "через" in t and any(v in t for v in ["напомн", "скажи", "сделай"]):
                    return True

        return False
