"""Doing tasks by chat: intent from the (mocked) local model, then buttons. No network."""
import asyncio
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
    monkeypatch.setattr(bot, "ASK_LEARNING", False)
    return folder


def make_note(title, actions, source):
    data = {"title": title, "category": "tech", "summary": "s", "key_points": ["k"], "resources": [],
            "tags": [], "claims": [], "action_items": p.clean_actions(actions),
            "quote": "", "lesson": "", "habit": ""}
    return p.save_note(data, "transcript", "screen", source)


def box(path, action):
    """The tick box of the line with this action: '- [ ]', '- [x]' or '- [-]'."""
    line = next(l for l in path.read_text(encoding="utf-8").splitlines() if action in l and l.startswith("- ["))
    return line[:5]


def ai_says(monkeypatch, intent, words=""):
    """Mock Ollama: the intent answer."""
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, **k: {"intent": intent, "words": words})


class Chat:
    """A fake Telegram chat: send a message, press a button, see the replies."""
    def __init__(self):
        self.replies, self.edits = [], []
        self.context = types.SimpleNamespace(
            user_data={}, chat_data={}, args=None,
            bot=types.SimpleNamespace(send_chat_action=self._nothing))

    async def _nothing(self, *a, **k):
        pass

    async def _reply(self, text, reply_markup=None, **k):
        self.replies.append((text, reply_markup))

    async def _edit(self, text, reply_markup=None, **k):
        self.edits.append((text, reply_markup))

    def send(self, text):
        msg = types.SimpleNamespace(text=text, reply_text=self._reply, reply_to_message=None)
        upd = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1),
                                    effective_chat=types.SimpleNamespace(id=1))
        asyncio.run(bot.chat(upd, self.context))

    def press(self, data):
        query = types.SimpleNamespace(data=data, answer=self._nothing, edit_message_text=self._edit,
                                      message=types.SimpleNamespace(reply_text=self._reply))
        upd = types.SimpleNamespace(callback_query=query, effective_user=types.SimpleNamespace(id=1))
        asyncio.run(bot.chat_action_pressed(upd, self.context))

    def buttons(self, markup):
        return [b.callback_data for b in markup.inline_keyboard[0]]


def test_i_finished_the_hallmark_task_asks_first_then_ticks(notes, monkeypatch):
    path = make_note("Hallmark cards tips", ["Send a Hallmark card to a friend"], "https://x.com/a/status/1")
    make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "done", "Hallmark")
    chat = Chat()
    chat.send("I finished the Hallmark task")
    text, markup = chat.replies[0]
    assert "Send a Hallmark card to a friend" in text and "Hallmark cards tips" in text
    assert chat.buttons(markup) == ["chatact:yes", "chatact:next", "chatact:no"]
    assert "- [ ] " in path.read_text(encoding="utf-8")                 # nothing changed yet
    chat.press("chatact:yes")
    assert chat.edits[-1][0] == "✅ Ticked: Send a Hallmark card to a friend (from Hallmark cards tips)"
    assert box(path, "Send a Hallmark card to a friend") == "- [x]"
    assert [a["action"] for a in p.open_actions()] == ["Run Strix on my repo"]


def test_skip_the_bla_one(notes, monkeypatch):
    path = make_note("BLA tools", ["Try the BLA command line"], "https://x.com/a/status/1")
    ai_says(monkeypatch, "skip", "BLA")
    chat = Chat()
    chat.send("skip the BLA one")
    assert chat.replies[0][0].startswith("Skip this action?")
    chat.press("chatact:yes")
    assert chat.edits[-1][0] == "⏭ Skipped: Try the BLA command line (from BLA tools)"
    assert box(path, "Try the BLA command line") == "- [-]"


def test_show_my_todo_list_runs_the_todo_command(notes, monkeypatch):
    make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "todo")
    monkeypatch.setattr(p, "chat_reply", lambda *a: pytest.fail("should not chat"))
    chat = Chat()
    chat.send("show my todo list")
    assert chat.replies[0][0] == bot.todo_page(1)[0]                    # exactly what /todo sends


@pytest.mark.parametrize("intent,expected", [("stats", lambda: bot.stats_text()),
                                             ("dupes", lambda: "👍 No duplicates: every video has one note.")])
def test_other_command_intents(notes, monkeypatch, intent, expected):
    ai_says(monkeypatch, intent)
    chat = Chat()
    chat.send("show my stats" if intent == "stats" else "any dupes?")
    assert chat.replies[0][0] == expected()


