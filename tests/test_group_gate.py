"""Tests for GroupGate strict triggers (mention / reply / keywords only)."""

from __future__ import annotations

from bot.group import GroupGate, GroupGateConfig, GateReason, UserLevel


OWNER_ID = 1001
VIP_ID = 1002
REGULAR_ID = 2002
BOT_ID = 9001


def _msg(
    *,
    user_id: int,
    text: str,
    chat_type: str = "supergroup",
    reply_to_bot: bool = False,
    reply_bot_id: int = BOT_ID,
) -> dict:
    message: dict = {
        "chat": {"id": -1001, "type": chat_type},
        "from": {"id": user_id},
        "text": text,
    }
    if reply_to_bot:
        message["reply_to_message"] = {
            "from": {"id": reply_bot_id, "is_bot": True},
        }
    return message


def _gate(**kwargs) -> GroupGate:
    cfg = GroupGateConfig(
        chat_id=-1001,
        owner_id=OWNER_ID,
        vip_user_id=VIP_ID,
        enable_proactive_mode=False,
        **kwargs,
    )
    cfg.extra["bot_username"] = "mrbaton_bot"
    cfg.extra["bot_id"] = BOT_ID
    return GroupGate(cfg)


def test_private_always_processed():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=REGULAR_ID, text="hi", chat_type="private"))
    assert result.should_process is True
    assert result.reason == GateReason.PRIVATE


def test_owner_without_trigger_ignored():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=OWNER_ID, text="куплю молоко"))
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED
    assert result.user_level == UserLevel.OWNER


def test_vip_without_trigger_ignored():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=VIP_ID, text="куплю молоко"))
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED
    assert result.user_level == UserLevel.VIP


def test_explicit_trigger_for_regular():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=REGULAR_ID, text="эй батон что скажешь"))
    assert result.should_process is True
    assert result.reason == GateReason.EXPLICIT_TRIGGER


def test_mention_trigger():
    gate = _gate()
    result = gate.should_process_message(
        _msg(user_id=REGULAR_ID, text="привет @mrbaton_bot помоги")
    )
    assert result.should_process is True
    assert result.reason == GateReason.MENTION
    assert "@mrbaton_bot" not in result.cleaned_text.lower()


def test_reply_to_this_bot():
    gate = _gate()
    result = gate.should_process_message(
        _msg(user_id=REGULAR_ID, text="ага", reply_to_bot=True)
    )
    assert result.should_process is True
    assert result.reason == GateReason.REPLY_TO_BOT


def test_reply_to_other_bot_ignored():
    gate = _gate()
    result = gate.should_process_message(
        _msg(user_id=REGULAR_ID, text="ага", reply_to_bot=True, reply_bot_id=9999)
    )
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED


def test_interest_keyword_without_trigger_ignored():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=REGULAR_ID, text="купил python"))
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED


def test_bare_bot_word_ignored():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=REGULAR_ID, text="этот бот глючит"))
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED


def test_regular_ignored_without_trigger():
    gate = _gate()
    result = gate.should_process_message(_msg(user_id=REGULAR_ID, text="куплю молоко"))
    assert result.should_process is False
    assert result.reason == GateReason.IGNORED
