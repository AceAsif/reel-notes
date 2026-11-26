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
    monkeypatch.setattr(p, "CLEANUP_UNDO_FILE", tmp_path / "cleanup_undo.json")
    monkeypatch.setattr(p, "STATE_FILE", tmp_path / "bot_state.json")
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


def test_invented_tool_name_marked_unverified():
    res = [{"name": "Claude-Mem", "link": ""}, {"name": "SuperFakeTool", "link": ""}]
    out = p.mark_unverified_names(res, "install claude mem today")
    assert "unverified" not in out[0]
    assert out[1]["unverified"]
    assert p.resource_line(out[1]).startswith("SuperFakeTool (unverified) ")
    assert "(unverified)" not in p.resource_line(out[0])


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
    assert "- [-] 🔗 a" in path.read_text(encoding="utf-8")


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
    assert f"- [x] 🔗 a ✅ {today}" in text and f"- [-] 🔗 b ❌ {today}" in text
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
    def fake_ai(prompt, schema=None):
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
    def fake_ai(prompt, schema=None):
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


# ---- reminders ----------------------------------------------------------------
from datetime import datetime as _dt  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

NOW = _dt(2026, 11, 13, 22, 30, tzinfo=ZoneInfo("UTC"))   # Friday night


@pytest.mark.parametrize("text,expected", [
    ("friday", "2026-11-20 09:00"),          # it's Friday 10:30pm: next Friday
    ("fri 11pm", "2026-11-13 23:00"),        # later today
    ("monday", "2026-11-16 09:00"),
    ("mon 5:30pm", "2026-11-16 17:30"),
    ("tomorrow", "2026-11-14 09:00"),
    ("tomorrow evening", "2026-11-14 19:00"),
    ("tonight", "2026-11-13 19:00"),
    ("next week", "2026-11-16 09:00"),
    ("in 3 days", "2026-11-16 09:00"),
    ("in 2 hours", "2026-11-14 00:30"),
    ("in 1 week", "2026-11-20 09:00"),
    ("20/11", "2026-11-20 09:00"),
    ("5/1", "2027-01-05 09:00"),             # already past this year: next year
    ("20/11/2027 8am", "2027-11-20 08:00"),
    ("2026-12-25", "2026-12-25 09:00"),
    ("25 dec", "2026-12-25 09:00"),
    ("dec 25 at 6pm", "2026-12-25 18:00"),
    ("7am", "2026-11-14 07:00"),             # time only, already passed today
])
def test_parse_when(text, expected):
    assert p.parse_when(text, NOW).strftime("%Y-%m-%d %H:%M") == expected


@pytest.mark.parametrize("text", ["someday", "31/02", "blah blah"])
def test_parse_when_unknown(text):
    assert p.parse_when(text, NOW) is None


def test_reminder_store(notes, tmp_path, monkeypatch):
    monkeypatch.setattr(p, "REMINDERS_FILE", tmp_path / "reminders.json")
    make_note(actions=["a", "b"])
    a = p.open_actions()[0]
    p.add_reminder(a, NOW)
    p.add_reminder(a, NOW.replace(day=20))          # same action: replaced, not doubled
    rs = p.load_reminders()
    assert len(rs) == 1 and rs[0]["text"] == "a" and rs[0]["when"].startswith("2026-11-20")
    assert p.remove_reminder(p.action_id(a)) and p.load_reminders() == []


# ---- chat mode ----------------------------------------------------------------

class FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass
    def json(self): return {"message": {"content": self.text}}


def capture_chat(monkeypatch, reply="Hi **there**"):
    sent = {}
    def fake_post(url, json, timeout):
        sent["url"], sent["body"] = url, json
        return FakeResp(reply)
    monkeypatch.setattr(p.requests, "post", fake_post)
    return sent


def test_chat_uses_matching_notes(notes, monkeypatch):
    note = make_note(title="Claude Memory Plugin", source="https://x/a")
    make_note(title="Cooking Rice", source="https://x/b", tags=["food"])
    sent = capture_chat(monkeypatch)
    reply, sources = p.chat_reply("which plugin gives claude memory?", [])
    system = sent["body"]["messages"][0]["content"]
    assert sent["url"].endswith("/api/chat") and sources == [note]
    assert "Claude Memory Plugin" in system and "Cooking Rice" not in system
    assert reply == "Hi there"                       # Markdown ** removed


def test_chat_follow_up_uses_previous_message(notes, monkeypatch):
    note = make_note(title="Strix Security Scanner", source="https://x/a")
    sent = capture_chat(monkeypatch)
    history = [{"role": "user", "content": "tell me about strix"},
               {"role": "assistant", "content": "Strix finds security holes."}]
    reply, sources = p.chat_reply("how do I install it?", history)
    assert sources == [note]                         # found via the previous message
    assert sent["body"]["messages"][1:] == history + [
        {"role": "user", "content": "how do I install it?"}]


def test_chat_small_talk_without_notes(notes, monkeypatch):
    make_note(title="Strix Security Scanner")
    sent = capture_chat(monkeypatch, reply="Hello! How can I help?")
    reply, sources = p.chat_reply("hi", [])
    assert sources == [] and "(no matching notes)" in sent["body"]["messages"][0]["content"]


def test_chat_history_is_limited(notes, monkeypatch):
    sent = capture_chat(monkeypatch)
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
               for i in range(40)]
    p.chat_reply("hello", history)
    assert len(sent["body"]["messages"]) == 1 + p.CHAT_HISTORY_TURNS * 2 + 1


@pytest.mark.parametrize("msg,expected", [
    ("which one should I try first?", True),
    ("how do I install it?", True),
    ("tell me more", True),
    ("what did I save about claude plugins?", False),
    ("design skills for landing pages and animations in react apps", False),
])
def test_is_follow_up(msg, expected):
    assert p.is_follow_up(msg) is expected


def test_follow_up_keeps_previous_notes(notes, monkeypatch):
    claude = make_note(title="Claude Plugins Strix Mem", source="https://x/a")
    make_note(title="Try First Trading Skill", source="https://x/b", tags=["trading"])
    capture_chat(monkeypatch)
    history = [{"role": "user", "content": "what did I save about claude plugins?"},
               {"role": "assistant", "content": "..."}]
    _, sources = p.chat_reply("which one should I try first?", history)
    assert sources[0] == claude


def test_chat_prompt_forbids_invented_steps():
    assert "NEVER invent steps" in p.CHAT_SYSTEM and "Claims to check" in p.CHAT_SYSTEM


# ---- /plan ----------------------------------------------------------------------

