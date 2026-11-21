"""'Done, with one line of what I learned': the question after a Done, and where the answer is saved."""
import asyncio
import itertools
import os
import types
from datetime import datetime
from pathlib import Path

import pytest
from telegram import ForceReply

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor as p  # noqa: E402

TODAY = f"{datetime.now():%Y-%m-%d}"


@pytest.fixture
def notes(tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    monkeypatch.setattr(bot, "ASK_LEARNING", True)
    return folder


def make_note(actions, title="Tool tips", source="https://x/1"):
    data = {"title": title, "category": "tech", "summary": "s", "key_points": ["k"], "resources": [],
            "tags": ["claude"], "claims": [], "other_ideas": [], "quote": "", "lesson": "", "habit": "",
            "action_items": p.clean_actions(actions)}
    return p.save_note(data, "transcript", "screen", source)


def done_index(lines, text):
    """Line number of the done action with this text (icons and dates do not matter)."""
    return next(n for n, ln in enumerate(lines) if p.done_line_text(ln) == text)


def tick(text):
    """Tick the open action with this text, like /done does. Returns its note."""
    actions = p.open_actions()
    n = next(i for i, a in enumerate(actions, 1) if a["action"] == text)
    p.complete_actions([n])
    return actions[n - 1]["path"]


# ---- cleaning what you type -------------------------------------------------------------------

@pytest.mark.parametrize("typed,expected", [
    ("  The docs have a quick\nstart page  ", "The docs have a quick start page"),
    ("- a leading bullet", "a leading bullet"),
    ("2) a number", "a number"),
    ("tab\tand\x00null", "tab and null"),
    ("two\n\nlines\n here", "two lines here"),
    ("skip", ""), ("Skip.", ""), ("NOTHING!", ""), ("no", ""), ("-", ""), ("", ""), ("   ", ""), (None, ""),
])
def test_clean_learning(typed, expected):
    assert p.clean_learning(typed) == expected


def test_a_long_learning_is_cut_to_one_short_line():
    one = p.clean_learning("word " * 200)
    assert len(one) == p.MAX_LEARNING and one.endswith("…") and "\n" not in one


@pytest.mark.parametrize("line,expected", [
    ("- [x] Read the docs ✅ 2026-11-20", "Read the docs"),
    ("- [x] 🔥 🧠 Every morning, write 3 goals 📅 2026-11-25 ✅ 2026-11-20", "Every morning, write 3 goals"),
    ("- [x] 🔽 🔗 Open the repo ✅ 2026-11-20", "Open the repo"),
    ("- [ ] Read the docs", None),
    ("- [-] Read the docs ❌ 2026-11-20", None),
    ("  - 💡 Learned: Read the docs", None),
    ("Read the docs", None),
])
def test_done_line_text(line, expected):
    assert p.done_line_text(line) == expected


# ---- saving it in the note ----------------------------------------------------------------------

def test_the_line_goes_right_under_the_done_action_and_nothing_else_changes(notes):
    path = make_note(["Read the docs", "Install the tool"])
    tick("Read the docs")
    before = path.read_text(encoding="utf-8").splitlines()
    assert p.add_learning(path.name, "Read the docs", "The docs have a quick start page") is True
    after = path.read_text(encoding="utf-8").splitlines()
    i = done_index(before, "Read the docs")
    assert after[i + 1] == "  - 💡 Learned: The docs have a quick start page"
    assert after[:i + 1] + after[i + 2:] == before                  # only ONE line was added
    assert [a["action"] for a in p.open_actions()] == ["Install the tool"]   # it is not a to-do


def test_a_second_answer_replaces_the_first(notes):
    path = make_note(["Read the docs"])
    tick("Read the docs")
    p.add_learning(path.name, "Read the docs", "first idea")
    p.add_learning(path.name, "Read the docs", "better idea")
    text = path.read_text(encoding="utf-8")
    assert text.count("💡 Learned") == 1 and "better idea" in text and "first idea" not in text


def test_works_with_priority_type_and_due_date(notes):
    path = make_note([{"text": "Write 3 goals", "priority": "high", "type": "habit"}])
    lines = path.read_text(encoding="utf-8").splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith("- [ ] 🔥 🧠 Write 3 goals"))
    lines[i] += " 📅 2026-12-24"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tick("Write 3 goals")
    assert "- [x] 🔥 🧠 Write 3 goals 📅 2026-12-24 ✅ " in path.read_text(encoding="utf-8")
    assert p.add_learning(path.name, "Write 3 goals", "It takes two minutes")


