"""
Usage examples for the Group Gate system.

IDs are placeholders — pass real Telegram user IDs from your .env
(OWNER_USER_ID / VIP_USER_ID) when wiring a live bot.
"""

from bot.group import GroupGate, GroupGateConfig, UserLevel


def example_family_group(owner_id: int, vip_user_id: int | None = None):
    """Lively private/family-style group."""
    config = GroupGateConfig.family_chat(
        owner_id=owner_id,
        vip_user_id=vip_user_id,
    )
    config.chat_id = -1001234567890
    config.chat_title = "Family chat"
    config.enable_proactive_mode = True

    gate = GroupGate(config)
    return gate


def example_trading_group(owner_id: int):
    """A dedicated trading discussion group."""
    config = GroupGateConfig.trading_group(owner_id=owner_id)
    config.chat_id = -1009876543210
    config.chat_title = "Trading & Crypto"

    config.trusted_user_ids = {111111111, 222222222}

    gate = GroupGate(config)
    return gate


def example_custom_group(owner_id: int, vip_user_id: int | None = None):
    """Fully custom configuration."""
    config = GroupGateConfig(
        chat_id=-100111222333,
        owner_id=owner_id,
        vip_user_id=vip_user_id,
        trusted_user_ids={111, 222, 333},
        interest_keywords=["бот", "нейросеть", "python", "glm"],
        context_window_size=20,
        context_relevance_threshold=0.5,
    )

    config.rate_limits[UserLevel.TRUSTED].messages_per_minute = 50

    gate = GroupGate(config)
    return gate