def test_make_plan_uses_only_note_content(notes):
    path = make_note(category="programming", title="5 Claude Plugins",
                     actions=[{"text": "Read the Strix README", "priority": "high"}, "Try Claude mem"],
                     resources=[{"name": "Strix", "link": "https://github.com/usestrix/strix"}],
                     claims=[{"claim": "7 billion free tokens", "why": "no source"}],
                     key_points=["Strix finds security holes"])
    p.complete_actions([2])                       # 'Try Claude mem' done: not in the plan
    plan = p.make_plan(path, "use it in my bot")
    assert plan.startswith("ACT AS: an experienced software engineer")
    assert "REQUEST:" in plan and "TERMS" in plan and "Constraints:" in plan and "Output:" in plan
    assert "1. Read the Strix README" in plan and "Try Claude mem" not in plan
    assert "https://github.com/usestrix/strix" in plan
    assert '"7 billion free tokens"' in plan and "My goal: use it in my bot" in plan
    assert "🔥" not in plan and "## " not in plan


def test_make_plan_without_actions(notes):
    path = make_note(category="motivation", actions=["x"])
    p.complete_actions([1])
    plan = p.make_plan(path)
    assert "supportive personal coach" in plan and "Suggest 3-5 practical actions" in plan


def test_make_plan_skips_creator_promo_actions(notes):
    path = make_note(actions=["Check the broadcast channel from the bio", "Read the README"])
    plan = p.make_plan(path)
    instructions = plan.split("Backup if a link")[0]
    assert "1. Read the README" in instructions and "broadcast channel" not in instructions
    assert "The creator offered: Check the broadcast channel from the bio" in plan


# ---- resurface --------------------------------------------------------------------

def test_resurface_picks_only_old_notes_and_rotates(notes):
    from datetime import date
    (notes / "2026-10-01_1200_a.md").write_text(
        "# Old A\n\n## Key points\n- point A1\n- point A2\n", encoding="utf-8")
    (notes / "2026-10-02_1200_b.md").write_text(
        "# Old B\n\n## Key quote\n> Stay hungry  *(paraphrased)*\n", encoding="utf-8")
    (notes / "2026-11-13_1200_new.md").write_text("# New\n\n## Key points\n- n\n", encoding="utf-8")
    today = date(2026, 11, 14)
    titles = {p.pick_resurface(today, shift=s)["title"] for s in range(4)}
    assert titles == {"Old A", "Old B"}                     # never the 1-day-old note
    quote = next(r for s in range(2) if (r := p.pick_resurface(today, shift=s))["title"] == "Old B")
    assert quote["kind"] == "quote" and quote["text"] == "Stay hungry"


def test_resurface_none_when_all_new(notes):
    from datetime import date
    (notes / "2026-11-13_1200_new.md").write_text("# New\n", encoding="utf-8")
    assert p.pick_resurface(date(2026, 11, 14)) is None


# ---- creator info and offers ------------------------------------------------------

@pytest.mark.parametrize("text,is_promo", [
    ("Comment 'MEMORY' to receive the GitHub repo", True),
    ('Comment "CLAUDE" below', True),
    ("Comment “PROCESS” to get the premium skills", True),
    ("Follow for more AI tools", True),
    ("Follow me for daily tips", True),
    ("Grab the link in bio", True),
    ("Follow the instructions to install the model", False),
    ("Add a comment to your code", False),
    ("Visit the GitHub repo and explore the README", False),
])
def test_promo_filter(text, is_promo):
    assert bool(p.LOW_PRIORITY_RE.search(text)) is is_promo


def test_creator_from_info():
    info = {"entries": [None, {"uploader": "Akita", "uploader_id": "akitaonrails",
                               "uploader_url": "https://www.instagram.com/akitaonrails"}]}
    c = p.creator_from_info(info)
    assert p.creator_line(c) == "Akita (@akitaonrails) https://www.instagram.com/akitaonrails"
    assert p.creator_line({"name": "", "handle": "123456", "url": ""}) == "@123456"
    assert p.creator_line(p.creator_from_info({"uploader_id": "98765"})) == ""
    assert p.creator_line(None) == ""


def test_note_has_creator_and_offer_section(notes):
    path = make_note(actions=["Visit the GitHub repo", "Comment 'MEMORY' to receive the repo"],
                     creator="Akita (@akitaonrails)",
                     key_points=["Memory is stored as Markdown", "Follow the creator for more"])
    text = path.read_text(encoding="utf-8")
    assert "- Creator: Akita (@akitaonrails)" in text.split("## Summary")[0]
    offer = text.split("## From the creator")[1].split("## Key points")[0]
    assert "- Offer: Comment 'MEMORY' to receive the repo" in offer
    assert "- Offer: Follow the creator for more" in offer
    # still a (low priority) action, nothing deleted:
    assert "- [ ] 🔽 🔗 Comment 'MEMORY' to receive the repo" in text
    assert p.find_note_by_source("https://x/1") == path      # duplicate check unaffected


def test_plan_moves_creator_offers_to_backup(notes):
    path = make_note(actions=["Visit the GitHub repo", "Comment 'MEMORY' to receive the repo"],
                     creator="Akita (@akitaonrails)",
                     key_points=["Memory is stored as Markdown", "Follow the creator for more"])
    plan = p.make_plan(path)
    instructions, backup = plan.split("Backup if a link above is wrong")
    assert "1. Visit the GitHub repo" in instructions and "MEMORY" not in instructions
    assert "Follow the creator" not in instructions and "Memory is stored as Markdown" in instructions
    assert "The video's creator: Akita (@akitaonrails)" in backup
    assert "The creator offered: Comment 'MEMORY' to receive the repo" in backup
    assert backup.count("Comment 'MEMORY'") == 1          # not listed twice


def test_repo_info_missing(monkeypatch):
    monkeypatch.setattr(p, "github_request", lambda p, params=None: (404, None))
    assert p.repo_info("a", "b") == {"missing": True}


def test_repo_info_rate_limit_is_not_missing(monkeypatch):
    monkeypatch.setattr(p, "github_request", lambda p, params=None: (403, None))
    assert p.repo_info("a", "b") is None


def test_repo_info_fields(monkeypatch):
    d = {"html_url": "https://github.com/a/b", "stargazers_count": 5, "description": "x",
         "pushed_at": "2024-03-02T00:00:00Z", "archived": True, "license": {"spdx_id": "MIT"}}
    monkeypatch.setattr(p, "github_request", lambda p, params=None: (200, d))
    info = p.repo_info("a", "b")
    assert info["updated"] == "2024-03-02" and info["archived"] and info["license"] == "MIT"


