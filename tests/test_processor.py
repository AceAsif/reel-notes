"""Tests for processor.py's pure logic (no Whisper, Ollama, Tesseract or network).

Run with:  python -m pytest
"""
import sys
import types
from pathlib import Path

import pytest

# Heavy libraries aren't needed for these tests: replace them with stand-ins
sys.modules.setdefault("pytesseract", types.SimpleNamespace(pytesseract=types.SimpleNamespace()))
sys.modules.setdefault("faster_whisper", types.SimpleNamespace(WhisperModel=None))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import processor as p  # noqa: E402


@pytest.fixture
def notes(tmp_path, monkeypatch):
    """An empty notes folder for each test, plus a no-network GitHub lookup."""
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    return folder


def make_note(category="tech", actions=None, title="Test Note", source="https://x/1", **extra):
    data = {"title": title, "category": category, "summary": "s", "key_points": ["k"],
            "resources": [], "tags": ["claude"], "claims": [],
            "action_items": p.clean_actions(actions or ["Do one thing"]),
            "quote": "", "lesson": "", "habit": ""}
    data.update(extra)
    return p.save_note(data, "transcript", "screen", source)


# ---- cleaning AI output -----------------------------------------------------

def test_clean_tags():
    assert p.clean_tags(["#AI Tools", "Python ", "python", "GitHub!!", " "]) == \
        ["ai-tools", "python", "github"]


def test_clean_actions_accepts_strings_objects_and_bad_priorities():
    out = p.clean_actions(["plain", {"text": "hi", "priority": "high"},
                           {"text": "odd", "priority": "URGENT"}, {"text": ""}])
    assert [(a["text"], a["priority"]) for a in out] == \
        [("plain", "normal"), ("hi", "high"), ("odd", "normal")]


def test_clean_claims_limits_to_four():
    out = p.clean_claims([{"claim": f"c{i}", "why": "w"} for i in range(6)])
    assert len(out) == 4 and out[0] == {"claim": "c0", "why": "w"}


def test_fenced_survives_backticks():
    lines = p.fenced("a ``` b")
    assert lines[0] == "````text" and lines[-1] == "````"


def test_invented_link_dropped_real_link_kept():
    res = [{"name": "Real", "link": "https://openai.com/blog"},
           {"name": "Fake", "link": "https://madeup.io"}]
    out = p.drop_invented_links(res, "see openai.com/blog for more")
    assert out[0]["link"] and out[1]["link"] == ""


# ---- notes, actions, search -------------------------------------------------

def test_duplicate_check_ignores_tracking(notes):
    path = make_note(source="https://www.instagram.com/reel/ABC/")
    assert p.find_note_by_source("https://www.instagram.com/reel/ABC/?igsh=zz") == path


def test_priorities_sort_and_done(notes):
    make_note(actions=[{"text": "low one", "priority": "low"},
                       {"text": "high one", "priority": "high"}, "normal one"])
    assert [a["action"] for a in p.open_actions()] == ["high one", "normal one", "low one"]
    assert p.complete_actions([1]) == ["high one"]
    assert [a["action"] for a in p.open_actions()] == ["normal one", "low one"]


def test_set_priority(notes):
    make_note(actions=["a", "b"])
    p.set_priority([2], "high")
    assert [a["action"] for a in p.open_actions()] == ["b", "a"]


def test_skip_hides_action(notes):
    path = make_note(actions=["a", "b"])
    p.complete_actions([1], "-")
    assert [a["action"] for a in p.open_actions()] == ["b"]
    assert "- [-] a" in path.read_text(encoding="utf-8")


def test_caption_checkbox_is_not_an_action(notes):
    path = make_note(actions=["real"])
    path.write_text(path.read_text(encoding="utf-8") + "\n## Post caption\n- [ ] fake\n",
                    encoding="utf-8")
    assert [a["action"] for a in p.open_actions()] == ["real"]


def test_search_and_tags(notes):
    make_note(title="Strix Security")
    assert p.search_notes("strix")[0]["title"] == "Strix Security"
    assert p.notes_with_tag("#Claude") and p.all_tags() == [("claude", 1)]


def test_motivation_habit_counts_as_action(notes):
    make_note(category="motivation", actions=["act"], quote="q", lesson="l",
              habit="Every Monday, do X", quote_exact=True)
    assert "Every Monday, do X" in [a["action"] for a in p.open_actions()]
