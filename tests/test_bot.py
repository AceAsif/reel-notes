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


def test_resurface_message(tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(bot.processor, "NOTES_DIR", folder)
    (folder / "2020-01-01_1200_a.md").write_text(
        "# Deep Conversations\n\n## Key quote\n> Ask better questions\n", encoding="utf-8")
    text, kb, path = bot.resurface_message()
    assert "💬 Ask better questions" in text and "Deep Conversations" in text
    assert path.name.startswith("2020-01-01") and kb.inline_keyboard[0][0].callback_data == "resurf:1"


def test_resurface_message_when_no_old_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    assert bot.resurface_message()[2] is None


def test_month_text(tmp_path, monkeypatch):
    from datetime import date
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(bot.processor, "NOTES_DIR", folder)
    today = date.today().isoformat()
    (folder / f"{today}_1200_a.md").write_text(
        f"# A\n\n- Category: tech\n- Tags: #claude #github\n\n## Action items\n"
        f"- [x] 🔥 Read the Strix README ✅ {today}\n- [ ] Try Claude mem\n", encoding="utf-8")
    text = bot.month_text()
    assert "so far" in text and "#claude (1 reel)" in text
    assert "Reels saved: 1 (1 tech)" in text and "Actions done: 1" in text
    assert "• Read the Strix README" in text and "Still open: 1" in text


def test_month_text_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    assert "No reels saved" in bot.month_text()


def test_month_range():
    from datetime import date
    assert bot.processor.month_range(date(2026, 11, 14)) == (date(2026, 11, 1), date(2026, 11, 14))
    assert bot.processor.month_range(date(2026, 1, 1), previous=True) == \
        (date(2025, 12, 1), date(2025, 12, 31))


def test_photo_routes_to_screenshot_handler():
    from datetime import datetime
    from telegram import Chat, Message, PhotoSize, Update, User
    bot.TOKEN = "123:ABC"
    app = bot.build_app()
    msg = Message(1, datetime.now(), Chat(1, "private"), from_user=User(1, "me", False),
                  photo=[PhotoSize("f", "u", 100, 100)])
    upd = Update(1, message=msg)
    assert next(h.callback.__name__ for h in app.handlers[0] if h.check_update(upd)) == "handle_photo"


class FakeShot:
    def __init__(self, caption=""):
        self.caption, self.document, self.replies = caption, None, []
        self.photo = [types.SimpleNamespace(get_file=self._file)]
    async def _file(self):
        async def dl(path): Path(path).write_bytes(b"x")
        return types.SimpleNamespace(download_to_drive=dl)
    async def reply_text(self, t):
        self.replies.append(t)
        async def edit(x): self.replies.append(x)
        return types.SimpleNamespace(edit_text=edit)


def test_album_makes_one_note(monkeypatch):
    calls = []
    def fake(paths, source, caption):
        calls.append((len(paths), source, caption))
        return Path("note.md"), {}
    monkeypatch.setattr(bot.processor, "process_videos", fake)
    monkeypatch.setattr(bot, "format_reply", lambda d, p: "saved")
    asyncio.run(bot.process_screenshots([FakeShot("my notes"), FakeShot()]))
    assert calls == [(2, "screenshot", "my notes")]


@pytest.mark.parametrize("text,handler", [("/redo", "redo"), ("/health", "health"),
                                          ("/update", "update_cmd")])
def test_new_commands_route(text, handler):
    assert first_matching_handler(text) == handler


def test_update_text():
    assert "up to date" in bot.update_text("1", "1", "")
    assert "→ 2" in bot.update_text("1", "2", "") and "Restart" in bot.update_text("1", "2", "")
    assert "failed" in bot.update_text("1", "1", "no network")


def test_health_text(monkeypatch):
    monkeypatch.setattr(bot.processor, "health_checks",
                        lambda: [(True, "Ollama", "running"), (False, "ffmpeg", "not found")])
    text = bot.health_text()
    assert "1 problem found" in text and "❌ ffmpeg: not found" in text


def run_redo_button(tmp_path, monkeypatch, answer, works):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    note = tmp_path / "2026-11-14_2106_x.md"
    note.write_text("# X\n- Source: https://www.instagram.com/reel/A/\n", encoding="utf-8")
    async def fake_link(status, url):
        if works:
            (tmp_path / "2026-11-15_0100_x.md").write_text("# X new", encoding="utf-8")
            return tmp_path / "2026-11-15_0100_x.md"
    monkeypatch.setattr(bot, "note_from_link", fake_link)
    edits = []
    async def edit(t): edits.append(t)
    async def ok(): pass
    query = types.SimpleNamespace(data=answer, answer=ok, edit_message_text=edit, message=None)
    upd = types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={"redo_path": str(note)})
    asyncio.run(bot.redo_button_pressed(upd, ctx))
    return note, edits


def test_redo_success_archives_old(tmp_path, monkeypatch):
    note, _ = run_redo_button(tmp_path, monkeypatch, "redo:yes", True)
    assert not note.exists() and (tmp_path / "old" / note.name).exists()


def test_redo_failure_restores_old(tmp_path, monkeypatch):
    note, _ = run_redo_button(tmp_path, monkeypatch, "redo:yes", False)
    assert note.exists() and not (tmp_path / "old").exists()


def test_redo_cancel(tmp_path, monkeypatch):
    note, edits = run_redo_button(tmp_path, monkeypatch, "redo:no", True)
    assert note.exists() and "kept" in edits[0]
