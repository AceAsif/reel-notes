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


# ---- chat mode routing and replies --------------------------------------------
import asyncio  # noqa: E402

import requests  # noqa: E402


def first_matching_handler(text):
    """Which handler would Telegram use for this message? (group 0, first match wins)"""
    from datetime import datetime
    from telegram import Chat, Message, MessageEntity, Update, User
    bot.TOKEN = "123:ABC"                       # any valid-looking token; nothing is sent
    app = bot.build_app()
    entities = ([MessageEntity("bot_command", 0, len(text.split()[0]))]
                if text.startswith("/") else None)
    msg = Message(1, datetime.now(), Chat(1, "private"), from_user=User(1, "me", False),
                  text=text, entities=entities)
    app.bot._bot_user = User(999, "Reel Notes", True, username="test_reel_bot")  # normally from Telegram
    upd = Update(1, message=msg)
    upd.set_bot(app.bot)
    msg.set_bot(app.bot)
    for h in app.handlers[0]:
        if h.check_update(upd):
            return h.callback.__name__
    return None


@pytest.mark.parametrize("text,handler", [
    ("https://www.instagram.com/reel/ABC/", "handle_link"),
    ("what did I save about claude?", "chat"),
    ("thanks!", "chat"),
    ("/todo", "todo"),
    ("/newchat", "newchat"),
])
def test_message_routing(text, handler):
    assert first_matching_handler(text) == handler


class FakeMessage:
    def __init__(self, text): self.text, self.replies = text, []
    async def reply_text(self, t, reply_markup=None): self.replies.append(t)


def run_chat(text, chat_data, monkeypatch, fake):
    monkeypatch.setattr(bot.processor, "chat_reply", fake)
    msg = FakeMessage(text)
    upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1),
                                effective_chat=types.SimpleNamespace(id=1))
    async def typing(*a): pass
    ctx = types.SimpleNamespace(bot=types.SimpleNamespace(send_chat_action=typing),
                                chat_data=chat_data, user_data={})
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    asyncio.run(bot.chat(upd, ctx))
    return msg.replies[-1], ctx


def test_chat_reply_lists_sources_and_remembers(tmp_path, monkeypatch):
    note = tmp_path / "2026-11-13_1200_x.md"
    note.write_text("# Claude Memory Plugin\n", encoding="utf-8")
    chat_data = {}
    reply, ctx = run_chat("which plugin?", chat_data, monkeypatch,
                          lambda text, history: ("Use Claude mem.", [note]))
    assert reply.startswith("Use Claude mem.") and "1. Claude Memory Plugin" in reply
    assert ctx.user_data["last_results"] == [str(note)]
    assert chat_data["chat_history"] == [
        {"role": "user", "content": "which plugin?"},
        {"role": "assistant", "content": "Use Claude mem."}]


def test_chat_when_ollama_is_off(monkeypatch):
    def down(text, history):
        raise requests.exceptions.ConnectionError()
    reply, _ = run_chat("hi", {}, monkeypatch, down)
    assert "Is Ollama running?" in reply


def test_newchat_clears_history(monkeypatch):
    msg = FakeMessage("/newchat")
    chat_data = {"chat_history": [{"role": "user", "content": "x"}]}
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    asyncio.run(bot.newchat(types.SimpleNamespace(message=msg,
                            effective_user=types.SimpleNamespace(id=1)),
                            types.SimpleNamespace(chat_data=chat_data)))
    assert chat_data["chat_history"] == []


# ---- /todo pages ---------------------------------------------------------------

@pytest.fixture
def many_actions(tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(bot.processor, "NOTES_DIR", folder)
    monkeypatch.setattr(bot.processor, "REMINDERS_FILE", tmp_path / "r.json")
    actions = "\n".join([f"- [ ] 🔥 high {i}" for i in range(3)] +
                        [f"- [ ] normal {i}" for i in range(20)])
    (folder / "2026-11-14_1200_x.md").write_text(
        f"# Note X\n\n## Action items\n{actions}\n", encoding="utf-8")


def test_todo_first_page(many_actions):
    text, kb = bot.todo_page(1)
    assert "23 open actions (page 1/3)" in text and "1. ☐ high 0" in text
    assert "11. ☐" not in text
    assert [b.text for b in kb.inline_keyboard[0]] == ["1/3", "Next ➡️"]


def test_todo_last_page_keeps_real_numbers(many_actions):
    text, kb = bot.todo_page(3)
    assert "21. ☐ normal 17" in text and "23. ☐ normal 19" in text
    assert [b.text for b in kb.inline_keyboard[0]] == ["⬅️ Prev", "3/3"]


def test_todo_high_filter(many_actions):
    text, kb = bot.todo_page(1, "high")
    assert "3 open high priority actions" in text and kb is None
    assert "normal 0" not in text


def test_todo_page_out_of_range(many_actions):
    assert "page 3/3" in bot.todo_page(99)[0]
