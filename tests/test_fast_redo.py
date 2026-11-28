"""/redo fast: make a note again from the text saved in it (no download, no Whisper, no OCR)."""
import asyncio
import os
import types
from datetime import datetime

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor as p  # noqa: E402

OLD_DATE = datetime(2026, 10, 5, 9, 30)
TRANSCRIPT = "[Slide 1] Strix finds security bugs. [Slide 2] (no speech)"
SCREEN = "[Slide 1]\ngithub.com/usestrix/strix\n## not a heading, just OCR\n```odd backticks```"
CAPTION = "Comment STRIX for the link\n## a caption line that looks like a heading"


@pytest.fixture
def notes(tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    # a fast redo must never download, listen or read the screen again
    for slow in ("download_media", "transcribe", "screen_text", "image_text"):
        monkeypatch.setattr(p, slow, lambda *a, **k: pytest.fail("a fast redo must not do this"))
    return folder


def old_note(actions=("Read the Strix docs page", "Install the Strix CLI tool", "Try the demo"),
             title="Strix Security Agent", category="tech", habit="", transcript=TRANSCRIPT,
             screen=SCREEN, caption=CAPTION, source="https://www.instagram.com/reel/ABC/",
             when=OLD_DATE, tags=("security", "my-renamed-tag")):
    data = {"title": title, "category": category, "summary": "old summary", "key_points": ["old point"],
            "resources": [], "tags": list(tags), "claims": [], "other_ideas": [], "quote": "",
            "lesson": "", "habit": habit, "action_items": p.clean_actions(list(actions)),
            "creator": "Ann Lee (@ann) https://www.instagram.com/ann", "video_count": 3, "photo_count": 2}
    return p.save_note(data, transcript, screen, source, "hi", caption, saved_at=when)


def tick(text, mark="x"):
    actions = p.open_actions()
    n = next(i for i, a in enumerate(actions, 1) if a["action"] == text)
    p.complete_actions([n], mark)


def fake_ai(monkeypatch, actions=("Read the Strix docs page today",), title="Strix: AI Security Testing",
            category="tech", habit="", tags=("ai-tools",)):
    seen = []

    def ask(prompt, schema=None):
        seen.append(prompt)
        return {"title": title, "category": category, "summary": "new summary", "key_points": ["new point"],
                "resources": [], "claims": [], "tags": list(tags), "habit": habit, "lesson": "l", "quote": "",
                "action_items": [{"text": t, "priority": "high", "type": "lookup"} for t in actions]}
    monkeypatch.setattr(p, "ask_ollama_json", ask)
    return seen


# ---- reading back what a note was made from ---------------------------------------------------------

def test_saved_inputs_reads_back_what_the_note_was_made_from(notes):
    saved = p.saved_inputs(old_note())
    assert saved["transcript"] == TRANSCRIPT
    assert saved["screen"] == SCREEN                       # a '## ' line inside the fence is kept
    assert saved["caption"] == CAPTION                     # a '## ' line in the caption is kept
    assert saved["source"] == "https://www.instagram.com/reel/ABC/"
    assert saved["creator"] == "Ann Lee (@ann) https://www.instagram.com/ann"
    assert (saved["language"], saved["video_count"], saved["photo_count"]) == ("hi", 3, 2)
    assert saved["date"] == OLD_DATE and saved["tags"] == ["security", "my-renamed-tag"]


def test_empty_markers_are_read_as_empty(notes):
    saved = p.saved_inputs(old_note(transcript="", screen="", caption="Only a caption"))
    assert (saved["transcript"], saved["screen"], saved["caption"]) == ("", "", "Only a caption")


def test_an_older_note_without_a_code_fence_still_works(notes):
    path = notes / "2026-09-01_1200_old.md"
    path.write_text("# Old\n\n- Date: 2026-09-01 12:00\n- Source: screenshot\n\n## Summary\ns\n\n"
                    "## Action items\n- [ ] Do it\n\n## Transcript\n(no speech)\n\n"
                    "## On-screen text\nplain OCR line\nsecond line\n\n## Post caption\nthe caption\n",
                    encoding="utf-8")
    saved = p.saved_inputs(path)
    assert saved["screen"] == "plain OCR line\nsecond line" and saved["caption"] == "the caption"
    assert saved["source"] == "screenshot" and saved["date"] == datetime(2026, 9, 1, 12, 0)
    assert (saved["video_count"], saved["photo_count"], saved["language"]) == (1, 0, "en")


def test_a_note_with_nothing_saved_cannot_be_redone_fast(notes):
    bare = notes / "2026-09-01_1200_bare.md"
    bare.write_text("# Bare\n\n## Summary\ns\n", encoding="utf-8")
    assert p.saved_inputs(bare) is None
    assert p.saved_inputs(old_note(transcript="", screen="", caption="")) is None
    with pytest.raises(p.RedoNotPossible, match="no saved transcript"):
        p.redo_from_saved(bare)
    assert bare.exists()


# ---- the redo itself ----------------------------------------------------------------------------------

def test_only_the_ai_runs_and_it_gets_the_same_text(notes, monkeypatch, capsys):
    path = old_note()
    prompts = fake_ai(monkeypatch)
    new, data = p.redo_from_saved(path)
    assert len(prompts) == 1
    for part in ("Strix finds security bugs", "github.com/usestrix/strix", "Comment STRIX for the link"):
        assert part in prompts[0]
    assert set(data["timings"]) == {"ai"} and "fast redo" in capsys.readouterr().out
    assert new == path and sorted(notes.rglob("*.md")) == [path]              # same file, no second copy


def test_date_source_creator_language_slides_and_tags_are_kept(notes, monkeypatch):
    path = old_note()
    fake_ai(monkeypatch, tags=("ai-tools", "other"))
    new, _ = p.redo_from_saved(path)
    text = new.read_text(encoding="utf-8")
    assert new == path                                                          # same file name and date
    assert text.startswith("# Strix: AI Security Testing\n")                       # the new AI title
    for line in ("- Date: 2026-10-05 09:30", "- Source: https://www.instagram.com/reel/ABC/",
                 "- Creator: Ann Lee (@ann) https://www.instagram.com/ann",
                 "- Language: hi (translated to English)", "- Slides: 5 (3 videos, 2 photos)",
                 "- Tags: #security #my-renamed-tag"):
        assert line in text, line
    assert p.saved_inputs(new)["transcript"] == TRANSCRIPT and p.saved_inputs(new)["screen"] == SCREEN
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/?igsh=x") == new


def test_done_skipped_and_learnings_are_kept_and_not_opened_again(notes, monkeypatch):
    path = old_note()
    tick("Read the Strix docs page")
    p.add_learning(path.name, "Read the Strix docs page", "The docs have a quick start")
    tick("Install the Strix CLI tool", "-")
    done_before = p.weekly_stats(datetime.now().date())["done"]
    fake_ai(monkeypatch, actions=["Read the Strix docs page today"])           # same idea as the done one
    new, _ = p.redo_from_saved(path)
    lines = new.read_text(encoding="utf-8").splitlines()
    done = next(i for i, ln in enumerate(lines) if ln.startswith("- [x]"))
    assert p._todo_text(lines[done]) == "Read the Strix docs page"             # the OLD done line
    assert lines[done + 1] == "  - 💡 Learned: The docs have a quick start"
    assert any(ln.startswith("- [-]") and "Install the Strix CLI tool" in ln for ln in lines)
    assert [a for a in p.open_actions() if a["path"] == new] == []             # nothing opened again
    assert p.weekly_stats(datetime.now().date())["done"] == done_before        # history still counts
    a_items, transcript = lines.index("## Action items"), lines.index("## Transcript")
    assert a_items < done < transcript                                          # inside the section


def test_a_new_idea_stays_open_next_to_the_old_history(notes, monkeypatch):
    path = old_note()
    tick("Read the Strix docs page")
    fake_ai(monkeypatch, actions=["Run Strix against a test website"])
    new, _ = p.redo_from_saved(path)
    open_now = [a["action"] for a in p.open_actions() if a["path"] == new]
    assert open_now == ["Run Strix against a test website"]
    assert "- [x] " in new.read_text(encoding="utf-8")


def test_a_done_habit_is_not_opened_again(notes, monkeypatch):
    habit = "Every morning, write down one limiting belief and replace it with a positive one."
    path = old_note(actions=[], category="motivation", habit=habit, title="Change Your Thoughts")
    tick(habit)
    fake_ai(monkeypatch, actions=[], category="motivation", title="Change Your Thoughts Now",
            habit="Each morning, write down one belief that limits you and replace it.")
    new, _ = p.redo_from_saved(path)
    text = new.read_text(encoding="utf-8")
    assert "## Habit to try\n- [x] " in text and habit in text
    assert [a for a in p.open_actions() if a["path"] == new] == []


def test_if_the_ai_fails_the_old_note_is_not_touched(notes, monkeypatch):
    path = old_note()
    before = path.read_text(encoding="utf-8")
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: {})
    with pytest.raises(RuntimeError):
        p.redo_from_saved(path)
    assert path.read_text(encoding="utf-8") == before and not (notes / "old").exists()