def test_repo_warnings():
    from datetime import date
    r = {"archived": True, "updated": "2024-03-02"}
    w = p.repo_warnings(r, today=date(2026, 1, 1))
    assert any("archived" in x for x in w) and any("Mar 2024" in x for x in w)
    assert p.repo_warnings({"missing": True})[0].startswith("⚠️ repo not found")
    assert p.repo_warnings({"updated": "2025-12-01"}, today=date(2026, 1, 1)) == []


def test_resource_line_shows_health():
    line = p.resource_line({"name": "B", "link": "https://github.com/a/b", "stars": 10,
                                    "updated": "2020-01-01", "license": "MIT", "archived": True}, "tech")
    assert "updated Jan 2020" in line and "MIT" in line and "archived" in line


def test_no_github_search_when_video_is_not_about_code(monkeypatch):
    called = []
    monkeypatch.setattr(p, "find_repo", lambda n, s: called.append(n) or {"link": "x", "stars": 9})
    text = "Go to settings and search for DNS. Muse from Meta, Grokbot from X."
    res = p.enrich_with_github([{"name": "Settings"}, {"name": "Muse"}], "tech", text)
    assert called == []
    assert p.resource_line(res[0], "tech") == "Settings — No repo found"


def test_github_search_when_video_mentions_open_source(monkeypatch):
    monkeypatch.setattr(p, "find_repo", lambda n, s: {"link": "https://github.com/nashsu/llm_wiki", "stars": 9})
    text = "LLM Wiki is an open source desktop app on GitHub"
    res = p.enrich_with_github([{"name": "LLM Wiki"}, {"name": "Other"}], "tech", text)
    assert res[0]["link"].endswith("llm_wiki")


ROADMAP = ("Core developer workflow: terminal, VS Code, Git/GitHub. GitHub Skills — "
           "Git and GitHub workflow. Python Tutorial — official documentation")


def test_roadmap_courses_get_no_repo_found(monkeypatch):
    monkeypatch.setattr(p, "find_repo", lambda n, s: {"link": "https://github.com/x/y", "stars": 9})
    res = p.enrich_with_github([{"name": "Python Tutorial"}, {"name": "SQLBolt"},
                                {"name": "GitHub Skills"}], "programming", ROADMAP)
    assert all(p.resource_line(r, "programming").endswith("No repo found") for r in res)


def test_course_names_skipped_even_for_open_source(monkeypatch):
    monkeypatch.setattr(p, "find_repo", lambda n, s: {"link": "https://github.com/x/y", "stars": 9})
    res = p.enrich_with_github([{"name": "Kaggle Learn: Python"}, {"name": "LLM Wiki"}],
                               "tech", "an open source app on GitHub")
    assert "link" not in res[0] and res[1]["link"] == "https://github.com/x/y"


def test_thinking_off_only_for_qwen3(monkeypatch):
    monkeypatch.setattr(p, "OLLAMA_MODEL", "qwen3:8b")
    assert p.ollama_extra() == {"think": False}
    monkeypatch.setattr(p, "OLLAMA_MODEL", "qwen2.5:7b")
    assert p.ollama_extra() == {}
    assert p.strip_thinking("<think>hmm</think>{\"a\":1}") == '{"a":1}'


def test_find_note_for_redo_and_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path)
    (tmp_path / "2026-11-14_2106_llm-wiki.md").write_text("# LLM Wiki\n- Source: https://www.instagram.com/reel/A/\n", encoding="utf-8")
    (tmp_path / "2026-11-15_0040_ai-job.md").write_text("# AI Job Market\n- Source: screenshot\n", encoding="utf-8")
    assert p.find_note_for_redo().name.endswith("ai-job.md")          # newest
    note = p.find_note_for_redo("llm wiki")
    assert p.note_source(note) == "https://www.instagram.com/reel/A/"
    assert p.find_note_for_redo("nothing here") is None
    hidden = note.with_suffix(".redo")
    note.replace(hidden)
    moved = p.archive_note(hidden)
    assert moved == tmp_path / "old" / "2026-11-14_2106_llm-wiki.md" and moved.exists()
    assert len(list(tmp_path.glob("*.md"))) == 1                         # hidden from /todo etc.


def test_update_ytdlp(monkeypatch):
    versions = iter(["2026.10.1", "2026.11.9"])
    monkeypatch.setattr(p, "ytdlp_version", lambda: next(versions))
    monkeypatch.setattr(p.subprocess, "run",
                        lambda *a, **k: types.SimpleNamespace(returncode=0, stderr="", stdout=""))
    assert p.update_ytdlp() == ("2026.10.1", "2026.11.9", "")


def test_health_checks_when_everything_is_off(tmp_path, monkeypatch):
    def down(*a, **k): raise p.requests.ConnectionError()
    monkeypatch.setattr(p.requests, "get", down)
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path / "missing")
    checks = {name: ok for ok, name, _ in p.health_checks()}
    assert checks["Ollama"] is False and checks["Notes folder"] is False


def make_actions_note(tmp_path, monkeypatch, body):
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path)
    (tmp_path / "2026-11-10_0900_a.md").write_text(
        "# A\n\n## Action items\n" + body, encoding="utf-8")
    return tmp_path / "2026-11-10_0900_a.md"


def test_split_due_and_label():
    from datetime import date
    assert p.split_due("Learn Pandas 📅 2026-11-20") == ("Learn Pandas", date(2026, 11, 20))
    assert p.split_due("Learn Pandas") == ("Learn Pandas", None)
    today = date(2026, 11, 16)
    assert p.due_label(date(2026, 11, 15), today).startswith("⚠️ overdue")
    assert p.due_label(today, today) == "📅 today"
    assert p.due_label(date(2026, 11, 17), today) == "📅 tomorrow"
    assert p.due_label(date(2026, 11, 20), today) == "📅 Fri 20 Nov"


def test_parse_due():
    from datetime import date
    mon = date(2026, 11, 16)
    assert p.parse_due("friday", mon) == date(2026, 11, 20)
    assert p.parse_due("monday", mon) == mon                    # today counts
    assert p.parse_due("in 3 days", mon) == date(2026, 11, 19)
    assert p.parse_due("20/11", mon) == date(2026, 11, 20)
    assert p.parse_due("banana", mon) is None


def test_due_soon_actions_go_first_and_priority_keeps_date(tmp_path, monkeypatch):
    from datetime import date, timedelta
    soon = date.today() + timedelta(days=1)
    note = make_actions_note(tmp_path, monkeypatch,
                             "- [ ] 🔥 High thing\n- [ ] Normal thing\n"
                             f"- [ ] 🔽 Low but due 📅 {soon:%Y-%m-%d}\n")
    acts = p.open_actions()
    assert acts[0]["action"] == "Low but due" and acts[0]["due"] == soon
    assert acts[1]["action"] == "High thing"
    p.set_priority([1], "high")                                  # date must survive
    assert f"- [ ] 🔥 Low but due 📅 {soon:%Y-%m-%d}" in note.read_text(encoding="utf-8")