def test_with_the_same_text_ticked_twice_the_newest_tick_gets_it(notes):
    path = make_note(["Read the docs"])
    path.write_text(path.read_text(encoding="utf-8").replace(
        "## Action items\n", f"## Action items\n- [x] Read the docs ✅ 2026-01-01\n"), encoding="utf-8")
    tick("Read the docs")
    p.add_learning(path.name, "Read the docs", "now I know")
    lines = path.read_text(encoding="utf-8").splitlines()
    old = next(n for n, ln in enumerate(lines) if ln.endswith("✅ 2026-01-01"))
    new = next(n for n, ln in enumerate(lines) if ln.endswith(f"✅ {TODAY}"))
    assert not lines[old + 1].startswith(p.LEARNED_PREFIX)
    assert lines[new + 1] == p.LEARNED_PREFIX + "now I know"


def test_nothing_is_saved_when_it_cannot_be_matched(notes):
    path = make_note(["Read the docs"])
    original = path.read_text(encoding="utf-8")
    assert p.add_learning(path.name, "Read the docs", "idea") is False          # not done yet
    tick("Read the docs")
    original = path.read_text(encoding="utf-8")
    assert p.add_learning(path.name, "Some other action", "idea") is False
    assert p.add_learning("2020-01-01_0000_gone.md", "Read the docs", "idea") is False
    assert p.add_learning(path.name, "Read the docs", "skip") is False
    assert p.add_learning(path.name, "Read the docs", "") is False
    assert path.read_text(encoding="utf-8") == original


def test_a_note_waiting_on_the_pc_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path / "missing drive")
    pending = tmp_path / "private" / "pending"
    pending.mkdir(parents=True)
    note = pending / "2026-11-20_0900_x.md"
    note.write_text(f"# X\n\n## Action items\n- [x] Do it ✅ {TODAY}\n", encoding="utf-8")
    assert p.find_note_file(note.name) == note
    assert p.add_learning(note.name, "Do it", "it worked")
    assert "  - 💡 Learned: it worked" in note.read_text(encoding="utf-8")


def test_an_answer_that_looks_like_a_todo_cannot_become_one(notes):
    path = make_note(["Read the docs", "Install the tool"])
    tick("Read the docs")
    headings = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.startswith("## ")]
    p.add_learning(path.name, "Read the docs", "- [ ] steal this\n## Transcript")
    after = path.read_text(encoding="utf-8").splitlines()
    assert [a["action"] for a in p.open_actions()] == ["Install the tool"]       # no new to-do
    assert [ln for ln in after if ln.startswith("## ")] == headings               # no new heading
    assert sum(ln.startswith(p.LEARNED_PREFIX) for ln in after) == 1              # one indented line


def test_the_new_line_does_not_break_the_other_features(notes):
    path = make_note(["Read the docs", "Install the tool", "Try the demo"])
    tick("Read the docs")
    p.add_learning(path.name, "Read the docs", "quickstart exists")
    # a line was added, so later line numbers moved: ticking the next action must still be right
    tick("Try the demo")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert done_index(lines, "Read the docs") and done_index(lines, "Try the demo")
    assert p.done_line_text(lines[done_index(lines, "Read the docs") + 1]) is None      # the learning line
    assert lines[done_index(lines, "Read the docs") + 1].startswith(p.LEARNED_PREFIX)
    assert any(ln.startswith("- [ ] ") and "Install the tool" in ln for ln in lines)
    assert [a["action"] for a in p.open_actions()] == ["Install the tool"]
    assert p.weekly_stats()["done"] == 2
    assert p.search_notes("quickstart")[0]["title"] == "Tool tips"                 # chat and /ask can find it
    assert "quickstart exists" in p.note_summary_text(path)
    assert len(p.plan_parts(path)["actions"]) == 1


# ---- /month ----------------------------------------------------------------------------------------

