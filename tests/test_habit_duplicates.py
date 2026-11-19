"""One idea = one to-do: a habit and an action that say the same thing (from a real note)."""
import os

import pytest

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")

import bot  # noqa: E402
import processor as p  # noqa: E402

# the pair from a real motivation note
HABIT = "Every morning, write down one limiting belief and replace it with a positive one."
ACTION = "Write down one belief that limits you and replace it with a positive one."


@pytest.fixture
def notes(tmp_path, monkeypatch):
    folder = tmp_path / "notes"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "enrich_with_github", lambda r, c, t: r)
    return folder


def note_data(habit=HABIT, actions=(), category="motivation", other=(), title="Change Your Thoughts",
              **extra):
    data = {"title": title, "category": category, "summary": "s",
            "key_points": ["k"], "resources": [], "tags": ["mindset"], "claims": [],
            "action_items": p.clean_actions(list(actions)), "other_ideas": list(other),
            "quote": "", "lesson": "", "habit": habit}
    data.update(extra)
    return data


def save(data, source="https://x/1"):
    return p.save_note(data, "transcript", "screen", source)


def model_answer(habit=HABIT, actions=(), category="motivation"):
    return {"title": "Change Your Thoughts", "category": category, "summary": "s", "key_points": ["k"],
            "resources": [], "tags": [], "claims": [], "habit": habit, "lesson": "l", "quote": "",
            "action_items": [{"text": t, "priority": pr, "type": "habit"} for t, pr in actions]}


# ---- are two lines the same idea? ------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    (HABIT, ACTION),
    ("Each night, write three things you are grateful for.", "Write down three things you are grateful for."),
    ("Every Monday, pick one task slightly harder than last week's and finish it.",
     "Pick one task that is harder than last week's and finish it."),
    ("Spend 10 minutes every day reading a book.", "Read a book for 10 minutes."),
])
def test_same_idea(a, b):
    assert p.similar_idea(a, b) and p.similar_idea(b, a)


@pytest.mark.parametrize("a,b", [
    (HABIT, "Install Ollama and pull the qwen3 model."),
    ("Journal every night about what went well today.", ACTION),
    ("Every morning, write 3 goals for the day.", "Write a prompt that asks Claude to plan my week."),
    ("Meditate for five minutes each morning.", "Meditate on your goals and write them down."),
    ("Every day, walk for 20 minutes.", "Walk through the Strix README and run the demo."),
    ("", ACTION),
    ("Do it", "Do it"),                       # too few words to say anything
])
def test_different_ideas(a, b):
    assert not p.similar_idea(a, b)


# ---- new notes: one entry --------------------------------------------------------------------

def test_new_note_keeps_one_entry_with_the_actions_priority(notes, monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: model_answer(
        actions=[(ACTION, "high")]))
    data = p.summarise("words", "", "")
    assert data["action_items"] == [] and data["habit"] == HABIT and data["habit_priority"] == "high"
    save(data)
    text = next(notes.glob("*.md")).read_text(encoding="utf-8")
    assert f"## Habit to try\n- [ ] 🔥 🧠 {HABIT}\n" in text
    open_now = p.open_actions()
    assert len(open_now) == 1                                      # ONE to-do, not two
    assert (open_now[0]["priority"], open_now[0]["kind"], open_now[0]["action"]) == ("high", "habit", HABIT)
    assert open_now[0]["section"] == "Habit to try"


def test_a_different_action_stays_next_to_the_habit(notes, monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: model_answer(
        actions=[("Read the first chapter of Atomic Habits", "normal")]))
    data = p.summarise("words", "", "")
    assert [a["text"] for a in data["action_items"]] == ["Read the first chapter of Atomic Habits"]
    assert "habit_priority" not in data
    save(data)
    assert "- [ ] " + HABIT + "\n" in next(notes.glob("*.md")).read_text(encoding="utf-8")   # no icons
    assert len(p.open_actions()) == 2


def test_best_priority_wins_and_a_repeated_other_idea_is_dropped(notes):
    data = note_data(actions=[{"text": ACTION, "priority": "low"},
                              {"text": "Write one belief that limits you, replace it with a positive one",
                               "priority": "high"},
                              {"text": "Install Ollama", "priority": "normal"}],
                     other=["Replace a limiting belief with a positive one: write it down",
                            "Watch the full talk"])
    p.merge_habit_and_actions(data)
    assert [a["text"] for a in data["action_items"]] == ["Install Ollama"]
    assert data["habit_priority"] == "high"
    assert data["other_ideas"] == ["Watch the full talk"]