def test_set_due_and_clear(tmp_path, monkeypatch):
    from datetime import date
    note = make_actions_note(tmp_path, monkeypatch, "- [ ] 🔥 Learn Pandas\n")
    p.set_due([1], date(2030, 1, 5))
    assert "- [ ] 🔥 Learn Pandas 📅 2030-01-05" in note.read_text(encoding="utf-8")
    p.set_due([1], None)
    assert note.read_text(encoding="utf-8").endswith("- [ ] 🔥 Learn Pandas\n")


def test_nudge_picks_overdue_first(tmp_path, monkeypatch):
    from datetime import date
    make_actions_note(tmp_path, monkeypatch,
                      "- [ ] 🔥 High thing\n- [ ] Late thing 📅 2020-01-01\n")
    assert p.pick_nudge()["action"] == "Late thing"


def test_combined_plan(tmp_path):
    a = tmp_path / "2026-11-14_2106_llm-wiki.md"
    a.write_text("# LLM Wiki\n\n- Category: tech\n- Source: https://x.com/a\n- Creator: Steve\n\n"
                 "## Summary\nA wiki app.\n\n## Claims to check\n- ⚠️ \"It is free\" — check\n\n"
                 "## Key points\n- Imports PDFs\n\n## Action items\n- [ ] 🔥 Install LLM Wiki 📅 2026-11-20\n",
                 encoding="utf-8")
    b = tmp_path / "2026-11-15_0112_ai-job.md"
    b.write_text("# AI Job Roadmap\n\n- Category: programming\n- Source: https://x.com/b\n\n"
                 "## Action items\n- [ ] Learn Pandas\n- [ ] 🔽 Comment 'Roadmap' for the link\n",
                 encoding="utf-8")
    plan = p.make_plan([a, b], "get a data job")
    assert "from 2 short videos" in plan and "My goal: get a data job" in plan
    assert 'V1: "LLM Wiki"' in plan and 'V2: "AI Job Roadmap"' in plan
    assert "- Install LLM Wiki" in plan and "📅" not in plan          # date stripped
    assert "Verify this claim (V1)" in plan
    assert "V2 creator: the creator (offered: Comment 'Roadmap' for the link)" in plan
    assert "- Comment 'Roadmap'" not in plan                            # not an action
    assert "V1: https://x.com/a · V2: https://x.com/b" in plan


@pytest.mark.parametrize("bad,expect", [
    ({"title": None, "summary": None, "key_points": None}, ("Untitled reel", "", [])),
    ({"title": "T", "key_points": "one\n- two\n3. three"}, ("T", "", ["one", "two", "three"])),
    ({"title": "T", "key_points": [{"point": "A"}, {"text": " B "}, None, ""]}, ("T", "", ["A", "B"])),
    ({"title": 42, "summary": ["x"], "key_points": 5}, ("42", "", [])),
])
def test_clean_note_fields_survives_wrong_shapes(bad, expect):
    d = p.clean_note_fields(dict(bad))
    assert (d["title"], d["summary"], d["key_points"]) == expect
    assert d["resources"] == []


def test_clean_note_fields_category_and_resources():
    assert p.clean_note_fields({"category": "Tech"})["category"] == "tech"
    assert p.clean_note_fields({"category": "science"})["category"] == "other"
    assert p.clean_note_fields({"category": None})["category"] == "other"
    d = p.clean_note_fields({"resources": [{"name": "A", "link": ""}, "B", None, 3]})
    assert d["resources"] == [{"name": "A", "link": ""}, "B"]
    assert p.clean_note_fields({"resources": "x"})["resources"] == []


def _fake_ollama(monkeypatch, answers):
    calls = []
    def post(url, json=None, timeout=None):
        calls.append(json)
        body = answers[min(len(calls), len(answers)) - 1]
        return types.SimpleNamespace(raise_for_status=lambda: None,
                                     json=lambda: {"response": body})
    monkeypatch.setattr(p.requests, "post", post)
    return calls


def test_ollama_retries_once_on_empty_answer(monkeypatch):
    calls = _fake_ollama(monkeypatch, ["not json", '{"title": "ok"}'])
    assert p.ask_ollama_json("x", schema={"type": "object"}) == {"title": "ok"}
    assert len(calls) == 2 and calls[0]["format"] == {"type": "object"}


def test_summarise_raises_clear_error_when_ai_is_empty(monkeypatch):
    calls = _fake_ollama(monkeypatch, ["", "{}"])
    monkeypatch.setattr(p, "NOTES_DIR", Path("/nonexistent-notes"))
    with pytest.raises(RuntimeError, match="no usable answer"):
        p.summarise("hello", "", "")
    assert len(calls) == 2


def test_summarise_saves_note_when_model_returns_nulls(monkeypatch, tmp_path):
    _fake_ollama(monkeypatch, ['{"title": null, "key_points": null, "summary": null, '
                               '"category": "Tech", "resources": null}'])
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path)
    data = p.summarise("hello", "", "")
    path = p.save_note(data, "hello", "", "https://x.com/a")
    assert "# Untitled reel" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("link,shown", [
    ("strix.ai/docs", "https://strix.ai/docs"),
    ("www.nas.com", "https://www.nas.com"),
    ("github.com/a/b", "https://github.com/a/b"),
    ("https://x.com/a", "https://x.com/a"),
])
def test_link_shown_without_https_is_kept(link, shown):
    assert shown in p.resource_line({"name": "T", "link": link}, "tech")


def test_not_a_link_says_no_repo_found():
    for bad in ("install it", "Muse", ""):
        line = p.resource_line({"name": "T", "link": bad}, "other")
        assert line == "T — No repo found" and "search" not in line


def test_real_repo_link_kept_without_no_repo_text():
    line = p.resource_line({"name": "B", "link": "https://github.com/a/b"}, "tech")
    assert "https://github.com/a/b" in line and "No repo found" not in line


def test_repo_name_at_end_of_sentence(monkeypatch):
    seen = []
    def fake(path, params=None):
        seen.append(path)
        return 200, {"html_url": "https://github.com/a/repo", "stargazers_count": 1}
    monkeypatch.setattr(p, "github_request", fake)
    assert p.repo_info("a", "repo.")["link"].endswith("a/repo")
    assert seen == ["/repos/a/repo"]


