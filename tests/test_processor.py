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


@pytest.mark.parametrize("text,expected", [
    ("Check the broadcast channel and Telegram from the bio for the plugins", "low"),
    ("Comment CLAUDE below to get the list", "low"),
    ("Follow the creator for more tips", "low"),
    ("Follow the instructions to install and load a local model", "high"),
    ("Read the Strix README", "high"),
])
def test_low_priority_fallback(text, expected):
    assert p.clean_actions([{"text": text, "priority": "high"}])[0]["priority"] == expected


def test_min_search_stars_blocks_small_namesake():
    assert p.MIN_SEARCH_STARS >= 100


def test_rename_tag_and_merge(notes):
    a = make_note(title="A", source="https://x/a", tags=["claudie", "github"])
    b = make_note(title="B", source="https://x/b", tags=["claudie", "claude"])
    assert p.rename_tag("#Claudie", "claude") == 2
    assert p.read_tags(a) == ["claude", "github"]
    assert p.read_tags(b) == ["claude"]            # merged, no duplicate
    assert p.rename_tag("missing", "x") == 0


def test_done_date_and_weekly_stats(notes):
    from datetime import date
    path = make_note(actions=["a", "b", "c"], tags=["python"])
    p.complete_actions([1])            # done today
    p.complete_actions([1], "-")       # skipped today
    text = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    assert f"- [x] a ✅ {today}" in text and f"- [-] b ❌ {today}" in text
    s = p.weekly_stats()
    assert (s["saved"], s["done"], s["skipped"], s["open"]) == (1, 1, 1, 1)
    assert s["categories"] == {"tech": 1} and s["top_tags"] == [("python", 1)]


def test_weekly_stats_ignores_old_notes(notes):
    old = notes / "2020-01-01_0000_old.md"
    old.write_text("# Old\n\n- Category: tech\n\n## Action items\n- [x] x ✅ 2020-01-01\n",
                   encoding="utf-8")
    s = p.weekly_stats()
    assert s["saved"] == 0 and s["done"] == 0


def test_nudge_prefers_high_and_rotates(notes):
    from datetime import date
    make_note(actions=["n1", {"text": "h1", "priority": "high"},
                       {"text": "h2", "priority": "high"}])
    picks = {p.pick_nudge(today=date(2026, 1, d))["action"] for d in (1, 2)}
    assert picks == {"h1", "h2"}                     # only high ones, rotating daily
    first = p.pick_nudge(today=date(2026, 1, 1))
    nxt = p.pick_nudge(after=p.action_id(first))
    assert nxt["action"] != first["action"]


def test_find_action_and_tick_by_id(notes):
    make_note(actions=["a", "b"])
    a = p.open_actions()[1]
    n, found = p.find_action(p.action_id(a))
    assert n == 2 and found["action"] == "b"
    p.complete_actions([n])
    assert p.find_action(p.action_id(a)) is None     # done now


def test_pick_slides_prefers_video_and_keeps_photos(tmp_path):
    for name in ["item_1.mp4", "item_1.jpg",     # video slide + its cover image
                 "item_2.jpg",                   # photo slide
                 "item_10.webp", "item_3.mp4"]:
        (tmp_path / name).write_bytes(b"x")
    assert [s.name for s in p.pick_slides(tmp_path)] == \
        ["item_1.mp4", "item_2.jpg", "item_3.mp4", "item_10.webp"]


