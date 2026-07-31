"""Tests for tools.dispatch error paths (no network)."""

from __future__ import annotations

import json

from bot.tools import dispatch


def test_unknown_tool_returns_error_json():
    raw = dispatch("definitely_not_a_tool", {}, chat_id=42)
    data = json.loads(raw)
    assert "error" in data
    assert "Unknown tool" in data["error"]


def test_notebook_write_empty_text():
    raw = dispatch("notebook_write", {"text": "   "}, chat_id=42)
    data = json.loads(raw)
    assert data.get("error") == "Пустой текст"


def test_create_reminder_missing_fields():
    raw = dispatch("create_reminder", {"time": "", "text": ""}, chat_id=42)
    data = json.loads(raw)
    assert "error" in data


def test_analyze_youtube_bad_url():
    raw = dispatch("analyze_youtube", {"url": "https://example.com/not-yt"}, chat_id=42)
    data = json.loads(raw)
    assert "error" in data