def test_if_saving_fails_the_old_note_is_put_back(notes, monkeypatch):
    path = old_note()
    before = path.read_text(encoding="utf-8")
    fake_ai(monkeypatch)

    def broken(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(p, "carry_over", broken)
    with pytest.raises(OSError):
        p.redo_from_saved(path)
    assert path.read_text(encoding="utf-8") == before
    assert list(notes.glob("*.md")) == [path] and list((notes / "old").glob("*.md")) == []


def test_another_note_with_the_same_name_is_never_overwritten(notes, monkeypatch):
    path = old_note()
    other = notes / "2026-10-05_0930_strix-ai-security-testing.md"
    other.write_text("# another note, do not touch\n", encoding="utf-8")
    fake_ai(monkeypatch)
    new, _ = p.redo_from_saved(path)
    assert new == path and not (notes / "2026-10-05_0930_strix-ai-security-testing_2.md").exists()
    assert other.read_text(encoding="utf-8") == "# another note, do not touch\n"


def test_a_screenshot_note_works_too(notes, monkeypatch):
    path = old_note(source="screenshot", transcript="", caption="", screen="Top 5 Python tips\n1. Use uv")
    fake_ai(monkeypatch, actions=["Install uv and make one project"])
    new, _ = p.redo_from_saved(path)
    assert "- Source: screenshot" in new.read_text(encoding="utf-8")


# ---- Telegram ---------------------------------------------------------------------------------------

class Msg:
    def __init__(self):
        self.sent, self.edits = [], []

    async def reply_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))

    async def edit_text(self, text, **kwargs):
        self.edits.append(text)