def test_find_note_uses_search(notes, monkeypatch):
    make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "find_note", "strix")
    chat = Chat()
    chat.send("find my notes about strix")
    assert chat.replies[0][0].startswith('🔍 1 note(s) for "strix"')


def test_show_note_opens_the_best_note(notes, monkeypatch):
    make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "show_note", "strix")
    chat = Chat()
    chat.send("open the strix note")
    assert chat.replies[0][0].startswith("# Strix security")


def test_no_match_shows_the_closest_actions_as_buttons(notes, monkeypatch):
    path = make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    for n in range(6):
        make_note(f"Note {n}", [f"Read chapter {n}"], f"https://x.com/a/status/{10 + n}")
    ai_says(monkeypatch, "done", "guitar practice")
    chat = Chat()
    chat.send("I finished the guitar practice task")
    text, markup = chat.replies[0]
    assert "couldn't find" in text and "Is it one of these?" in text
    data = [row[0].callback_data for row in markup.inline_keyboard]
    assert data == [f"chatact:pick:{k}" for k in range(5)] + ["chatact:no"]       # 5 closest + Cancel
    assert box(path, "Run Strix on my repo") == "- [ ]"                            # nothing changed


def test_two_notes_match_each_action_is_a_button_and_a_pick_asks_first(notes, monkeypatch):
    first = make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/1")
    second = make_note("Strix part two", ["Read the Strix docs"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "done", "Strix")
    chat = Chat()
    chat.send("done with the strix one")
    text, markup = chat.replies[0]
    assert text.startswith('2 open actions match "Strix"')
    labels = [row[0].text for row in markup.inline_keyboard]
    assert labels[-1] == "Cancel" and len(labels) == 3
    pick = next(k for k, l in enumerate(labels) if l.startswith("Read the Strix docs"))
    chat.press(f"chatact:pick:{pick}")
    assert "Read the Strix docs" in chat.edits[-1][0]                              # confirm first
    assert box(second, "Read the Strix docs") == "- [ ]"
    chat.press("chatact:yes")
    assert box(second, "Read the Strix docs") == "- [x]" and box(first, "Run Strix on my repo") == "- [ ]"


def test_one_note_with_several_actions_shows_each(notes, monkeypatch):
    make_note("Strix security", ["Run Strix on my repo", "Read the Strix report"], "https://x.com/a/status/1")
    ai_says(monkeypatch, "skip", "Strix")
    chat = Chat()
    chat.send("skip the strix one")
    labels = [row[0].text for row in chat.replies[0][1].inline_keyboard]
    assert [l.split(" (")[0] for l in labels[:-1]] == ["Run Strix on my repo", "Read the Strix report"]


def make_rich_note(title, action, source, resources=(), tags=(), summary="s"):
    data = {"title": title, "category": "tech", "summary": summary, "key_points": ["k"],
            "resources": list(resources), "tags": list(tags), "claims": [],
            "action_items": p.clean_actions([action]), "quote": "", "lesson": "", "habit": ""}
    return p.save_note(data, "transcript", "screen", source)


def test_word_only_in_resources_matches(notes):
    make_rich_note("Claude Code Makes Premium Websites", "Build a landing page with Claude Code",
                   "https://x.com/a/status/1", resources=[{"name": "hallmark",
                                                          "link": "https://github.com/Nutlope/hallmark"}])
    make_rich_note("Strix security", "Run Strix on my repo", "https://x.com/a/status/2")
    assert [a["action"] for a in p.match_actions("I have completed the Hallmark task")] == \
        ["Build a landing page with Claude Code"]


def test_word_only_in_file_name_summary_or_tags_matches(notes):
    path = make_rich_note("Weekly planning tips", "Plan next week on Sunday", "https://x.com/a/status/1")
    path.rename(path.with_name("2026-01-01_0900_orbit-planner.md"))
    make_rich_note("Sleep better", "Go to bed at ten", "https://x.com/a/status/2", summary="A zenith routine.")
    make_rich_note("Morning", "Drink water first", "https://x.com/a/status/3", tags=["hydration"])
    assert [a["action"] for a in p.match_actions("orbit")] == ["Plan next week on Sunday"]
    assert [a["action"] for a in p.match_actions("zenith")] == ["Go to bed at ten"]
    assert [a["action"] for a in p.match_actions("hydration")] == ["Drink water first"]


def test_action_and_title_matches_rank_above_resource_matches(notes):
    make_rich_note("Video tools", "Install the editor", "https://x.com/a/status/1",
                   resources=[{"name": "Remotion", "link": "https://www.remotion.dev"}])
    make_rich_note("Remotion basics", "Make a 10 second intro", "https://x.com/a/status/2")
    assert [a["action"] for a in p.match_actions("remotion")] == ["Make a 10 second intro", "Install the editor"]


def test_filler_words_alone_match_nothing(notes):
    make_rich_note("Strix security", "Run Strix on my repo", "https://x.com/a/status/1")
    assert p.match_actions("I have completed the task") == []


def test_cancel_changes_nothing(notes, monkeypatch):
    path = make_note("Hallmark cards tips", ["Send a Hallmark card"], "https://x.com/a/status/1")
    before = path.read_text(encoding="utf-8")
    ai_says(monkeypatch, "done", "hallmark")
    chat = Chat()
    chat.send("I finished the Hallmark task")
    chat.press("chatact:no")
    assert chat.edits[-1][0] == "OK, nothing changed." and path.read_text(encoding="utf-8") == before
    chat.press("chatact:yes")                                            # an old button: still nothing
    assert path.read_text(encoding="utf-8") == before


def test_fuzzy_match_on_a_typo(notes):
    make_note("Hallmark cards tips", ["Send a Hallmark card"], "https://x.com/a/status/1")
    assert [a["action"] for a in p.match_actions("the halmark task")] == ["Send a Hallmark card"]


def test_odd_intent_from_the_model_is_chat(monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, **k: {"intent": "delete_everything", "words": 3})
    assert p.detect_intent("show me everything") == {"intent": "chat", "words": "3"}


def test_chat_reply_never_claims_an_action(notes, monkeypatch):
    sent = {}
    def fake_post(url, json, timeout):
        sent["system"] = json["messages"][0]["content"]
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "message": {"content": sent["reply"]}})
    monkeypatch.setattr(p.requests, "post", fake_post)
    for claim in ("Great job! I've marked the Hallmark task as done.", "Your task has been completed.",
                  "The Hallmark task is marked.", "It has been ticked off.", "That one is now done.",
                  "Done! Nice work.", "You're all set."):
        sent["reply"] = claim
        reply, _ = p.chat_reply("well done me", [])
        assert reply == "I can't change tasks in chat. Try: I finished <task>, or /done.", claim
    assert "never say you marked" in sent["system"].lower().replace("\n  ", " ")


