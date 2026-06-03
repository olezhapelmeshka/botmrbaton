"""
bot.group — Modern Group Access Control System

This package contains a complete, extensible implementation of the Group Gate.

Main entry point:
    from bot.group import GroupGate, GroupGateConfig, GateResult

Example:
    config = GroupGateConfig.family_chat(owner_id=571662006, anastasia_id=...)
    gate = GroupGate(config)
    result = gate.should_process_message(telegram_update["message"])
"""

from bot.group.config import GroupGateConfig
from bot.group.gate import GroupGate
from bot.group.types import GateReason, GateResult, UserLevel

__all__ = [
    "GroupGate",
    "GroupGateConfig",
    "GateResult",
    "GateReason",
    "UserLevel",
]
