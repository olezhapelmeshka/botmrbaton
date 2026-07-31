"""Unit tests for reminder weekday helpers (no LLM calls)."""

from __future__ import annotations

from bot.reminder_parser import _extract_weekdays_from_text, _normalize_weekdays


def test_extract_wednesday():
    assert _extract_weekdays_from_text("каждую среду в 9:00") == [2]


def test_extract_mon_and_fri():
    days = _extract_weekdays_from_text("по пн и пт")
    assert days == [0, 4]


def test_extract_weekdays_bulk():
    assert _extract_weekdays_from_text("по будням в 10:00") == [0, 1, 2, 3, 4]


def test_extract_weekend():
    assert _extract_weekdays_from_text("каждые выходные") == [5, 6]


def test_normalize_mixed():
    assert _normalize_weekdays(["пн", 4, "суббота"]) == [0, 4, 5]


def test_normalize_empty_fallback_monday():
    assert _normalize_weekdays([]) == [0]
