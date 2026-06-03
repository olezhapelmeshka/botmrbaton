"""
User access level resolution for groups.

This module is responsible for determining what level of trust a user has
in a specific group.
"""

from __future__ import annotations

from bot.group.config import GroupGateConfig
from bot.group.types import UserLevel


def get_user_level(user_id: int, config: GroupGateConfig) -> UserLevel:
    """
    Determine the access level of a user in the context of a group.

    Order of precedence:
        1. Owner
        2. Anastasia (special)
        3. Trusted list
        4. Regular (default)
    """
    if user_id == config.owner_id:
        return UserLevel.OWNER

    if config.anastasia_id is not None and user_id == config.anastasia_id:
        return UserLevel.ANASTASIA

    if user_id in config.trusted_user_ids:
        return UserLevel.TRUSTED

    return UserLevel.REGULAR
