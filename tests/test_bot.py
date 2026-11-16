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
    assert "23 open actions (page 1/3)" in text and "1. ☐ 🔗 high 0" in text
    assert "11. ☐" not in text
    assert [b.text for b in kb.inline_keyboard[0]] == ["1/3", "Next ➡️"]


def test_todo_last_page_keeps_real_numbers(many_actions):
    text, kb = bot.todo_page(3)
    assert "21. ☐ 🔗 normal 17" in text and "23. ☐ 🔗 normal 19" in text
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
    async def _file(self, **k):
        async def dl(path, **k): Path(path).write_bytes(b"x")
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


_real_sleep = asyncio.sleep


async def _no_wait(s):
    await _real_sleep(0)


def test_download_retries_then_works(tmp_path, monkeypatch):
    from telegram.error import TimedOut
    monkeypatch.setattr(bot.asyncio, "sleep", _no_wait)
    tries = []
    async def get_file(**k):
        tries.append(1)
        if len(tries) < 3:
            raise TimedOut()
        async def dl(path, **k): Path(path).write_bytes(b"x")
        return types.SimpleNamespace(download_to_drive=dl)
    asyncio.run(bot.download(types.SimpleNamespace(get_file=get_file), tmp_path / "a.jpg"))
    assert len(tries) == 3 and (tmp_path / "a.jpg").exists()


def test_download_gives_clear_error(tmp_path, monkeypatch):
    from telegram.error import TimedOut
    monkeypatch.setattr(bot.asyncio, "sleep", _no_wait)
    async def get_file(**k): raise TimedOut()
    with pytest.raises(RuntimeError, match="timed out 3 times"):
        asyncio.run(bot.download(types.SimpleNamespace(get_file=get_file), tmp_path / "a.jpg"))


def run_due(text, monkeypatch):
    msg = FakeMessage(text)
    upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(args=text.split()[1:])
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    asyncio.run(bot.due(upd, ctx))
    return msg.replies[-1]


def test_due_command(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    (tmp_path / "a.md").write_text("# A\n\n## Action items\n- [ ] Learn Pandas\n", encoding="utf-8")
    assert "No actions have a due date" in run_due("/due", monkeypatch)
    assert "Learn Pandas" in run_due("/due 1 in 3 days", monkeypatch)
    assert "📅" in (tmp_path / "a.md").read_text(encoding="utf-8")
    assert "Learn Pandas" in run_due("/due", monkeypatch)
    assert "don't understand" in run_due("/due 1 banana", monkeypatch)
    assert "Removed" in run_due("/due 1 off", monkeypatch)
    assert "/due" in first_matching_handler("/due 1 friday") or first_matching_handler("/due 1 friday") == "due"


def test_todo_shows_due_section(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    (tmp_path / "a.md").write_text("# A\n\n## Action items\n- [ ] 🔥 Big\n- [ ] Late 📅 2020-01-01\n",
                                   encoding="utf-8")
    text, _ = bot.todo_page(1)
    assert text.index("DUE SOON") < text.index("HIGH PRIORITY")
    assert "1. ☐ 🔗 Late  ⚠️ overdue" in text
    assert "overdue" in bot.due_text()


def test_plan_notes_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    for i in range(1, 4):
        (tmp_path / f"2026-11-1{i}_0900_n{i}.md").write_text(f"# N{i}\n- Tags: #python\n",
                                                            encoding="utf-8")
    ctx = types.SimpleNamespace(user_data={})
    paths, goal, problem = bot.plan_notes(ctx, ["1", "3", "my", "goal"])
    assert [p.name[:10] for p in paths] == ["2026-11-13", "2026-11-11"] and goal == "my goal"
    paths, _, _ = bot.plan_notes(ctx, ["#python"])
    assert len(paths) == 3
    assert "No notes tagged" in bot.plan_notes(ctx, ["#nothing"])[2]
    assert "Usage" in bot.plan_notes(ctx, ["9"])[2]
    assert bot.plan_notes(ctx, [])[0][0].name.startswith("2026-11-13")     # newest by default


def test_edited_messages_are_ignored():
    from datetime import datetime
    from telegram import Chat, Message, Update, User
    bot.TOKEN = "123:ABC"
    app = bot.build_app()
    app.bot._bot_user = User(999, "Reel Notes", True, username="test_reel_bot")
    msg = Message(1, datetime.now(), Chat(1, "private"), from_user=User(1, "me", False), text="/done 2")
    upd = Update(1, edited_message=msg)
    upd.set_bot(app.bot)
    first_group = sorted(app.handlers)[0]
    assert first_group == -1
    assert any(h.check_update(upd) for h in app.handlers[-1])
    normal = Update(2, message=msg)
    normal.set_bot(app.bot)
    assert not any(h.check_update(normal) for h in app.handlers[-1])


def test_todo_and_notes_when_folder_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path / "missing")
    text, kb = bot.todo_page(1)
    assert "Google Drive" in text and kb is None
    msg = FakeMessage("/notes")
    upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1))
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    asyncio.run(bot.notes_list(upd, types.SimpleNamespace(user_data={})))
    assert "Google Drive" in msg.replies[-1]
    sent = []
    async def send_message(chat, t): sent.append(t)
    asyncio.run(bot.send_nudge(types.SimpleNamespace(send_message=send_message), 1, "hi"))
    assert "Google Drive" in sent[0]