def test_retag_fills_empty_tags_line_once(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path)
    note = tmp_path / "2026-11-10_0900_a.md"
    note.write_text("# A\n\n- Date: x\n- Tags: \n\n## Summary\nHi\n", encoding="utf-8")
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, **k: {"tags": ["python"]})
    for _ in range(2):                                  # a second /retag must change nothing
        p.tag_untagged_notes()
    text = note.read_text(encoding="utf-8")
    assert text.count("- Tags:") == 1 and "- Tags: #python" in text


def test_notes_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path / "missing")
    assert not p.notes_ready()
    monkeypatch.setattr(p, "NOTES_DIR", tmp_path)
    assert p.notes_ready()


# ---- timing ------------------------------------------------------------------

def test_timing_text():
    assert p.timing_text({"download": 4.2, "whisper": 21, "ocr": 48.4, "ai": 14}) == \
        "88s (download 4 · listen 21 · read screen 48 · AI 14)"
    assert p.timing_text({"whisper": 0, "ocr": 2, "ai": 3}) == "5s (listen 0 · read screen 2 · AI 3)"


def test_note_pipeline_records_timings(notes, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(p, "transcribe", lambda v: ("spoken words", "en"))
    monkeypatch.setattr(p, "screen_text", lambda v, w: "on screen")
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: {
        "title": "Timed", "category": "tech", "summary": "s", "key_points": ["k"],
        "resources": [], "action_items": [], "claims": [], "tags": []})
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    _, data = p.process_videos([video], "https://x/t")
    assert set(data["timings"]) == {"whisper", "ocr", "ai"}
    assert all(v >= 0 for v in data["timings"].values())
    assert "timing:" in capsys.readouterr().out


# ---- stable action ids and /todo numbers ---------------------------------------

def test_action_id_survives_moved_lines_priority_and_due(notes):
    path = make_note(actions=["Read the docs", "Install it"])
    a = next(x for x in p.open_actions() if x["action"] == "Read the docs")
    aid = p.action_id(a)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines.insert(3, "- Mood: good")                       # a hand edit moves every line down
    path.write_text("\n".join(lines), encoding="utf-8")
    n, found = p.find_action(aid)
    assert found["action"] == "Read the docs"
    p.set_priority([n], "high")
    p.set_due([p.find_action(aid)[0]], p.date.today() + p.timedelta(days=30))
    assert p.find_action(aid)[1]["priority"] == "high"    # same id after both changes


def test_old_style_action_id_still_found(notes):
    make_note(actions=["Read the docs"])
    a = p.open_actions()[0]
    old = p.legacy_action_id(a)
    assert ":" in old and p.find_action(old)[1]["action"] == "Read the docs"


def test_same_text_twice_gets_two_ids(notes):
    make_note(actions=["Do it", "Do it"])
    ids = [p.action_id(a) for a in p.open_actions()]
    assert len(set(ids)) == 2


def test_current_numbers_follow_the_list_you_saw(notes):
    make_note(title="Old", actions=["Read the docs", "Try the demo"], source="https://x/1")
    shown = [p.action_id(a) for a in p.open_actions()]             # what /todo showed
    data = {"title": "New", "category": "tech", "summary": "s", "key_points": [], "resources": [],
            "tags": [], "claims": [], "quote": "", "lesson": "", "habit": "",
            "action_items": [{"text": "Install tool", "priority": "high"}]}
    p.save_note(data, "", "", "https://x/2")                        # a new 🔥 action arrives
    assert p.open_actions()[0]["action"] == "Install tool"          # the list has moved
    assert p.complete_actions(p.current_numbers(shown, [1])) == ["Read the docs"]
    assert p.current_numbers(shown, [1]) == []                      # already done: left out
    assert p.complete_actions(p.current_numbers(shown, [2])) == ["Try the demo"]
    assert p.current_numbers(None, [2, 5]) == [2, 5]                # no saved list: as typed
    assert p.current_numbers(shown, [99]) == []


# ---- catch-up of scheduled messages missed while the PC was off --------------------

RULES = {"nudge": {"every": "day", "at": (8, 0)},
         "weekly": {"every": "week", "weekday": 6, "at": (9, 0)},      # Sunday
         "monthly": {"every": "month", "day": 1, "at": (9, 30)}}


@pytest.mark.parametrize("kind,now,expected", [
    ("nudge", "2026-11-16 07:59", None),                 # before 8:00: nothing due yet
    ("nudge", "2026-11-16 08:00", "2026-11-16"),
    ("nudge", "2026-11-16 22:15", "2026-11-16"),
    ("weekly", "2026-11-15 08:59", "2026-11-08"),        # Sunday before 9:00: last week's
    ("weekly", "2026-11-15 09:00", "2026-11-15"),
    ("weekly", "2026-11-18 14:00", "2026-11-15"),        # Wednesday: last Sunday
    ("monthly", "2026-11-01 09:29", "2026-10-01"),
    ("monthly", "2026-11-01 09:30", "2026-11-01"),
    ("monthly", "2026-11-20 10:00", "2026-11-01"),
])
def test_last_slot(kind, now, expected):
    slot = p.last_slot(RULES[kind], p.datetime.fromisoformat(now))
    assert (slot.isoformat() if slot else None) == expected


def test_due_jobs_first_run_sends_nothing():
    sent = {}
    assert p.due_jobs(p.datetime(2026, 11, 16, 10, 0), sent, RULES) == []
    assert sent == {"nudge": "2026-11-16", "weekly": "2026-11-15", "monthly": "2026-11-01"}


def test_due_jobs_catches_up_what_was_missed():
    sent = {"nudge": "2026-11-13", "weekly": "2026-11-08", "monthly": "2026-11-01"}
    # PC off from Friday evening to Monday 10:00: today's nudge + Sunday's review
    now = p.datetime(2026, 11, 16, 10, 0)
    assert p.due_jobs(now, sent, RULES) == [("nudge", "2026-11-16"), ("weekly", "2026-11-15")]
    sent.update(nudge="2026-11-16", weekly="2026-11-15")
    assert p.due_jobs(now, sent, RULES) == []                           # never sent twice
    # started early next morning: yesterday's nudge is NOT sent late; today's comes at 8:00
    sent["nudge"] = "2026-11-14"
    assert p.due_jobs(p.datetime(2026, 11, 17, 7, 0), sent, RULES) == []


def test_sent_jobs_file(tmp_path, monkeypatch):
    monkeypatch.setattr(p, "SENT_JOBS_FILE", tmp_path / "sent.json")
    assert p.load_sent_jobs() == {}
    p.save_sent_jobs({"nudge": "2026-11-16"})
    assert p.load_sent_jobs() == {"nudge": "2026-11-16"}
    (tmp_path / "sent.json").write_text("not json")
    assert p.load_sent_jobs() == {}


