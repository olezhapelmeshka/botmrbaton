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
        2. VIP (optional privileged co-user)
        3. Trusted list
        4. Regular (default)
    """
    if config.owner_id and user_id == config.owner_id:
        return UserLevel.OWNER

    if config.vip_user_id and user_id == config.vip_user_id:
        return UserLevel.VIP

    if user_id in config.trusted_user_ids:
        return UserLevel.TRUSTED

    return UserLevel.REGULAR