class FakeVideoMsg(FakeShot):
    def __init__(self, caption):
        super().__init__(caption)
        self.video = types.SimpleNamespace(file_size=1000, get_file=self._file)
        self.document = None


def test_video_with_caption_saves_link_as_source(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    calls = []
    def fake(videos, source, caption):
        calls.append((source, caption))
        return Path("n.md"), {}
    monkeypatch.setattr(bot.processor, "process_videos", fake)
    monkeypatch.setattr(bot, "format_reply", lambda d, p: "ok")
    cap = "Great tip! https://www.instagram.com/reel/ABC/ #ai"
    upd = types.SimpleNamespace(message=FakeVideoMsg(cap), effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.handle_video(upd, None))
    assert calls == [("https://www.instagram.com/reel/ABC/", cap)]
    calls.clear()
    upd = types.SimpleNamespace(message=FakeVideoMsg("just words"), effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.handle_video(upd, None))
    assert calls == [("", "just words")]


# ---- /todo numbers stay the same until the next /todo ----------------------------

def test_done_uses_numbers_from_last_todo(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    def save(title, action, priority, source):
        data = {"title": title, "category": "tech", "summary": "s", "key_points": [],
                "resources": [], "tags": [], "claims": [], "quote": "", "lesson": "", "habit": "",
                "action_items": [{"text": action, "priority": priority}]}
        return bot.processor.save_note(data, "", "", source)
    old = save("Old", "Read the docs", "normal", "https://x/1")
    context = types.SimpleNamespace(args=[], user_data={})
    def update():
        return types.SimpleNamespace(message=FakeMessage(""), effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.todo(update(), context))                 # shows "1. Read the docs"
    save("New", "Install tool", "high", "https://x/2")       # a new 🔥 action moves the list
    context.args = ["1"]
    upd = update()
    asyncio.run(bot.done(upd, context))
    assert "Read the docs" in upd.message.replies[-1]
    assert "- [x] Read the docs" in old.read_text(encoding="utf-8")
    assert [a["action"] for a in bot.processor.open_actions()] == ["Install tool"]
    upd = update()                                            # number 1 is gone now
    asyncio.run(bot.done(upd, context))
    assert "No matching numbers" in upd.message.replies[-1]


# ---- catch-up of scheduled messages ------------------------------------------------

def catch_up_setup(tmp_path, monkeypatch, sent):
    monkeypatch.setattr(bot.processor, "SENT_JOBS_FILE", tmp_path / "sent.json")
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    monkeypatch.setattr(bot, "job_rules", lambda: {"nudge": {"every": "day", "at": (0, 0)}})
    bot.processor.save_sent_jobs(sent)
    calls = []
    async def fake_nudge(context): calls.append("nudge")
    monkeypatch.setitem(bot.JOB_SENDERS, "nudge", fake_nudge)
    return calls


def test_missed_nudge_is_sent_once(tmp_path, monkeypatch):
    calls = catch_up_setup(tmp_path, monkeypatch, {"nudge": "2000-01-01"})
    asyncio.run(bot.run_due_jobs(None))
    asyncio.run(bot.run_due_jobs(None))                  # the next check must not repeat it
    assert calls == ["nudge"]


def test_first_run_sends_nothing(tmp_path, monkeypatch):
    calls = catch_up_setup(tmp_path, monkeypatch, {})
    asyncio.run(bot.run_due_jobs(None))
    assert calls == [] and "nudge" in bot.processor.load_sent_jobs()


def test_catch_up_waits_for_notes_folder_and_internet(tmp_path, monkeypatch):
    calls = catch_up_setup(tmp_path, monkeypatch, {"nudge": "2000-01-01"})
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path / "drive-not-started")
    asyncio.run(bot.run_due_jobs(None))
    assert calls == []                                   # waits: Google Drive is not up yet
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    async def offline(context): raise bot.NetworkError("no internet")
    monkeypatch.setitem(bot.JOB_SENDERS, "nudge", offline)
    asyncio.run(bot.run_due_jobs(None))
    assert bot.processor.load_sent_jobs()["nudge"] == "2000-01-01"   # not marked: tried again later


def test_job_rules_follow_settings(monkeypatch):
    monkeypatch.setattr(bot, "NUDGE_TIME", "off")
    monkeypatch.setattr(bot, "RESURFACE", "off")
    monkeypatch.setattr(bot, "YTDLP_UPDATE_TIME", "25:99")          # wrong value = off
    assert set(bot.job_rules()) == {"weekly", "monthly"}
    monkeypatch.setattr(bot, "NUDGE_TIME", "07:30")
    assert bot.job_rules()["nudge"] == {"every": "day", "at": (7, 30)}


# ---- the reply under a new note ------------------------------------------------------

def saved_note(tmp_path, monkeypatch, actions, other_ideas=()):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    data = {"title": "Tool tips", "category": "tech", "summary": "s", "key_points": ["k"],
            "resources": [], "tags": [], "claims": [], "quote": "", "lesson": "", "habit": "",
            "other_ideas": list(other_ideas),
            "action_items": [{"text": t, "priority": "normal", "kind": "ai"} for t in actions]}
    return bot.processor.save_note(data, "", "", "https://x/1"), data


def test_new_note_reply_shows_type_icon_and_other_ideas_but_no_buttons(tmp_path, monkeypatch):
    path, data = saved_note(tmp_path, monkeypatch, ["Ask Claude to plan it"], ["Try the demo"])
    text = bot.format_reply(data, path)
    assert "☐ 🤖 Ask Claude to plan it" in text
    assert "Other ideas" in text and "• Try the demo" in text
    assert "pick ONE" not in text
    sent = {}
    async def edit_text(t, **kw): sent.update(text=t, kw=kw)
    asyncio.run(bot.send_note_reply(types.SimpleNamespace(edit_text=edit_text), data, path))
    assert sent["text"] == text and "reply_markup" not in sent["kw"]


def test_note_without_actions_has_no_action_section_in_reply(tmp_path, monkeypatch):
    path, data = saved_note(tmp_path, monkeypatch, [])
    assert "Action items" not in bot.format_reply(data, path)


# ---- action types in /todo -------------------------------------------------------------

def test_todo_shows_type_icons_and_filters_by_type(tmp_path, monkeypatch):
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    data = {"title": "Mixed", "category": "tech", "summary": "s", "key_points": ["k"],
            "resources": [], "tags": [], "claims": [], "quote": "", "lesson": "", "habit": "",
            "action_items": [{"text": "Ask Claude to plan it", "priority": "normal", "kind": "ai"}]}
    bot.processor.save_note(data, "", "", "https://x/1")
    data.update(title="Habits", action_items=[
        {"text": "Every morning, write 3 goals", "priority": "normal", "kind": "habit"}])
    bot.processor.save_note(data, "", "", "https://x/2")
    text, _ = bot.todo_page(1)
    assert "☐ 🤖 Ask Claude to plan it" in text and "☐ 🧠 Every morning" in text
    assert "🤖 1 ai can do it" in text
    only_ai, _ = bot.todo_page(1, kind="ai")
    assert "Ask Claude" in only_ai and "Every morning" not in only_ai
    none, _ = bot.todo_page(1, kind="lookup")
    assert none.startswith("No Look up / set up actions")


# ---- /cleanup ----------------------------------------------------------------------------

def cleanup_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    monkeypatch.setattr(bot.processor, "NOTES_DIR", tmp_path)
    (tmp_path / "2026-11-01_1000_old.md").write_text(
        "# Old\n\n- Date: 2026-11-01 10:00\n- Category: tech\n\n## Action items\n"
        "- [ ] 🔥 Keep me\n- [ ] Extra one\n- [ ] Comment 'FABLE' to get the link\n\n"
        "## Transcript\nx\n", encoding="utf-8")


def press_cleanup(data):
    replies, cleared = [], []
    async def answer(): pass
    async def edit_message_reply_markup(reply_markup=None): cleared.append(True)
    async def reply_text(t): replies.append(t)
    query = types.SimpleNamespace(data=data, answer=answer,
                                  edit_message_reply_markup=edit_message_reply_markup,
                                  message=types.SimpleNamespace(reply_text=reply_text))
    upd = types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.cleanup_button_pressed(upd, None))
    return replies, cleared