def send(ctx, *args):
    msg = Msg()
    ctx.args = list(args)
    asyncio.run(bot.redo(types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1)), ctx))
    return msg


def ctx(**user_data):
    return types.SimpleNamespace(user_data=dict(user_data), args=[])


def buttons(msg):
    return [b.callback_data for row in msg.sent[-1][1].inline_keyboard for b in row]


def test_slash_redo_fast_asks_first(notes):
    path = old_note()
    c = ctx()
    msg = send(c, "fast")                                                 # the newest note
    assert "from its saved text" in msg.sent[0][0] and "Done and skipped actions" in msg.sent[0][0]
    assert buttons(msg) == ["redo:fast", "redo:no"] and c.user_data["redo_path"] == str(path)
    c = ctx(last_results=[str(path)])
    assert buttons(send(c, "fast", "1")) == ["redo:fast", "redo:no"]     # /redo fast 1 (after /notes)
    c = ctx()
    send(c, "FAST", "strix")                                              # by title words
    assert c.user_data["redo_path"] == str(path)


def test_slash_redo_fast_without_saved_text(notes):
    (notes / "2026-09-01_1200_bare.md").write_text("# Bare\n\n## Summary\ns\n", encoding="utf-8")
    c = ctx()
    msg = send(c, "fast")
    assert msg.sent[0][0] == p.MSG_NO_SAVED_TEXT and "redo_path" not in c.user_data


def test_plain_redo_of_a_screenshot_note_suggests_fast(notes):
    old_note(source="screenshot")
    msg = send(ctx())
    assert "/redo fast" in msg.sent[0][0]


def press(c, data):
    message = Msg()

    async def ok():
        return None

    async def edit(text, **kwargs):
        message.edits.append(text)
    query = types.SimpleNamespace(data=data, answer=ok, edit_message_text=edit, message=message)
    asyncio.run(bot.redo_button_pressed(
        types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1)), c))
    return message


def test_the_fast_button_makes_the_note(notes, monkeypatch):
    path = old_note()
    fake_ai(monkeypatch)
    message = press(ctx(redo_path=str(path)), "redo:fast")
    assert "no download" in message.edits[0]
    assert message.edits[-1].startswith("📝 Strix: AI Security Testing") and "⏱" in message.edits[-1]
    assert path.read_text(encoding="utf-8").startswith("# Strix: AI Security Testing")
    assert not (notes / "old").exists()


def test_the_fast_button_reports_a_failure_and_keeps_the_note(notes, monkeypatch):
    path = old_note()
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: {})
    message = press(ctx(redo_path=str(path)), "redo:fast")
    assert "The old note was not changed." in message.edits[-1] and path.exists()


def test_cancel_keeps_the_note(notes):
    path = old_note()
    message = press(ctx(redo_path=str(path)), "redo:no")
    assert message.edits == ["OK, kept the note as it is."] and path.exists()