def test_month_shows_what_you_learned(notes):
    path = make_note([f"Action {i}" for i in range(7)])
    for i in range(7):
        tick(f"Action {i}")
        p.add_learning(path.name, f"Action {i}", f"lesson {i}")
    assert p.stats_between(datetime.now().date(), datetime.now().date())["learned"][0] == "lesson 0"
    text = bot.month_text()
    assert "💡 What you learned:" in text and "• lesson 0" in text and "• lesson 4" in text
    assert "lesson 5" not in text and "...and 2 more" in text


def test_month_has_no_learned_part_without_learnings(notes):
    make_note(["Read the docs"])
    tick("Read the docs")
    assert "What you learned" not in bot.month_text()


# ---- the question in Telegram -------------------------------------------------------------------------

class Msg:
    """A Telegram message the bot can answer. Every answer is a new Msg with its own id."""
    ids = itertools.count(500)

    def __init__(self, text="", reply_to=None):
        self.text, self.reply_to_message, self.message_id = text, reply_to, next(Msg.ids)
        self.sent = []                                    # (text, reply_markup, the new Msg)

    async def reply_text(self, text, reply_markup=None, **kwargs):
        new = Msg(text)
        self.sent.append((text, reply_markup, new))
        return new


def context(args=None):
    async def typing(*a, **k):
        return None
    return types.SimpleNamespace(user_data={}, chat_data={}, args=args or [],
                                 bot=types.SimpleNamespace(send_chat_action=typing))


def command(ctx, args=None):
    msg = Msg("/done")
    ctx.args = args or []
    return types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1)), msg


def press_done(ctx, action):
    async def nothing(*a, **k):
        return None
    shown = []

    async def edit(text, **k):
        shown.append(text)
    message = Msg("nudge")
    query = types.SimpleNamespace(data=f"nudge:done:{p.action_id(action)}", answer=nothing,
                                  edit_message_text=edit, message=message)
    update = types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.nudge_button_pressed(update, ctx))
    return message, shown


def say(ctx, text, reply_to=None):
    msg = Msg(text, reply_to=reply_to)
    update = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1),
                                   effective_chat=types.SimpleNamespace(id=1))
    asyncio.run(bot.chat(update, ctx))
    return msg


@pytest.fixture
def chat_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(p, "chat_reply", lambda text, history: (calls.append(text) or "chat answer", []))
    return calls


def test_done_button_asks_and_the_reply_is_saved(notes, chat_calls):
    path = make_note(["Read the docs", "Install the tool"])
    ctx = context()
    message, shown = press_done(ctx, p.open_actions()[0])
    assert shown and "Done: Read the docs" in shown[0]
    text, markup, question = message.sent[0]
    assert "What did you learn?" in text and isinstance(markup, ForceReply)
    assert list(ctx.user_data["learn_q"].values()) == [{"note": path.name, "text": "Read the docs"}]
    answer = say(ctx, "The docs have a quick start page", reply_to=question)
    assert answer.sent[0][0] == "💡 Saved in the note. Well done!"
    assert "  - 💡 Learned: The docs have a quick start page" in path.read_text(encoding="utf-8")
    assert ctx.user_data["learn_q"] == {} and chat_calls == []         # not treated as a chat message


def test_slash_done_with_one_number_asks(notes):
    make_note(["Read the docs"])
    ctx = context()
    update, msg = command(ctx, ["1"])
    asyncio.run(bot.done(update, ctx))
    assert "Read the docs" in msg.sent[0][0] and "What did you learn?" in msg.sent[1][0]


def test_several_done_at_once_do_not_ask_and_skip_never_asks(notes):
    make_note(["Read the docs", "Install the tool", "Try the demo"])
    ctx = context()
    update, msg = command(ctx, ["1", "2"])
    asyncio.run(bot.done(update, ctx))
    assert len(msg.sent) == 1 and "learn_q" not in ctx.user_data
    update, msg = command(ctx, ["1"])
    asyncio.run(bot.skip(update, ctx))
    assert len(msg.sent) == 1 and "learn_q" not in ctx.user_data


def test_a_skip_button_on_a_nudge_does_not_ask(notes):
    make_note(["Read the docs"])
    ctx = context()
    action = p.open_actions()[0]

    async def nothing(*a, **k):
        return None
    message = Msg("nudge")
    query = types.SimpleNamespace(data=f"nudge:skip:{p.action_id(action)}", answer=nothing,
                                  edit_message_text=nothing, message=message)
    asyncio.run(bot.nudge_button_pressed(
        types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1)), ctx))
    assert message.sent == []


