"""Duplicate links: video IDs, the link index (link_index.json) and /dupes. No network."""
import asyncio
import json
import types

import pytest

import bot
import processor as p


@pytest.fixture
def notes(tmp_path, monkeypatch):
    folder = tmp_path / "notesdir"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(bot, "ALLOWED_USER_ID", "")
    return folder


def write(folder, name, source, title="T"):
    path = folder / name
    path.write_text(f"# {title}\n- Source: {source}\n\n## Summary\ns\n", encoding="utf-8")
    return path


# ---- video IDs -------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("https://www.instagram.com/reel/ABC123/", "https://www.instagram.com/reels/ABC123"),
    ("https://www.instagram.com/reel/ABC123/", "https://instagram.com/p/ABC123/?img_index=1"),
    ("https://www.instagram.com/reel/ABC123/", "https://www.instagram.com/tv/ABC123"),
    ("https://www.instagram.com/reel/ABC123/", "https://www.instagram.com/someone/reel/ABC123/"),
    ("https://www.instagram.com/reel/ABC123/?igsh=MWx0&utm_source=ig_web",
     "https://www.instagram.com/reel/ABC123#top"),
    ("https://www.tiktok.com/@ann/video/7301234567890?is_from_webapp=1",
     "https://m.tiktok.com/v/7301234567890.html"),
    ("https://www.youtube.com/watch?v=abcDEF12345&t=3", "https://youtu.be/abcDEF12345?si=x"),
    ("https://www.youtube.com/shorts/abcDEF12345", "https://m.youtube.com/watch?feature=share&v=abcDEF12345"),
    ("https://www.facebook.com/reel/1234567890/?mibextid=x", "https://www.facebook.com/watch/?v=1234567890"),
    ("https://www.facebook.com/someone/videos/1234567890/", "https://fb.watch/1234567890/"),
    ("https://x.com/ann/status/1234567890?s=20", "https://mobile.twitter.com/bob/status/1234567890"),
    ("https://example.com/Video/1/?ref=x", "https://example.com/video/1"),        # fallback: clean URL
])
def test_same_video_same_key(a, b):
    assert p.normalise_url(a) == p.normalise_url(b)


@pytest.mark.parametrize("url,key", [
    ("https://www.instagram.com/reels/AbC_1-z/", "instagram:AbC_1-z"),
    ("https://www.tiktok.com/@ann/video/7301234567890", "tiktok:7301234567890"),
    ("https://youtu.be/abcDEF12345", "youtube:abcDEF12345"),
    ("https://www.facebook.com/reel/987654321", "facebook:987654321"),
    ("https://twitter.com/ann/status/42", "x:42"),
    ("https://vm.tiktok.com/ZMabc/", "https://vm.tiktok.com/zmabc"),             # short link: no ID offline
])
def test_each_platform_key(url, key):
    assert p.normalise_url(url) == key


def test_different_videos_differ():
    assert p.normalise_url("https://www.instagram.com/reel/AAA/") != p.normalise_url("https://www.instagram.com/reel/BBB/")
    assert p.normalise_url("https://www.tiktok.com/@a/video/1") != p.normalise_url("https://www.tiktok.com/@a/video/2")


# ---- the index ---------------------------------------------------------------------------

def test_missing_index_is_rebuilt_from_source_lines(notes):
    write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    assert not p.LINK_INDEX_FILE.exists()
    assert p.find_note_by_source("https://www.instagram.com/reels/ABC?igsh=1").name == "2026-11-01_0900_a.md"
    data = json.loads(p.LINK_INDEX_FILE.read_text(encoding="utf-8"))
    assert data["links"]["instagram:ABC"] == [{"file": "2026-11-01_0900_a.md", "saved": "2026-11-01 09:00",
                                               "folder": "notes"}]


def test_broken_or_old_index_is_rebuilt(notes):
    write(notes, "2026-11-01_0900_a.md", "https://youtu.be/abcDEF12345")
    p.LINK_INDEX_FILE.write_text("{not json", encoding="utf-8")
    assert p.find_note_by_source("https://www.youtube.com/shorts/abcDEF12345")
    data = json.loads(p.LINK_INDEX_FILE.read_text(encoding="utf-8"))
    data["version"] = 0
    data["links"] = {}
    p.LINK_INDEX_FILE.write_text(json.dumps(data), encoding="utf-8")
    assert p.find_note_by_source("https://youtu.be/abcDEF12345")                 # old version: rebuilt


