"""
Main Group Gate implementation.

This is the central piece that decides whether a message from a group
should be processed by the agent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from bot.group.access import get_user_level
from bot.group.config import GroupGateConfig
from bot.group.context import GroupContext
from bot.group.decision import LLMResponseDecider, ResponseDecider
from bot.group.rate_limiter import RateLimiter
from bot.group.spam import SpamDetector
from bot.group.context import MessageSnapshot
from bot.group.types import GateReason, GateResult, UserLevel


class GroupGate:
    """
    Modern, extensible Group Gate with optional LLM decision layer.

    When `response_decider` is provided (recommended for lively behavior),
    every message in proactive groups will be evaluated by a fast model (GLM)
    before deciding whether to wake up the full agent.
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
        self.response_decider = response_decider  # LLM-based decider (GLM)

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

        # === 2. Determine user level ===
        level = get_user_level(user_id, self.config)

        # === 3. Owner and VIP bypass most checks ===
        if level == UserLevel.OWNER:
            return GateResult(True, GateReason.OWNER, text, level)

        if level == UserLevel.VIP:
            return GateResult(True, GateReason.VIP, text, level)

        # === 4. Rate limiting ===
        if not self.rate_limiter.is_allowed(user_id, level):
            return GateResult(False, GateReason.RATE_LIMITED, text, level)

        # === 5. Spam / Flood protection ===
        is_spam, spam_reason = self.spam_detector.check(user_id, text)
        if is_spam:
            reason = GateReason.SPAM_DUPLICATE if spam_reason == "duplicate" else GateReason.SPAM_FLOOD
            return GateResult(False, reason, text, level)

        # === 6. Hard triggers (always process) ===
        bot_username = self.config.extra.get("bot_username", "")
        if self._has_mention(text, bot_username):
            return GateResult(True, GateReason.MENTION, self._clean_mention(text, bot_username), level)

        if self.config.always_process_replies_to_bot and self._is_reply_to_bot(message):
            return GateResult(True, GateReason.REPLY_TO_BOT, text, level)

        if self._contains_explicit_trigger(text):
            return GateResult(True, GateReason.EXPLICIT_TRIGGER, text, level)

        # === 7. LLM-based decision layer (makes the bot feel alive) ===
        if self.response_decider is not None and self.config.enable_proactive_mode:
            recent = self.context.get_recent_messages()
            current = MessageSnapshot(user_id, text, time.time())

            decision = self.response_decider.should_respond(
                recent_messages=recent,
                current_message=current,
            )

            if decision.should_respond:
                return GateResult(
                    True,
                    GateReason.CONTEXT_RELEVANT,
                    text,
                    level,
                    metadata={
                        "llm_decision": True,
                        "reason": decision.reason,
                        "confidence": decision.confidence,
                        "suggested_path": decision.path,
                        "reminder_request": decision.reminder_request,
                    },
                )
            else:
                # LLM decided not to respond — we can still allow very rare spontaneous messages
                # (optional: add small probability here later)
                return GateResult(False, GateReason.IGNORED, text, level)

        # === 8. Fallback: simple keyword/context relevance ===
        relevance = self.context.calculate_relevance_score(self.config.interest_keywords)
        if relevance >= self.config.context_relevance_threshold:
            return GateResult(
                True,
                GateReason.CONTEXT_RELEVANT,
                text,
                level,
                metadata={"relevance_score": round(relevance, 2)}
            )

        # === 9. Legacy proactive mode (without LLM) ===
        if self.config.enable_proactive_mode:
            return GateResult(True, GateReason.PROACTIVE, text, level)

        # === Default: ignore ===
        return GateResult(False, GateReason.IGNORED, text, level)

    # --- Helper methods ---

    def _has_mention(self, text: str, bot_username: str) -> bool:
        if not bot_username or not text:
            return False
        return f"@{bot_username.lower()}" in text.lower()

    def _clean_mention(self, text: str, bot_username: str) -> str:
        if not bot_username:
            return text
        import re
        return re.sub(rf"@?{re.escape(bot_username)}", "", text, flags=re.IGNORECASE).strip()

    def _is_reply_to_bot(self, message: dict) -> bool:
        reply_to = message.get("reply_to_message") or {}
        reply_from = reply_to.get("from") or {}
        return bool(reply_from.get("is_bot"))

    def _contains_explicit_trigger(self, text: str) -> bool:
        """Legacy trigger words from old system (can be moved to config)."""
        # For backward compatibility with old GROUP_TRIGGER_WORDS
        # In real usage this should come from config.
        from bot.config import GROUP_TRIGGER_WORDS
        low = text.lower()
        return any(t in low for t in GROUP_TRIGGER_WORDS)
