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


def test_no_match_says_so_and_points_to_todo(notes, monkeypatch):
    path = make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "done", "Hallmark")
    chat = Chat()
    chat.send("I finished the Hallmark task")
    text, markup = chat.replies[0]
    assert "couldn't find" in text and "/todo" in text and markup is None
    assert box(path, "Run Strix on my repo") == "- [ ]"


def test_two_matches_not_this_one_shows_the_next(notes, monkeypatch):
    first = make_note("Strix security", ["Run Strix on my repo"], "https://x.com/a/status/1")
    second = make_note("Strix part two", ["Read the Strix docs"], "https://x.com/a/status/2")
    ai_says(monkeypatch, "done", "Strix")
    chat = Chat()
    chat.send("done with the strix one")
    assert "2 actions match" in chat.replies[0][0]
    shown_first = chat.replies[0][0]
    chat.press("chatact:next")
    assert chat.edits[-1][0] != shown_first and "Strix" in chat.edits[-1][0]
    chat.press("chatact:yes")
    texts = first.read_text(encoding="utf-8") + second.read_text(encoding="utf-8")
    assert texts.count("- [x] ") == 1 and texts.count("- [ ] ") == 1     # only the second one shown
    chat2 = Chat()
    chat2.send("done with the strix one")
    chat2.press("chatact:next")
    assert chat2.edits[-1][0].startswith("No other match. Nothing changed.")


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