@pytest.mark.parametrize("reply", [
    "Well done! Strix scans code for security bugs.", "The note says Strix is open source.",
    "You can mark it with /done 2."])
def test_normal_replies_are_not_taken_as_claims(reply):
    assert not p.CLAIMED_ACTION_RE.search(reply)


@pytest.mark.parametrize("message,asks_ai", [
    ("hello", False), ("what is Strix used for?", False), ("thanks!", False),
    ("I finished the Hallmark task", True), ("I have completed it", True), ("skip the BLA one", True),
    ("show my todo list", True), ("what tools do I have", True), ("how did I do this week?", True),
    ("which videos did I save twice", True)])
def test_intent_ai_is_only_asked_when_a_task_word_is_there(monkeypatch, message, asks_ai):
    calls = []
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, **k: calls.append(1) or {"intent": "todo"})
    result = p.detect_intent(message)
    assert bool(calls) is asks_ai
    if not asks_ai:
        assert result == {"intent": "chat", "words": ""}


def test_normal_chat_still_works_and_changes_nothing(notes, monkeypatch):
    path = make_note("Hallmark cards tips", ["Send a Hallmark card"], "https://x.com/a/status/1")
    ai_says(monkeypatch, "chat")
    monkeypatch.setattr(p, "chat_reply", lambda m, h: ("Hello! Nice to see you.", []))
    chat = Chat()
    chat.send("hello")
    assert chat.replies == [("Hello! Nice to see you.", None)]
    assert box(path, "Send a Hallmark card") == "- [ ]"


def test_ai_down_falls_back_to_chat(notes, monkeypatch):
    monkeypatch.setattr(p, "chat_reply", lambda m, h: ("ok", []))         # requests.post fails in tests
    chat = Chat()
    chat.send("hello")
    assert chat.replies == [("ok", None)]