def test_deleted_note_is_dropped_and_older_note_is_found(notes):
    old = write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    new = write(notes, "2026-11-05_1000_a.md", "https://www.instagram.com/p/ABC/")
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/") == new  # newest first
    new.unlink()
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/") == old
    old.unlink()
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/") is None


def test_note_added_by_hand_is_found(notes):
    write(notes, "2026-11-01_0900_a.md", "https://x.com/a/status/1")
    assert p.find_note_by_source("https://x.com/a/status/2") is None             # index built now
    write(notes, "2026-11-02_0900_b.md", "https://x.com/a/status/2")
    assert p.find_note_by_source("https://twitter.com/a/status/2").name == "2026-11-02_0900_b.md"


def test_saved_note_is_added_without_a_rebuild(notes, monkeypatch):
    p.load_link_index()                                                        # build an empty index
    data = {"title": "Tip", "category": "tech", "summary": "s", "key_points": [], "resources": [],
            "tags": [], "claims": [], "action_items": [], "quote": "", "lesson": "", "habit": ""}
    path = p.save_note(data, "t", "s", "https://www.tiktok.com/@a/video/77")
    monkeypatch.setattr(p, "rebuild_link_index", lambda: pytest.fail("should not rebuild"))
    assert p.find_note_by_source("https://m.tiktok.com/v/77.html") == path


def test_moved_from_pending_updates_the_folder(notes, monkeypatch):
    p.PENDING_DIR.mkdir(parents=True)
    write(p.PENDING_DIR, "2026-11-03_0800_p.md", "https://www.facebook.com/reel/55")
    assert p.load_link_index()["links"]["facebook:55"][0]["folder"] == "pending"
    monkeypatch.setattr(p, "notes_ready", lambda: True)
    assert p.sync_pending() == 1
    entry = json.loads(p.LINK_INDEX_FILE.read_text(encoding="utf-8"))["links"]["facebook:55"][0]
    assert entry["folder"] == "notes"
    assert p.find_note_by_source("https://fb.watch/55/") == notes / "2026-11-03_0800_p.md"


def test_screenshot_notes_are_not_indexed(notes):
    write(notes, "2026-11-01_0900_s.md", "screenshot")
    assert p.load_link_index()["links"] == {}


def test_index_never_edits_notes(notes):
    path = write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    before = path.read_text(encoding="utf-8")
    p.rebuild_link_index()
    p.duplicate_notes()
    assert path.read_text(encoding="utf-8") == before


# ---- /dupes ------------------------------------------------------------------------------

def run_dupes():
    replies = []
    async def reply(text, **kw): replies.append(text)
    upd = types.SimpleNamespace(message=types.SimpleNamespace(reply_text=reply),
                                effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.dupes(upd, None))
    return "\n".join(replies)


def test_dupes_lists_videos_with_more_than_one_note_and_deletes_nothing(notes):
    write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    write(notes, "2026-11-04_1200_a_2.md", "https://www.instagram.com/reels/ABC?igsh=z")
    write(notes, "2026-11-02_0900_b.md", "https://youtu.be/abcDEF12345")
    text = run_dupes()
    assert "Videos with more than one note: 1" in text
    assert "• 2026-11-01_0900_a.md (2026-11-01 09:00)" in text
    assert "• 2026-11-04_1200_a_2.md (2026-11-04 12:00)" in text
    assert "_b.md" not in text and "Nothing was deleted" in text
    assert len(list(notes.glob("*.md"))) == 3


def test_dupes_when_there_are_none(notes):
    write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    assert run_dupes() == "👍 No duplicates: every video has one note."


# ---- check before any download ---------------------------------------------------------

def test_reels_link_of_a_saved_reel_is_not_downloaded(notes, monkeypatch):
    write(notes, "2026-11-01_0900_a.md", "https://www.instagram.com/reel/ABC/")
    downloads, replies = [], []
    async def fake_link(status, u): downloads.append(u)
    monkeypatch.setattr(bot, "note_from_link", fake_link)
    async def reply(text, reply_markup=None): replies.append(text)
    msg = types.SimpleNamespace(text="https://www.instagram.com/reels/ABC/?igsh=x", reply_text=reply)
    upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1))
    asyncio.run(bot.handle_link(upd, types.SimpleNamespace(user_data={})))
    assert downloads == [] and replies[0].startswith("📌 Already saved")
