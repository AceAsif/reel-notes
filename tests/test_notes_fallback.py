"""When the notes folder is missing (Google Drive not running), notes are kept on the PC."""
import asyncio
import os
import types
from pathlib import Path

import pytest
import requests

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor as p  # noqa: E402


@pytest.fixture
def gone(tmp_path, monkeypatch):
    """A notes folder that cannot be made, like a folder on drive G: when G: is missing.
    (Its parent is a plain file, so creating the folder fails with an OSError.)"""
    (tmp_path / "no_such_drive").write_text("x")
    folder = tmp_path / "no_such_drive" / "Reel Notes"
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    return folder


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """A notes folder that works."""
    folder = tmp_path / "drive" / "Reel Notes"
    folder.mkdir(parents=True)
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    return folder


def note(title="Tool tips", source="https://x/1"):
    data = {"title": title, "category": "tech", "summary": "s", "key_points": ["k"], "resources": [],
            "tags": ["claude"], "claims": [], "other_ideas": [], "quote": "", "lesson": "", "habit": "",
            "action_items": p.clean_actions(["Read the docs"])}
    return p.save_note(data, "transcript", "screen", source), data


# ---- saving -------------------------------------------------------------------------------------

def test_note_goes_to_the_pending_folder_when_the_notes_folder_is_missing(gone, capsys):
    path, _ = note()
    assert path.parent == p.PENDING_DIR and path.exists()
    assert "# Tool tips" in path.read_text(encoding="utf-8")
    assert p.is_pending(path) and p.pending_notes() == [path]
    log = capsys.readouterr().out
    assert " notes: notes folder not available" in log and path.name in log   # the real error is logged


def test_note_goes_to_the_notes_folder_when_it_works(drive):
    path, _ = note()
    assert path.parent == drive and not p.is_pending(path) and p.pending_notes() == []


class _FixedTime(p.datetime):
    """The clock stops, so two notes are surely saved in the same minute."""
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 2, 9, 30, 15)


def test_two_notes_with_the_same_title_in_the_same_minute_are_both_kept(drive, monkeypatch):
    monkeypatch.setattr(p, "datetime", _FixedTime)
    first, _ = note(source="https://x/1")
    second, _ = note(source="https://x/2")
    third, _ = note(source="https://x/3")
    assert first.name == "2026-01-02_0930_tool-tips.md"
    assert second.name == "2026-01-02_0930_tool-tips_2.md"
    assert third.name == "2026-01-02_0930_tool-tips_3.md"
    assert sorted(drive.glob("*.md")) == [first, second, third]
    assert [p.note_source(f) for f in (first, second, third)] == ["https://x/1", "https://x/2", "https://x/3"]
    assert len(p.open_actions()) == 3                               # no action is lost


def test_same_title_in_the_same_minute_is_also_kept_in_the_pending_folder(gone, monkeypatch):
    monkeypatch.setattr(p, "datetime", _FixedTime)
    first, _ = note(source="https://x/1")
    second, _ = note(source="https://x/2")
    assert second.name == "2026-01-02_0930_tool-tips_2.md"
    assert p.pending_notes() == [first, second]
    assert [p.note_source(f) for f in (first, second)] == ["https://x/1", "https://x/2"]


def test_a_folder_that_exists_but_cannot_be_written_also_falls_back(drive, monkeypatch):
    real = Path.write_text

    def fail_in_drive(self, *args, **kwargs):
        if self.parent == drive:
            raise PermissionError("Drive is offline")
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_in_drive)
    path, _ = note()
    assert p.is_pending(path) and path.exists()


def test_the_whole_pipeline_works_without_the_notes_folder(gone, tmp_path, monkeypatch):
    """The real failure: a link was downloaded, listened to and summarised, then lost at the end."""
    monkeypatch.setattr(p, "transcribe", lambda v: ("spoken words", "en"))
    monkeypatch.setattr(p, "screen_text", lambda v, w: "on screen")
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: {
        "title": "Rich vs Poor", "category": "tech", "summary": "s", "key_points": ["k"],
        "resources": [], "action_items": [], "claims": [], "tags": []})
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    path, data = p.process_videos([video], "https://www.instagram.com/reel/ABC/")
    assert p.is_pending(path) and data["title"] == "Rich vs Poor"


def test_if_even_the_pending_folder_fails_the_error_is_shown(gone, tmp_path, monkeypatch):
    (tmp_path / "also_a_file").write_text("x")
    monkeypatch.setattr(p, "PENDING_DIR", tmp_path / "also_a_file" / "pending")
    with pytest.raises(OSError):
        note()


def test_a_reel_saved_while_the_folder_was_missing_is_not_saved_twice(gone):
    path, _ = note(source="https://www.instagram.com/reel/ABC/?igsh=x")
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/") == path


# ---- moving the notes back ---------------------------------------------------------------------------

def test_notes_move_to_the_notes_folder_when_it_is_back(gone, tmp_path, monkeypatch, capsys):
    a, _ = note("First note", "https://x/1")
    b, _ = note("Second note", "https://x/2")
    texts = {a.name: a.read_text(encoding="utf-8"), b.name: b.read_text(encoding="utf-8")}
    assert p.sync_pending() == 0 and len(p.pending_notes()) == 2     # still missing: nothing is lost
    drive = tmp_path / "drive" / "Reel Notes"
    drive.mkdir(parents=True)
    monkeypatch.setattr(p, "NOTES_DIR", drive)                       # Google Drive is back
    assert p.sync_pending() == 2
    assert p.pending_notes() == []
    for name, text in texts.items():
        assert (drive / name).read_text(encoding="utf-8") == text
    assert "moved 2 note(s)" in capsys.readouterr().out
    assert p.sync_pending() == 0                                      # nothing left to do


