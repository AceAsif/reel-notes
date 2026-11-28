"""tools/chat_sim.py with the AI mocked: routing, buttons, sandbox. No network."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import chat_sim  # noqa: E402
import processor as p  # noqa: E402

INTENTS = {"I finished the Hallmark task": ("done", "Hallmark"), "skip the BLA one": ("skip", "BLA"),
           "show my todo list": ("todo", ""), "what tools do I have": ("tools", ""),
           "I finished the guitar practice task": ("done", "guitar practice"),
           "I have completed the Hallmark task": ("done", "Hallmark"),
           "I finished the orbit task": ("done", "orbit"),
           "I finished the Remotion task": ("done", "Remotion"),
           "what is Strix used for?": ("chat", "Strix")}


@pytest.fixture
def mocked_ai(monkeypatch):
    def intent(prompt, **k):
        message = prompt.rsplit("MESSAGE: ", 1)[1]
        kind, words = INTENTS[message]
        return {"intent": kind, "words": words}
    monkeypatch.setattr(p, "ask_ollama_json", intent)
    monkeypatch.setattr(p, "chat_reply", lambda m, h: ("Strix scans your code for security bugs.", []))


def test_all_scenarios_pass_with_a_well_behaved_model(mocked_ai, capsys):
    assert chat_sim.main(["--file", str(ROOT / "tests" / "chat_scenarios.txt")]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") >= 9 and "FAIL" not in out
    assert "[buttons: ✅ Yes, tick it | Not this one | Cancel]" in out
    assert "| Message | Intent | Reply | Result |" in out


def test_sandbox_never_touches_real_paths_and_puts_them_back(mocked_ai):
    before = {n: getattr(p, n) for n in ("NOTES_DIR", "PENDING_DIR", *chat_sim.STATE_FILES)}
    r = chat_sim.run_scenario({"message": "I finished the Hallmark task", "intent": "done",
                               "expect": "Ticked", "press": "✅ Yes, tick it"})
    assert r["ok"], r["problems"]
    assert {n: getattr(p, n) for n in before} == before
    assert not Path(str(before["NOTES_DIR"])).joinpath("2026-01-01_0900_hallmark-card-ideas.md").exists()


def test_wrong_intent_and_a_claimed_action_fail(monkeypatch):
    monkeypatch.setattr(p, "ask_ollama_json", lambda prompt, **k: {"intent": "chat", "words": ""})
    monkeypatch.setattr(p, "chat_reply", lambda m, h: ("I've marked it as done!", []))
    r = chat_sim.run_scenario({"message": "I finished the Hallmark task", "intent": "done",
                               "expect": "", "press": ""})
    assert not r["ok"]
    assert "intent chat, expected done" in r["problems"]
    assert "chat reply claims it changed something" in r["problems"]


def test_links_are_not_downloaded(mocked_ai):
    r = chat_sim.run_scenario({"message": "https://www.instagram.com/reel/ABC/", "intent": "",
                               "expect": "skipped", "press": ""})
    assert r["ok"] and r["got_intent"] == "(none)"


def test_only_local_ollama_is_allowed(mocked_ai):
    with chat_sim.sandbox():
        with pytest.raises(p.requests.exceptions.ConnectionError, match="blocks network"):
            p.requests.get("https://api.github.com/repos/a/b")
        with pytest.raises(p.requests.exceptions.ConnectionError, match="blocks network"):
            p.requests.post("https://api.telegram.org/bot123/sendMessage", json={})


def test_missing_button_is_reported(mocked_ai):
    r = chat_sim.run_scenario({"message": "show my todo list", "intent": "todo", "expect": "",
                               "press": "Delete everything"})
    assert not r["ok"] and 'could not press "Delete everything"' in r["problems"]