def test_no_habit_means_nothing_changes(notes):
    data = note_data(habit="", actions=[ACTION])
    p.merge_habit_and_actions(data)
    assert len(data["action_items"]) == 1 and "habit_priority" not in data


def test_tech_notes_have_no_habit_so_nothing_is_merged(notes, monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, schema=None: model_answer(
        actions=[(ACTION, "high")], category="tech"))
    data = p.summarise("words", "", "")
    assert data["habit"] == "" and len(data["action_items"]) == 1


def test_telegram_reply_shows_the_habit_once(notes):
    data = note_data(actions=[{"text": ACTION, "priority": "high"}])
    p.merge_habit_and_actions(data)
    text = bot.format_reply(data, save(data))
    assert "🔁 Habit to try: 🔥 🧠 " + HABIT in text
    assert "Action items" not in text and text.count("write down one") == 1


# ---- old notes: /cleanup finds the pair ---------------------------------------------------------

def old_note_with_pair(habit_due=None, action_due=None, source="https://x/old", other_actions=()):
    data = note_data(actions=[ACTION, *other_actions])
    path = save(data, source)
    lines = path.read_text(encoding="utf-8").splitlines()
    if habit_due:
        i = next(n for n, ln in enumerate(lines) if ln == f"- [ ] {HABIT}")
        lines[i] += f" 📅 {habit_due}"
    if action_due:
        i = next(n for n, ln in enumerate(lines) if ln.startswith("- [ ] ") and ACTION in ln)
        lines[i] += f" 📅 {action_due}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_old_pair_is_two_to_dos_and_cleanup_skips_the_habit(notes):
    old_note_with_pair()
    assert len(p.open_actions()) == 2
    plan = p.cleanup_plan()
    assert (plan["dups"], plan["junk"], plan["extras"], plan["left"]) == (1, 0, 0, 1)
    p.skip_with_undo(plan["ids"])
    left = p.open_actions()
    assert [a["action"] for a in left] == [ACTION]                  # the action stays
    assert HABIT in next(notes.glob("*.md")).read_text(encoding="utf-8")      # the note is not changed otherwise
    assert p.cleanup_plan()["ids"] == []                            # nothing more to do


def test_cleanup_can_be_undone(notes):
    old_note_with_pair()
    p.skip_with_undo(p.cleanup_plan()["ids"])
    assert len(p.open_actions()) == 1
    assert p.undo_cleanup() == 1
    assert len(p.open_actions()) == 2


def test_if_only_the_habit_has_a_due_date_the_action_is_skipped(notes):
    old_note_with_pair(habit_due="2026-12-01")
    plan = p.cleanup_plan()
    assert plan["dups"] == 1
    p.skip_with_undo(plan["ids"])
    assert [a["action"] for a in p.open_actions()] == [HABIT]


def test_a_habit_that_repeats_an_extra_action_is_not_skipped_with_it(notes):
    # the note has two actions: the best one is kept, the extra repeats the habit
    old_note_with_pair(other_actions=["Install Ollama and pull the qwen3 model"])
    data_lines = next(notes.glob("*.md")).read_text(encoding="utf-8")
    assert data_lines.count("- [ ]") == 3
    plan = p.cleanup_plan()
    p.skip_with_undo(plan["ids"])
    left = [a["action"] for a in p.open_actions()]
    assert len(left) == len(set(left)) == plan["left"]
    assert any(p.similar_idea(HABIT, a) for a in left)             # the idea is still on the list once


def test_two_different_notes_are_never_compared(notes):
    save(note_data(habit=HABIT, actions=[], title="First note"), "https://x/a")
    save(note_data(habit="", actions=[ACTION], title="Second note"), "https://x/b")
    assert p.cleanup_plan()["dups"] == 0 and len(p.open_actions()) == 2


def test_a_habit_alone_or_a_different_action_is_left_alone(notes):
    save(note_data(actions=["Read the first chapter of Atomic Habits"]), "https://x/c")
    assert p.cleanup_plan()["dups"] == 0 and len(p.open_actions()) == 2


def test_cleanup_message_mentions_the_pair_only_when_there_is_one(notes):
    old_note_with_pair()
    text = bot.cleanup_text(p.cleanup_plan())
    assert "1 are the same idea twice (a habit and an action)" in text
    p.skip_with_undo(p.cleanup_plan()["ids"])
    assert "same idea twice" not in bot.cleanup_text(p.cleanup_plan())


# ---- /plan --------------------------------------------------------------------------------------

def test_plan_lists_the_idea_once_for_an_old_note(notes):
    path = old_note_with_pair()
    plan = p.make_plan(path)
    assert len(p.plan_parts(path)["actions"]) == 1
    assert plan.count("replace it with a positive one") == 1        # the idea is in the prompt once