# ---- fewer actions, and pick ONE when a note is saved --------------------------------

def test_prompt_asks_for_few_actions_all_steps_and_simple_english():
    assert "list of 0-2 objects" in p.PROMPT and "Use [] if nothing" in p.PROMPT
    assert "keep EVERY step" in p.PROMPT
    assert "simple English" in p.PROMPT


def test_split_actions_keeps_the_best_one_and_moves_offers_out():
    actions = p.clean_actions(["One", {"text": "Two", "priority": "high"},
                               "Comment 'AI' to get the link", "Three"])
    kept, extras, offers = p.split_actions(actions)
    assert [a["text"] for a in kept] == ["Two"]                 # highest priority wins
    assert [a["text"] for a in extras] == ["One", "Three"]
    assert offers == ["Comment 'AI' to get the link"]
    assert [a["text"] for a in p.limit_actions(actions)] == ["Two"]


def test_summarise_gives_one_action_other_ideas_and_offers(notes, monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: {
        "title": "T", "category": "tech", "summary": "s", "key_points": ["k"], "resources": [],
        "claims": [], "tags": [], "action_items": [
            {"text": "Do A", "priority": "normal"}, {"text": "Do B", "priority": "normal"},
            {"text": "Comment 'MEMORY' to get the repo", "priority": "normal"}]})
    data = p.summarise("words", "", "")
    assert [a["text"] for a in data["action_items"]] == ["Do A"]
    assert data["other_ideas"] == ["Do B"]
    assert data["creator_offers"] == ["Comment 'MEMORY' to get the repo"]
    text = p.save_note(data, "t", "s", "https://x/9").read_text(encoding="utf-8")
    assert "## Other ideas\n- Do B" in text
    assert "- Offer: Comment 'MEMORY' to get the repo" in text
    assert text.count("- [ ] ") == 1                             # only one real action


def test_new_notes_store_the_action_type(notes):
    path = make_note(actions=[{"text": "Ask Claude to rewrite my CV", "type": "ai"}])
    assert "- [ ] 🤖 Ask Claude to rewrite my CV" in path.read_text(encoding="utf-8")
    a = p.open_actions()[0]
    assert a["kind"] == "ai" and a["kind_saved"] and a["action"] == "Ask Claude to rewrite my CV"


def test_guess_kind_for_old_actions():
    assert p.guess_kind("Paste the prompt into ChatGPT") == "ai"
    assert p.guess_kind("Every morning, write 3 goals") == "habit"
    assert p.guess_kind("Find the Strix GitHub repo and read its README") == "lookup"
    assert p.guess_kind("Do the thing", category="motivation") == "habit"


def test_action_id_ignores_the_type_icon(notes):
    path = make_note(actions=["Read the docs"])
    before = p.open_actions()[0]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] 🔗 ", "- [ ] "), encoding="utf-8")
    after = p.open_actions()[0]
    assert after["kind_saved"] is False and p.action_id(after) == p.action_id(before)


def test_priority_change_keeps_the_saved_type(notes):
    path = make_note(actions=[{"text": "Ask Claude to plan my week", "type": "ai"}])
    p.set_priority([1], "high")
    assert "- [ ] 🔥 🤖 Ask Claude to plan my week" in path.read_text(encoding="utf-8")



# ---- /cleanup ----------------------------------------------------------------------

def old_note(title, lines):
    """A note written by hand, like the old ones (several actions, no type icons)."""
    path = p.NOTES_DIR / f"2026-11-01_1000_{title.lower().replace(' ', '-')}.md"
    path.write_text(f"# {title}\n\n- Date: 2026-11-01 10:00\n- Category: tech\n\n## Action items\n"
                    + "\n".join(lines) + "\n\n## Transcript\nwords\n", encoding="utf-8")
    return path


def test_cleanup_plan_skips_junk_and_extras_but_keeps_best_dated_and_habits(notes):
    old_note("One", ["- [ ] 🔥 Best", "- [ ] Second", "- [ ] 🔽 Third",
                     "- [ ] 🔽 Comment 'MEMORY' to get the repo"])
    old_note("Two", ["- [ ] Normal A", "- [ ] Normal B 📅 2030-01-01"])
    make_note(title="Habit note", category="motivation", habit="Every Monday, plan the week",
              actions=["Only action"], source="https://x/h")
    plan = p.cleanup_plan()
    assert plan["open"] == 8 and plan["junk"] == 1 and plan["extras"] == 2
    assert plan["left"] == 5 and plan["notes"] == 3
    skipped = p.skip_actions_by_id(plan["ids"])
    assert sorted(skipped) == ["Comment 'MEMORY' to get the repo", "Second", "Third"]
    left = [a["action"] for a in p.open_actions()]
    assert sorted(left) == sorted(["Best", "Normal A", "Normal B",
                                   "Every Monday, plan the week", "Only action"])
    assert p.cleanup_plan()["ids"] == []                      # nothing more to do
    assert "- [-] 🔽 Third" in (p.NOTES_DIR / "2026-11-01_1000_one.md").read_text(encoding="utf-8")


def test_cleanup_with_nothing_to_do(notes):
    make_note(actions=["Do one thing"])
    plan = p.cleanup_plan()
    assert plan["ids"] == [] and plan["open"] == 1


# ---- creator offers vs real actions ------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Comment 'MEMORY' to get the repo", "Comment LEARN to get the prompt",
    "Follow the creator for more", "Link in bio for the guide", "DM me the word AI",
    "Check the link in the caption", "Get the link in the bio", "Follow me for more tips",
    "DM us for the template", "Send me a DM and I'll share it", "Visit the creator's page",
    "Comment below for the link"])
def test_creator_offers_are_recognised(text):
    assert p.LOW_PRIORITY_RE.search(text)


@pytest.mark.parametrize("text", [
    "Update your LinkedIn bio with these 3 keywords", "DM your manager to ask for feedback",
    "Put the link in your notes app", "Add a comment to your code",
    "Write your bio in 3 lines", "Reply to the DM from your recruiter"])
def test_real_actions_are_not_mistaken_for_offers(text):
    assert not p.LOW_PRIORITY_RE.search(text)


def test_a_linkedin_bio_action_is_kept_as_the_main_action():
    actions = p.clean_actions([{"text": "Update your LinkedIn bio with these 3 keywords",
                                "priority": "high"}, "Read the guide"])
    kept, extras, offers = p.split_actions(actions)
    assert [a["text"] for a in kept] == ["Update your LinkedIn bio with these 3 keywords"]
    assert offers == []


