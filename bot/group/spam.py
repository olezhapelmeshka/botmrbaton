"""
Anti-spam and anti-flood protection.
"""

from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict

from bot.group.config import GroupGateConfig


@dataclass
class _UserSpamState:
    recent_hashes: Deque[str] = field(default_factory=lambda: deque(maxlen=10))
    message_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=20))


class SpamDetector:
    """Detects spam, duplicates and flooding per user."""

    def __init__(self, config: GroupGateConfig):
        self.config = config
        self._states: Dict[int, _UserSpamState] = {}

    def _get_state(self, user_id: int) -> _UserSpamState:
        if user_id not in self._states:
            self._states[user_id] = _UserSpamState()
        return self._states[user_id]

    def _text_hash(self, text: str) -> str:
        normalized = " ".join(text.lower().split())
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:16]

    def check(self, user_id: int, text: str) -> tuple[bool, str | None]:
        """
        Returns (is_spam, reason).
        reason can be: "duplicate", "flood", or None
        """
        if not self.config.enable_spam_protection or not text:
            return False, None

        state = self._get_state(user_id)
        now = time.time()
        text_hash = self._text_hash(text)

        # Duplicate detection
        if text_hash in state.recent_hashes:
            return True, "duplicate"

        # Flood detection
        state.message_timestamps.append(now)
        recent = [t for t in state.message_timestamps if now - t < self.config.flood_window_seconds]
        if len(recent) >= self.config.flood_messages_threshold:
            return True, "flood"

        # Record state
        state.recent_hashes.append(text_hash)
        return False, None
