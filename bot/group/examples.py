"""
Usage examples for the new Group Gate system.
"""

from bot.group import GroupGate, GroupGateConfig, UserLevel


def example_family_group(owner_id: int, anastasia_id: int):
    """Main family chat (the one from the original project)."""
    config = GroupGateConfig.family_chat(
        owner_id=owner_id,
        anastasia_id=anastasia_id,
    )
    # Override some values for this specific chat
    config.chat_id = -1001234567890
    config.chat_title = "Семья"
    config.enable_proactive_mode = True

    gate = GroupGate(config)
    return gate


def example_trading_group(owner_id: int):
    """A dedicated trading discussion group."""
    config = GroupGateConfig.trading_group(owner_id=owner_id)
    config.chat_id = -1009876543210
    config.chat_title = "Трейдинг & Крипта"

    # Give some people higher trust
    config.trusted_user_ids = {123456789, 987654321}

    gate = GroupGate(config)
    return gate


def example_custom_group():
    """Fully custom configuration."""
    config = GroupGateConfig(
        chat_id=-100111222333,
        owner_id=571662006,
        anastasia_id=123456789,
        trusted_user_ids={111, 222, 333},
        interest_keywords=["логопедия", "дизартрия", "бот", "нейросеть", "claude"],
        context_window_size=20,
        context_relevance_threshold=0.5,
    )

    # Fine-tune rate limits
    config.rate_limits[UserLevel.TRUSTED].messages_per_minute = 50

    gate = GroupGate(config)
    return gate