# ---- undo for /cleanup -------------------------------------------------------------------

def test_undo_cleanup_puts_back_the_skipped_actions(notes):
    path = old_note("One", ["- [ ] 🔥 Best", "- [ ] Second 📅 2030-01-01",
                            "- [ ] 🔽 Third"])
    before = path.read_text(encoding="utf-8")
    old_note("Two", ["- [ ] Keep", "- [ ] Drop"])
    plan = p.cleanup_plan()
    assert p.can_undo_cleanup() == 0
    assert len(p.skip_with_undo(plan["ids"])) == len(plan["ids"]) >= 2
    assert p.can_undo_cleanup() == len(plan["ids"])
    assert p.undo_cleanup() == len(plan["ids"])
    assert path.read_text(encoding="utf-8") == before
    assert p.can_undo_cleanup() == 0 and p.undo_cleanup() == 0


def test_undo_cleanup_leaves_ticked_actions_alone(notes):
    path = old_note("One", ["- [ ] Best", "- [ ] Extra"])
    p.skip_with_undo(p.cleanup_plan()["ids"])
    text = path.read_text(encoding="utf-8").replace("- [-] Extra", "- [x] Extra")
    path.write_text(text, encoding="utf-8")                   # you ticked it yourself later
    assert p.undo_cleanup() == 0
    assert "- [x] Extra" in path.read_text(encoding="utf-8")


# ---- nudge details, "save one, do one", prompt for one action ------------------------------

def test_action_details_prefers_a_real_link_and_two_points(notes):
    path = make_note(actions=["Install the tool"], key_points=["First point", "Second point", "Third"],
                     resources=[{"name": "Search", "link": "https://www.google.com/search?q=x"},
                                {"name": "Repo", "link": "https://github.com/a/b."}])
    d = p.action_details(p.open_actions()[0])
    assert d["link"] == "https://github.com/a/b" and d["is_reel"] is False     # no trailing dot
    assert d["points"] == ["First point", "Second point"]


def test_action_details_falls_back_to_the_reel_link(notes):
    make_note(actions=["Read it"], source="https://www.instagram.com/reel/abc/",
              resources=[{"name": "Search", "link": "https://www.google.com/search?q=x"}])
    d = p.action_details(p.open_actions()[0])
    assert d["link"] == "https://www.instagram.com/reel/abc/" and d["is_reel"] is True


def test_action_details_trims_long_points(notes):
    make_note(actions=["Do it"], key_points=["word " * 60])
    point = p.action_details(p.open_actions()[0])["points"][0]
    assert len(point) <= 160 and point.endswith("...")


def test_save_one_asks_once_a_day_when_nothing_was_ticked(notes):
    old = old_note("Older", ["- [ ] 🔥 Old action"])
    new = make_note(title="Brand new", actions=["New action"], source="https://x/new")
    today = p.date.today()
    first = p.save_one_candidate(exclude=new, today=today)
    assert first["action"] == "Old action" and first["path"] == old
    assert p.save_one_candidate(exclude=new, today=today) is None            # only once a day
    assert p.save_one_candidate(exclude=new, today=today + p.timedelta(days=1)) is not None


def test_save_one_is_quiet_when_you_did_something_this_week(notes):
    old_note("Older", ["- [ ] Old action", "- [ ] Tick me"])
    new = make_note(actions=["New"], source="https://x/new")
    p.complete_actions([2])                                                  # a real "done" today
    assert p.save_one_candidate(exclude=new) is None


def test_save_one_never_offers_the_new_note_itself(notes):
    new = make_note(actions=["Only action"], source="https://x/new")
    assert p.save_one_candidate(exclude=new) is None
    assert p.load_state() == {}                                              # nothing was recorded


def test_make_action_prompt_is_about_one_action_only(notes):
    path = make_note(title="Memory tools", actions=["Ask Claude to set up memory", "Other thing"],
                     key_points=["Memory is stored as Markdown"], source="https://x/m")
    action = next(a for a in p.open_actions() if a["action"] == "Ask Claude to set up memory")
    text = p.make_action_prompt(action)
    assert text.startswith("ACT AS:") and "TERMS" in text and "Instructions:" in text
    assert 'Help me do ONE thing I saved from a short video: "Ask Claude to set up memory"' in text
    assert "under 5 minutes" in text and "Memory is stored as Markdown" in text
    assert "Other thing" not in text and "Constraints:" in text and "Output:" in text


# ---- search finds short topic words; usage counter -----------------------------------------

def test_question_words_keep_ai_and_uv_and_drop_filler():
    assert p.question_words("what did I save about AI and uv?") == ["ai", "uv"]
    assert p.question_words("did I save anything about go to market?") == ["anything", "market"]


def test_short_words_match_whole_words_only(notes):
    make_note(title="Said again", actions=["x"], key_points=["he said it again"], source="https://x/1")
    make_note(title="Uses AI", actions=["x"], key_points=["the ai tools"], source="https://x/2")
    assert [r["title"] for r in p.search_notes("ai")] == ["Uses AI"]
    assert len(p.search_notes("tools")) == 1


def test_usage_counter_and_text():
    assert "No counts yet" in p.usage_text()
    for name in ["todo", "todo", "(chat)", "ask"]:
        p.count_usage(name)
    text = p.usage_text()
    assert text.splitlines()[1] == "2× /todo" and "1× (chat)" in text and "1× /ask" in text
    assert "since" in text.splitlines()[0]


# ---- /tools: tools and plugins found in the notes ----------------------------------

def test_tools_counted_once_per_note_and_unverified_skipped(notes):
    make_note(title="A", resources=[{"name": "Strix", "link": "https://github.com/a/strix"},
                                    {"name": "Strix", "link": ""},              # same note: once
                                    {"name": "Ghost", "link": "", "unverified": True},
                                    {"name": "Muse", "link": ""}])
    make_note(title="B", source="https://x/2", resources=[{"name": "strix", "link": ""}])
    p.PENDING_DIR.mkdir(parents=True)
    (p.PENDING_DIR / "c.md").write_text("# C\n\n## Resources\n- Aider https://www.google.com/search?q=Aider\n",
                                        encoding="utf-8")
    assert p.all_tools() == [("Strix", "https://github.com/a/strix", 2, "repo"),
                             ("Aider", "No repo found", 1, "tool"),             # old search link
                             ("Muse", "No repo found", 1, "tool")]


# ---- /tools clean-up rules (tool_catalog.json) ------------------------------------