def test_cleanup_asks_first_then_skips(tmp_path, monkeypatch):
    cleanup_setup(tmp_path, monkeypatch)
    sent = []
    class Msg:
        async def reply_text(self, t, reply_markup=None): sent.append((t, reply_markup))
    upd = types.SimpleNamespace(message=Msg(), effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.cleanup(upd, None))
    text, markup = sent[0]
    assert "3 open actions" in text and "skip 2 and keep 1" in text
    assert [b.callback_data for b in markup.inline_keyboard[0]] == ["cleanup:yes", "cleanup:no"]
    assert len(bot.processor.open_actions()) == 3              # nothing changed yet
    replies, cleared = press_cleanup("cleanup:yes")
    assert "Skipped 2. 1 open actions left" in replies[0] and cleared
    assert [a["action"] for a in bot.processor.open_actions()] == ["Keep me"]
    replies, _ = press_cleanup("cleanup:yes")                   # pressed twice
    assert "Nothing left" in replies[0]


def test_cleanup_cancel_changes_nothing(tmp_path, monkeypatch):
    cleanup_setup(tmp_path, monkeypatch)
    replies, _ = press_cleanup("cleanup:no")
    assert "nothing changed" in replies[0] and len(bot.processor.open_actions()) == 3


def test_cleanup_command_is_registered():
    assert first_matching_handler("/cleanup") is not None


def test_weekly_review_hint_only_when_the_list_is_long(tmp_path, monkeypatch):
    cleanup_setup(tmp_path, monkeypatch)
    assert bot.cleanup_hint() == ""                              # only 3 open
    monkeypatch.setattr(bot, "CLEANUP_HINT_OVER", 2)
    assert "/cleanup" in bot.cleanup_hint() and "skip 2" in bot.cleanup_hint()
