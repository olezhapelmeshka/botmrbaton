"""
Group conversation context and topic memory.

The bot keeps a short-term memory of recent messages in the group
to understand what is currently being discussed.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List

from bot.group.config import GroupGateConfig


@dataclass
class MessageSnapshot:
    user_id: int
    text: str
    timestamp: float


class GroupContext:
    """
    Maintains recent conversation history for a single group.
    Used for context-aware triggering.
    """

    def __init__(self, config: GroupGateConfig):
        self.config = config
        self._messages: Deque[MessageSnapshot] = deque(maxlen=config.context_window_size)

    def add_message(self, user_id: int, text: str, timestamp: float) -> None:
        if text:
            self._messages.append(MessageSnapshot(user_id, text, timestamp))

    def get_recent_messages(self, limit: int | None = None) -> List[MessageSnapshot]:
        if limit is None:
            return list(self._messages)
        return list(self._messages)[-limit:]

    def calculate_relevance_score(self, interest_keywords: list[str]) -> float:
        """
        Very simple keyword-based relevance score.
        Can be replaced later with embeddings or small LLM call.
        """
        if not self._messages or not interest_keywords:
            return 0.0

        recent_text = " ".join(m.text.lower() for m in self._messages)
        matches = sum(1 for kw in interest_keywords if kw.lower() in recent_text)
        return min(1.0, matches / max(1, len(interest_keywords) * 0.6))
