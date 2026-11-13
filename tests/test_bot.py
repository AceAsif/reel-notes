"""Tests for bot.py helpers that don't need Telegram."""
import os
import re
import sys
import types
from pathlib import Path

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
sys.modules.setdefault("pytesseract", types.SimpleNamespace(pytesseract=types.SimpleNamespace()))
sys.modules.setdefault("faster_whisper", types.SimpleNamespace(WhisperModel=None))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot  # noqa: E402


@pytest.mark.parametrize("text,ok", [
    ("https://www.instagram.com/reel/ABC/", True),
    ("https://www.instagram.com/p/ABC/", True),
    ("https://www.facebook.com/reel/123", True),
    ("look https://www.youtube.com/shorts/abcDEF12345 nice", True),
    ("https://youtu.be/abcDEF12345", True),
    ("https://www.youtube.com/watch?v=abcDEF12345", True),
    ("https://www.tiktok.com/@user/video/123", True),
    ("https://vm.tiktok.com/ZMabc/", True),
    ("https://www.youtube.com/@somechannel", False),
    ("https://example.com/video", False),
])
def test_link_pattern(text, ok):
    assert bool(re.search(bot.LINK_PATTERN, text)) is ok
