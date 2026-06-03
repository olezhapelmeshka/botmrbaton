"""
Core types for the Group Gate system.

This module defines the data structures used throughout the group access control,
rate limiting, and decision making process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class UserLevel(str, Enum):
    """Hierarchy of user access levels in a group."""
    OWNER = "owner"           # Bot owner (highest privileges)
    ANASTASIA = "anastasia"   # Special user (Anastasia)
    TRUSTED = "trusted"       # Whitelisted users
    REGULAR = "regular"       # Normal group members
    RESTRICTED = "restricted" # Users with lowered permissions


class GateReason(str, Enum):
    """Reasons why a message was accepted or rejected by the gate."""
    # Positive reasons (should_process=True)
    PRIVATE = "private"
    MENTION = "mention"
    REPLY_TO_BOT = "reply_to_bot"
    EXPLICIT_TRIGGER = "explicit_trigger"
    OWNER = "owner"
    ANASTASIA = "anastasia"
    TRUSTED = "trusted"
    CONTEXT_RELEVANT = "context_relevant"      # Smart context match
    PROACTIVE = "proactive"                    # Legacy proactive mode

    # Negative reasons (should_process=False)
    NOT_IN_GROUP = "not_in_group"
    RATE_LIMITED = "rate_limited"
    SPAM_DUPLICATE = "spam_duplicate"
    SPAM_FLOOD = "spam_flood"
    IGNORED = "ignored"


@dataclass
class GateResult:
    """
    Result of the GroupGate decision.

    Attributes:
        should_process: Whether the message should be passed to the agent.
        reason: Machine-readable reason for the decision.
        cleaned_text: Text with bot mention removed (for groups).
        user_level: The access level of the sender.
        metadata: Additional information (e.g. matched keywords, topic, confidence).
    """
    should_process: bool
    reason: GateReason
    cleaned_text: str
    user_level: UserLevel
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return (
            f"GateResult(should={self.should_process}, "
            f"reason={self.reason.value}, level={self.user_level.value})"
        )