def test_mixed_post_note(notes, monkeypatch, tmp_path):
    slides = [tmp_path / "item_1.mp4", tmp_path / "item_2.jpg"]
    monkeypatch.setattr(p, "transcribe", lambda v: ("spoken words", "en"))
    monkeypatch.setattr(p, "screen_text", lambda v, w: "video text")
    monkeypatch.setattr(p, "image_text", lambda i, w: "photo text")
    seen = {}
    def fake_ai(prompt):
        seen["prompt"] = prompt
        return {"title": "Mixed", "category": "tech", "summary": "s", "key_points": [],
                "resources": [], "action_items": ["a"], "tags": []}
    monkeypatch.setattr(p, "ask_ollama_json", fake_ai)
    path, data = p.process_videos(slides, "https://x/p/1")
    assert (data["video_count"], data["photo_count"]) == (1, 1)
    assert "[Slide 2 · photo]" in seen["prompt"] and "photo text" in seen["prompt"]
    assert "- Slides: 2 (1 video, 1 photo)" in path.read_text(encoding="utf-8")


def test_slide_summary():
    assert p.slide_summary({"video_count": 4, "photo_count": 0}) == "4 videos"
    assert p.slide_summary({"video_count": 0, "photo_count": 3}) == "3 photos"


@pytest.mark.parametrize("a,b,same", [
    ("https://www.youtube.com/shorts/abcDEF12345", "https://youtu.be/abcDEF12345?si=x", True),
    ("https://www.youtube.com/watch?v=abcDEF12345&t=3", "https://m.youtube.com/shorts/abcDEF12345", True),
    ("https://www.youtube.com/watch?v=abcDEF12345", "https://www.youtube.com/watch?v=zzzzzzzzzzz", False),
    ("https://www.instagram.com/reel/ABC/?igsh=1", "https://www.instagram.com/reel/abc", True),
])
def test_normalise_url(a, b, same):
    assert (p.normalise_url(a) == p.normalise_url(b)) is same


def test_long_videos_filtered():
    import yt_dlp
    f = yt_dlp.utils.match_filter_func(f"duration <=? {p.MAX_MINUTES * 60}")
    assert f({"duration": 45}) is None                   # short: accepted
    assert f({"duration": 3600}) is not None             # 1 hour: rejected
    assert f({}) is None                                 # unknown length: accepted


def test_question_words_drop_filler():
    assert p.question_words("Which tools help Claude remember things?") == \
        ["tools", "help", "claude", "remember", "things"]


def test_ask_no_matching_notes_skips_ai(notes, monkeypatch):
    make_note(title="Strix Security")
    monkeypatch.setattr(p, "ask_ollama_json", lambda pr: pytest.fail("AI should not be asked"))
    assert p.answer_question("how do I bake bread?") == (p.NOT_FOUND, [])


def test_ask_uses_matching_notes_and_sources(notes, monkeypatch):
    a = make_note(title="Claude Memory Plugin", source="https://x/a")
    make_note(title="Strix Security", source="https://x/b")
    seen = {}
    def fake_ai(prompt):
        seen["prompt"] = prompt
        return {"answer": "Use Claude mem.", "sources": [1, 99]}   # 99 is invalid
    monkeypatch.setattr(p, "ask_ollama_json", fake_ai)
    answer, sources = p.answer_question("Which plugin gives Claude memory?")
    assert answer == "Use Claude mem." and sources == [a]
    assert "Claude Memory Plugin" in seen["prompt"] and "## Transcript" not in seen["prompt"]


def test_ask_ai_says_not_found(notes, monkeypatch):
    make_note(title="Claude Memory Plugin")
    monkeypatch.setattr(p, "ask_ollama_json", lambda pr: {"answer": p.NOT_FOUND, "sources": []})
    assert p.answer_question("claude pricing?") == (p.NOT_FOUND, [])


def test_ask_drops_weak_matches(notes, monkeypatch):
    strong = make_note(title="Claude Memory Plugin Claude Memory", source="https://x/a")
    make_note(title="Cooking", source="https://x/b", tags=["food"],
              key_points=["memory of grandma's food"])
    seen = {}
    monkeypatch.setattr(p, "ask_ollama_json",
                        lambda pr: seen.setdefault("p", pr) and {"answer": "x", "sources": []})
    p.answer_question("claude memory plugin")
    assert "Claude Memory Plugin" in seen["p"] and "Cooking" not in seen["p"]