def test_it_can_be_switched_off(notes, monkeypatch):
    monkeypatch.setattr(bot, "ASK_LEARNING", False)
    make_note(["Read the docs", "Install the tool"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    update, msg = command(ctx, ["1"])
    asyncio.run(bot.done(update, ctx))
    assert message.sent == [] and len(msg.sent) == 1 and "learn_q" not in ctx.user_data


def test_replying_skip_saves_nothing_and_forgets_the_question(notes, chat_calls):
    path = make_note(["Read the docs"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    before = path.read_text(encoding="utf-8")
    answer = say(ctx, "skip", reply_to=message.sent[0][2])
    assert answer.sent[0][0] == "OK, no problem." and path.read_text(encoding="utf-8") == before
    assert ctx.user_data["learn_q"] == {} and chat_calls == []


def test_a_normal_message_is_never_taken_as_the_answer(notes, chat_calls):
    path = make_note(["Read the docs"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    before = path.read_text(encoding="utf-8")
    say(ctx, "what did I save about claude?")                         # not a reply: it is a chat message
    other = Msg("some other bot message")
    say(ctx, "thanks!", reply_to=other)                                # a reply to another message
    assert chat_calls == ["what did I save about claude?", "thanks!"]
    assert path.read_text(encoding="utf-8") == before
    assert len(ctx.user_data["learn_q"]) == 1                         # the question is still waiting


def test_one_question_takes_one_answer(notes, chat_calls):
    make_note(["Read the docs"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    question = message.sent[0][2]
    say(ctx, "first", reply_to=question)
    say(ctx, "second", reply_to=question)
    assert chat_calls == ["second"]                                    # the 2nd reply is just chat


def test_if_the_note_is_gone_you_are_told(notes, chat_calls):
    path = make_note(["Read the docs"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    path.unlink()
    answer = say(ctx, "an idea", reply_to=message.sent[0][2])
    assert "could not find that action" in answer.sent[0][0]


def test_if_the_notes_folder_is_not_reachable_the_question_stays(notes, monkeypatch, chat_calls):
    make_note(["Read the docs"])
    ctx = context()
    message, _ = press_done(ctx, p.open_actions()[0])
    question = message.sent[0][2]
    real = p.add_learning

    def offline(*args):
        raise OSError("Drive is offline")
    monkeypatch.setattr(p, "add_learning", offline)
    answer = say(ctx, "an idea", reply_to=question)
    assert "Reply again later" in answer.sent[0][0] and len(ctx.user_data["learn_q"]) == 1
    monkeypatch.setattr(p, "add_learning", real)
    assert "Saved" in say(ctx, "an idea", reply_to=question).sent[0][0]


def test_no_internet_while_asking_does_not_break_the_done(notes):
    make_note(["Read the docs"])
    ctx = context()

    class Offline(Msg):
        async def reply_text(self, text, reply_markup=None, **kwargs):
            raise bot.NetworkError("no internet")
    update, _ = command(ctx, ["1"])
    update.message = Offline("/done")
    update.message.sent = []
    asyncio.run(bot.ask_learning(update.message, ctx, p.open_actions()[0]))
    assert "learn_q" not in ctx.user_data


def test_only_the_newest_questions_are_remembered(notes):
    path = make_note(["Read the docs"])
    action = {"path": path, "action": "Read the docs"}
    ctx = context()
    message = Msg("x")
    for _ in range(bot.MAX_LEARN_QUESTIONS + 5):
        asyncio.run(bot.ask_learning(message, ctx, action))
    waiting = ctx.user_data["learn_q"]
    assert len(waiting) == bot.MAX_LEARN_QUESTIONS
    assert min(waiting) == message.sent[5][2].message_id              # the 5 oldest were forgotten


def test_the_question_is_short_and_simple():
    assert all(len(s.split()) <= 14 for s in bot.LEARN_QUESTION.replace("\n", " ").split(". "))
    assert "one line" in bot.LEARN_QUESTION and "skip" in bot.LEARN_QUESTION