def test_a_note_with_the_same_name_is_never_overwritten(gone, tmp_path, monkeypatch):
    waiting, _ = note("Same title")
    drive = tmp_path / "drive"
    drive.mkdir()
    (drive / waiting.name).write_text("# older note, do not touch\n", encoding="utf-8")
    monkeypatch.setattr(p, "NOTES_DIR", drive)
    assert p.sync_pending() == 1
    assert (drive / waiting.name).read_text(encoding="utf-8") == "# older note, do not touch\n"
    assert (drive / f"{waiting.stem}_2.md").read_text(encoding="utf-8").startswith("# Same title")


def test_a_failed_move_keeps_the_note_on_the_pc(gone, tmp_path, monkeypatch, capsys):
    a, _ = note("First note", "https://x/1")
    b, _ = note("Second note", "https://x/2")
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", drive)
    real = p.shutil.copy2
    calls = []

    def flaky(src, dst):
        calls.append(src)
        if len(calls) == 2:
            raise OSError("Drive stopped")
        return real(src, dst)
    monkeypatch.setattr(p.shutil, "copy2", flaky)
    assert p.sync_pending() == 1
    assert len(p.pending_notes()) == 1 and p.pending_notes()[0].exists()      # not deleted
    assert "could not move" in capsys.readouterr().out
    monkeypatch.setattr(p.shutil, "copy2", real)
    assert p.sync_pending() == 1 and p.pending_notes() == []                    # tried again, worked


def test_a_bad_copy_is_not_trusted(gone, tmp_path, monkeypatch):
    a, _ = note()
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", drive)
    monkeypatch.setattr(p.shutil, "copy2", lambda src, dst: Path(dst).write_text("cut"))
    assert p.sync_pending() == 0
    assert a.exists() and list(drive.glob("*.md")) == []                        # the cut copy is removed


def test_nothing_is_moved_when_pending_is_the_notes_folder(tmp_path, monkeypatch):
    same = tmp_path / "same"
    same.mkdir()
    (same / "x.md").write_text("# x\n")
    monkeypatch.setattr(p, "NOTES_DIR", same)
    monkeypatch.setattr(p, "PENDING_DIR", same)
    assert p.sync_pending() == 0 and (same / "x.md").exists()


# ---- what the user sees ----------------------------------------------------------------------------

def reply_data():
    return {"title": "Tool tips", "category": "tech", "summary": "s", "key_points": [],
            "resources": [], "action_items": []}


def test_the_reply_warns_only_for_a_note_kept_on_the_pc(gone):
    kept, _ = note()
    text = bot.format_reply(reply_data(), kept)
    assert "saved on this PC and moves there when it is back" in text and "Google Drive" in text


def test_the_reply_has_no_warning_for_a_normal_note(drive):
    path, _ = note()
    assert "saved on this PC" not in bot.format_reply(reply_data(), path)


def test_the_missing_folder_message_says_what_happens_and_how_many_wait(gone):
    text = bot.todo_page()[0]
    assert "Is Google Drive running?" in text and "New reels are still saved on this PC" in text
    assert "waiting" not in text
    note("One", "https://x/1")
    note("Two", "https://x/2")
    assert "💾 2 notes waiting on this PC" in bot.todo_page()[0]
    for f in p.pending_notes()[1:]:
        f.unlink()
    assert "💾 1 note waiting on this PC" in bot.todo_page()[0]


def test_health_shows_the_waiting_notes(gone, monkeypatch):
    def no_ollama(*args, **kwargs):
        raise requests.ConnectionError()
    monkeypatch.setattr(p.requests, "get", no_ollama)
    assert not any(name == "Notes waiting on this PC" for _, name, _ in p.health_checks())
    note()
    waiting = [c for c in p.health_checks() if c[1] == "Notes waiting on this PC"]
    assert waiting and waiting[0][0] is False and waiting[0][2].startswith("1.")


# ---- the bot moves the notes by itself and says so ----------------------------------------------------

class Ctx:
    def __init__(self):
        self.sent = []
        self.bot = types.SimpleNamespace(send_message=self.send)
        self.job = types.SimpleNamespace(chat_id=42)

    async def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def test_the_regular_check_moves_waiting_notes_and_tells_you_once(gone, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "job_rules", lambda: {})
    note("One", "https://x/1")
    note("Two", "https://x/2")
    ctx = Ctx()
    asyncio.run(bot.run_due_jobs(ctx))
    assert ctx.sent == [] and len(p.pending_notes()) == 2            # Drive still missing: quiet
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", drive)
    asyncio.run(bot.run_due_jobs(ctx))
    assert ctx.sent == [(42, "📁 Your notes folder is back. Moved 2 notes from this PC to it.")]
    assert len(list(drive.glob("*.md"))) == 2 and p.pending_notes() == []
    asyncio.run(bot.run_due_jobs(ctx))
    assert len(ctx.sent) == 1                                        # no second message


def test_a_lost_message_does_not_undo_the_move(gone, tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "job_rules", lambda: {})
    note()
    drive = tmp_path / "drive"
    drive.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", drive)
    ctx = Ctx()

    async def offline(chat_id, text, **kwargs):
        raise bot.NetworkError("no internet")
    ctx.bot.send_message = offline
    asyncio.run(bot.run_due_jobs(ctx))
    assert len(list(drive.glob("*.md"))) == 1 and p.pending_notes() == []
