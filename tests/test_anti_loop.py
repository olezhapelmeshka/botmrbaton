"""Anti-meme-loop: summary hygiene + reply overlap filter."""

from __future__ import annotations

from bot.memory import sanitize_summary_for_context, summarize_old_messages
from bot.utils import is_near_repeat, token_overlap_ratio


def test_summarize_skips_assistant_lines():
    msgs = [
        {"role": "user", "username": "alice", "text": "купил молоко"},
        {"role": "assistant", "text": "4 часа картошки ахах"},
        {"role": "user", "first_name": "bob", "text": "погода норм"},
        {"role": "assistant", "text": "опять картошка"},
    ]
    summary = summarize_old_messages(msgs)
    assert "картошк" not in summary
    assert "молоко" in summary
    assert "погода" in summary
    assert "- bot:" not in summary.lower()


def test_sanitize_summary_strips_legacy_bot_lines():
    raw = (
        "- alice: купил молоко\n"
        "- bot: 4 часа картошки ахах\n"
        "- bob: погода норм\n"
        "бот: старый мем\n"
    )
    clean = sanitize_summary_for_context(raw, max_chars=800)
    assert "картошк" not in clean
    assert "старый мем" not in clean
    assert "молоко" in clean
    assert "погода" in clean


def test_sanitize_summary_truncates():
    raw = "- u: " + ("слово " * 200)
    clean = sanitize_summary_for_context(raw, max_chars=50)
    assert len(clean) <= 50


def test_overlap_detects_near_duplicate_meme():
    prev = ["4 часа картошки это уже классика ахах", "ладно перебор"]
    reply = "4 часа картошки это уже классика просто"
    assert is_near_repeat(reply, prev) is True


def test_overlap_allows_fresh_reply():
    prev = ["4 часа картошки ахах", "мем века просто"]
    reply = "ща гляну погоду в казани"
    assert is_near_repeat(reply, prev) is False


def test_overlap_skips_short_util_replies():
    prev = ["ок, поставил."]
    assert is_near_repeat("ок.", prev) is False


def test_token_overlap_ratio_bounds():
    assert token_overlap_ratio("", "hello") == 0.0
    assert token_overlap_ratio("один два три", "один два три") == 1.0
