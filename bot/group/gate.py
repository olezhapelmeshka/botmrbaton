"""
Main Group Gate implementation.

This is the central piece that decides whether a message from a group
should be processed by the agent.
"""

from __future__ import annotations

import re
import time

from bot.group.access import get_user_level
from bot.group.config import GroupGateConfig
from bot.group.context import GroupContext
from bot.group.decision import ResponseDecider
from bot.group.rate_limiter import RateLimiter
from bot.group.spam import SpamDetector
from bot.group.types import GateReason, GateResult, UserLevel


class GroupGate:
    """
    Group Gate: in groups, process only mention / reply-to-this-bot / trigger words.
    Private chats always process. Optional response_decider is kept for API compat
    but is not used for wake decisions.
    """

    def __init__(
        self,
        config: GroupGateConfig,
        response_decider: ResponseDecider | None = None,
    ):
        self.config = config
        self.context = GroupContext(config)
        self.rate_limiter = RateLimiter(config)
        self.spam_detector = SpamDetector(config)
        self.response_decider = response_decider

    def should_process_message(self, message: dict) -> GateResult:
        """
        Main decision method.

        Returns a rich GateResult that explains exactly why the message
        was accepted or rejected.
        """
        chat = message.get("chat") or {}
        chat_type = (chat.get("type") or "").lower()
        text = (message.get("text") or message.get("caption") or "").strip()
        user = message.get("from") or {}
        user_id = user.get("id")

        # === 1. Basic guards ===
        if chat_type == "private":
            return GateResult(True, GateReason.PRIVATE, text, UserLevel.REGULAR)

        if chat_type not in ("group", "supergroup"):
            return GateResult(False, GateReason.NOT_IN_GROUP, text, UserLevel.REGULAR)

        if user_id is None:
            return GateResult(False, GateReason.IGNORED, text, UserLevel.REGULAR)

        # Update conversation context
        self.context.add_message(user_id, text, time.time())

        level = get_user_level(user_id, self.config)

        # === 2. Rate limiting ===
        if not self.rate_limiter.is_allowed(user_id, level):
            return GateResult(False, GateReason.RATE_LIMITED, text, level)

        # === 3. Spam / Flood protection ===
        is_spam, spam_reason = self.spam_detector.check(user_id, text)
        if is_spam:
            reason = GateReason.SPAM_DUPLICATE if spam_reason == "duplicate" else GateReason.SPAM_FLOOD
            return GateResult(False, reason, text, level)

        # === 4. Hard triggers only (mention / reply / keywords) ===
        bot_username = self.config.extra.get("bot_username", "")
        if self._has_mention(text, bot_username):
            return GateResult(True, GateReason.MENTION, self._clean_mention(text, bot_username), level)

        if self.config.always_process_replies_to_bot and self._is_reply_to_bot(message):
            return GateResult(True, GateReason.REPLY_TO_BOT, text, level)

        if self._contains_explicit_trigger(text):
            return GateResult(True, GateReason.EXPLICIT_TRIGGER, text, level)

        return GateResult(False, GateReason.IGNORED, text, level)

    # --- Helper methods ---

    def _has_mention(self, text: str, bot_username: str) -> bool:
        if not bot_username or not text:
            return False
        return f"@{bot_username.lower()}" in text.lower()

    def _clean_mention(self, text: str, bot_username: str) -> str:
        if not bot_username:
            return text
        return re.sub(rf"@?{re.escape(bot_username)}", "", text, flags=re.IGNORECASE).strip()

    def _is_reply_to_bot(self, message: dict) -> bool:
        reply_to = message.get("reply_to_message") or {}
        reply_from = reply_to.get("from") or {}
        if not reply_from.get("is_bot"):
            return False
        bot_id = self.config.extra.get("bot_id")
        if bot_id is not None:
            return reply_from.get("id") == bot_id
        return True

    def _contains_explicit_trigger(self, text: str) -> bool:
        """Word-boundary match against GROUP_TRIGGER_WORDS (unicode-aware)."""
        from bot.config import GROUP_TRIGGER_WORDS

        if not text:
            return False
        low = text.lower()
        for tw in GROUP_TRIGGER_WORDS:
            tw = (tw or "").strip().lower()
            if not tw:
                continue
            pat = r"(?<![\w])" + re.escape(tw) + r"(?![\w])"
            if re.search(pat, low, re.UNICODE):
                return True
        return False