CAT = {"aliases": {"Higgs Field": "Higgsfield", "Higgsfield.ai": "Higgsfield", "Higgsfield MCP": "Higgsfield"},
       "entries": {"Higgsfield": {"type": "tool", "link": "https://higgsfield.ai"},
                   "Claude": {"type": "tool", "link": "https://claude.ai"},
                   "Python": {"type": "language"}},
       "stoplist": ["AI agents", "Golden Hour", "Rim Light"]}


def names(rows):
    return {r[0]: r for r in rows}


def test_tools_aliases_fold_into_one_name_counted_once_per_note():
    rows = p.clean_tools([("Higgs Field", "", "a.md"), ("Higgsfield.ai", "", "a.md"),
                          ("Higgsfield MCP", "https://mcp.higgsfield.ai/mcp", "b.md")], CAT)
    assert rows == [("Higgsfield", "https://higgsfield.ai", 2, "tool")]


def test_tools_official_link_from_catalog_wins():
    rows = p.clean_tools([("Claude", "https://github.com/someone/claude-clone", "a.md")], CAT)
    assert rows == [("Claude", "https://claude.ai", 1, "tool")]


def test_tools_stoplist_drops_generic_and_lighting_terms():
    rows = p.clean_tools([("AI agents", "", "a.md"), ("golden hour", "", "a.md"),
                          ("Rim-Light", "", "a.md"), ("Strix", "", "a.md")], CAT)
    assert [r[0] for r in rows] == ["Strix"]


@pytest.mark.parametrize("suffix", ["GitHub", "Website", "Docs", "Documentation", "Integrations",
                                    "Example", "GitHub Repo"])
def test_tools_suffix_names_fold_into_parent_and_give_the_link(suffix):
    rows = p.clean_tools([("OpenJarvis", "", "a.md"),
                          (f"OpenJarvis {suffix}", "https://open-jarvis.example.org/x", "b.md")], CAT)
    assert rows == [("OpenJarvis", "https://open-jarvis.example.org/x", 2, "tool")]


def test_tools_link_shared_by_three_tools_is_dropped():
    raw = [(n, "https://news.example.com", f"{n}.md") for n in ("Aa", "Bb", "Cc")]
    raw += [("Dd", "https://dd.example.com", "d.md"), ("Ee", "https://two.example.com", "e.md"),
            ("Ff", "https://two.example.com", "f.md")]
    links = {r[0]: r[1] for r in p.clean_tools(raw, CAT)}
    assert links["Aa"] == links["Bb"] == links["Cc"] == "No repo found"
    assert links["Dd"] == "https://dd.example.com" and links["Ff"] == "https://two.example.com"


@pytest.mark.parametrize("link", [
    "https://generativelanguage.googleapis.com/v1beta",       # API endpoint
    "https://api.example.com/models", "https://mcp.example.ai/mcp", "https://example.com/v1/chat",
    "https://Animated-History-Docs-Guide.pdf", "https://example.com/files/guide.pdf",
    "https://t.co/AbC123", "https://tinyurl.com/3d6zzd6r",
    "https://example.com/csv%20|%20file.csv", "https://example.com/a b", "not a link"])
def test_tools_bad_links_are_dropped(link):
    assert p.clean_tools([("Zed Tool", link, "a.md")], CAT)[0][1] == "No repo found"


@pytest.mark.parametrize("link", ["https://higgsfield.ai/mcp", "https://youtu.be/abcDEF12345",
                                  "https://github.com/a/b", "https://docs.nvidia.com/skills"])
def test_tools_good_links_are_kept(link):
    assert p.tool_link_ok(link)


def test_tools_generic_github_repo_name_becomes_repo_name():
    rows = p.clean_tools([("GitHub Repository", "https://github.com/ethan/sellbird", "a.md"),
                          ("GitHub repo", "https://github.com/x/ai-rmemory.git", "b.md"),
                          ("GitHub Repository", "", "c.md")], CAT)                 # no link: dropped
    assert names(rows) == {"sellbird": ("sellbird", "https://github.com/ethan/sellbird", 1, "repo"),
                           "ai-rmemory": ("ai-rmemory", "https://github.com/x/ai-rmemory.git", 1, "repo")}


def test_tools_types():
    rows = names(p.clean_tools([("Python", "", "a.md"), ("Someone's YouTube Channel", "", "a.md"),
                                ("Kaggle Learn: Pandas", "", "a.md"), ("Strix", "https://github.com/u/strix", "a.md"),
                                ("Muse", "", "a.md")], CAT))
    assert {n: r[3] for n, r in rows.items()} == {"Python": "language", "Someone's YouTube Channel": "channel",
                                                  "Kaggle Learn: Pandas": "course", "Strix": "repo",
                                                  "Muse": "tool"}


def test_real_tool_catalog_loads_and_is_consistent():
    cat = p.load_tool_catalog()
    types = {"tool", "model", "repo", "language", "course", "company", "channel", "other"}
    assert cat["aliases"] and cat["entries"] and cat["stoplist"]
    assert all(e["type"] in types for e in cat["entries"].values())
    assert all(target in cat["entries"] for target in cat["aliases"].values()
               if target not in ("REA", "FreeLLMAPI", "SynthID Remover"))
    assert all(p.tool_link_ok(e["link"]) for e in cat["entries"].values() if "link" in e)
    assert p.clean_tools([("Higgs Field MCP", "", "a.md")]) == [("Higgsfield", "https://higgsfield.ai", 1, "tool")]


@pytest.mark.parametrize("name", ["30 Day Plan to Master Your Communication", "Phone Addict? (Start this tonight)",
                                  "Animated History Docs Guide", "Systematic Withdrawal Plan (SWP)",
                                  "AI CEO Challenge", "Claim Your Business", "SECU AUUIO 1.U",
                                  "Q3 Revenue Report", "B jobs_list.xlsx", "report.csv", "Guide.PDF"])
def test_real_catalog_drops_non_tools_and_file_names(name):
    assert p.clean_tools([(name, "", "a.md")]) == []


def test_real_catalog_aliases_chachibt_and_c_dance():
    rows = p.clean_tools([("ChachiBT", "", "a.md"), ("ChatGPT", "", "b.md"), ("C-Dance 2.5", "", "a.md")])
    assert rows == [("ChatGPT", "https://chatgpt.com", 2, "tool"), ("Seedance 2.5", "No repo found", 1, "model")]


def test_tools_empty_folder(notes):
    assert p.all_tools() == []


def test_long_tool_list_is_split():
    lines = [f"Tool {i} (1) https://github.com/a/tool-{i}" for i in range(300)]
    messages = p.split_messages(lines)
    assert len(messages) > 1 and all(len(m) <= 4000 for m in messages)
    assert "\n".join(messages).splitlines() == lines                          # nothing lost
