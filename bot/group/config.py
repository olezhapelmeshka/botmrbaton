"""
Configuration for GroupGate.

This module provides a flexible, per-chat configuration system.
It supports different behaviors for different groups (family chat, trading group, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.group.types import UserLevel


@dataclass
class RateLimitConfig:
    """Rate limiting parameters for a specific user level."""
    messages_per_minute: int = 10
    burst: int = 5                    # Maximum messages in a short burst
    cooldown_seconds: int = 0         # Minimum seconds between messages


@dataclass
class GroupGateConfig:
    """
    Full configuration for one group's gate behavior.

    This is the central configuration object. It should be loaded once per chat
    (or from a central config file) and passed to GroupGate.
    """

    # === Identity ===
    chat_id: int
    owner_id: int
    vip_user_id: int | None = None

    chat_title: str = ""

    # === Access Control ===
    trusted_user_ids: set[int] = field(default_factory=set)

    # === Smart Context Triggers ===
    # Keywords/phrases that indicate the conversation is relevant.
    # If recent messages contain these, the bot becomes more "eager" to respond.
    interest_keywords: list[str] = field(default_factory=lambda: [
        "трейд", "trading", "крипта", "crypto", "btc", "eth", "sol",
        "код", "программирование", "python", "рефакторинг", "архитектура",
        "мистер батон", "батон", "бот", "нейросеть", "glm",
    ])

    context_window_size: int = 12          # How many recent messages to remember for context
    context_relevance_threshold: float = 0.55  # How strongly context must match interests

    # === Rate Limiting per Level ===
    rate_limits: dict[UserLevel, RateLimitConfig] = field(default_factory=lambda: {
        UserLevel.OWNER:      RateLimitConfig(messages_per_minute=120, burst=30, cooldown_seconds=0),
        UserLevel.VIP:        RateLimitConfig(messages_per_minute=60,  burst=15, cooldown_seconds=0),
        UserLevel.TRUSTED:    RateLimitConfig(messages_per_minute=30,  burst=8,  cooldown_seconds=1),
        UserLevel.REGULAR:    RateLimitConfig(messages_per_minute=8,   burst=3,  cooldown_seconds=4),
        UserLevel.RESTRICTED: RateLimitConfig(messages_per_minute=3,   burst=1,  cooldown_seconds=15),
    })

    # === Spam Protection ===
    enable_spam_protection: bool = True
    duplicate_message_window: int = 5          # Last N messages to check for duplicates
    flood_messages_threshold: int = 5          # Messages in flood_window_seconds
    flood_window_seconds: int = 25

    # === Behavior ===
    always_process_replies_to_bot: bool = True
    always_process_mentions: bool = True
    enable_proactive_mode: bool = False        # Legacy: process almost everything

    # === Extensibility ===
    extra: dict[str, Any] = field(default_factory=dict)  # For future features per group

    @classmethod
    def family_chat(cls, owner_id: int, vip_user_id: int | None = None) -> "GroupGateConfig":
        """Preset for a lively private/family-style group."""
        return cls(
            chat_id=-1,  # Will be set at runtime
            owner_id=owner_id,
            vip_user_id=vip_user_id,
            trusted_user_ids=set(),
            interest_keywords=[
                "трейд", "крипта", "код", "python", "бот", "нейросеть"
            ],
            enable_proactive_mode=True,
        )

    @classmethod
    def trading_group(cls, owner_id: int) -> "GroupGateConfig":
        """Preset for a trading/crypto discussion group."""
        return cls(
            chat_id=-1,
            owner_id=owner_id,
            interest_keywords=["трейд", "крипта", "btc", "eth", "sol", "long", "short", "funding"],
            context_relevance_threshold=0.4,   # More eager in trading groups
            rate_limits={
                UserLevel.OWNER:      RateLimitConfig(messages_per_minute=200, burst=50),
                UserLevel.TRUSTED:    RateLimitConfig(messages_per_minute=40, burst=12),
                UserLevel.REGULAR:    RateLimitConfig(messages_per_minute=12, burst=4),
            },
        )
