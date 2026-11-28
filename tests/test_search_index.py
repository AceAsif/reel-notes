"""Search by meaning: search_index.json, the mixed score and the exact-word fallback. No network."""
import importlib.util
import json
from pathlib import Path

import pytest
import requests

import processor as p

WORDS = ["cooking", "coding", "travel"]


def fake_embed(calls):
    def embed(texts, prefix):
        calls.append((prefix, list(texts)))
        # one number per topic word; "recipe" means cooking, so meaning finds it without the word
        return [[float(w in t.lower() or (w == "cooking" and "recipe" in t.lower())) + 0.01
                 for w in WORDS] for t in texts]
    return embed


@pytest.fixture
def notes(tmp_path, monkeypatch):
    folder = tmp_path / "notesdir"
    folder.mkdir()
    monkeypatch.setattr(p, "NOTES_DIR", folder)
    monkeypatch.setattr(p, "SEARCH_INDEX_FILE", tmp_path / "search_index.json")
    calls = []
    monkeypatch.setattr(p, "embed", fake_embed(calls))
    return folder, calls


def write(folder, name, title, summary, transcript="long words here"):
    path = folder / name
    path.write_text(f"# {title}\n- Source: screenshot\n\n## Summary\n{summary}\n\n"
                    f"## Key points\n- point\n\n## Transcript\n{transcript}\n", encoding="utf-8")
    return path


def test_embed_text_skips_transcript(notes):
    folder, _ = notes
    path = write(folder, "2026-11-01 a.md", "Pasta", "A quick recipe", transcript="secret travel talk")
    text = p.note_embed_text(path)
    assert "Pasta" in text and "A quick recipe" in text and "- point" in text
    assert "travel" not in text


def test_index_embeds_only_new_or_changed_notes(notes):
    folder, calls = notes
    a = write(folder, "2026-11-01 a.md", "Pasta", "A recipe")
    write(folder, "2026-11-02 b.md", "Python", "Coding tips")
    data = p.sync_search_index()
    assert set(data["notes"]) == {a.name, "2026-11-02 b.md"}
    assert calls[0][0] == "search_document: " and len(calls[0][1]) == 2
    p.sync_search_index()
    assert len(calls) == 1                       # nothing changed: no new embedding
    write(folder, a.name, "Pasta", "A recipe for travel")
    p.sync_search_index()
    assert len(calls[1][1]) == 1                 # only the changed note
    a.unlink()
    saved = json.loads(p.SEARCH_INDEX_FILE.read_text(encoding="utf-8"))
    assert set(p.sync_search_index()["notes"]) == {"2026-11-02 b.md"} != set(saved["notes"])


def test_new_model_or_broken_file_rebuilds(notes, monkeypatch):
    folder, calls = notes
    write(folder, "2026-11-01 a.md", "Pasta", "A recipe")
    p.sync_search_index()
    monkeypatch.setattr(p, "EMBED_MODEL", "other-model")
    assert p.sync_search_index()["model"] == "other-model" and len(calls) == 2
    p.SEARCH_INDEX_FILE.write_text("{not json", encoding="utf-8")
    p.sync_search_index()
    assert len(calls) == 3


def test_first_build_keeps_progress_when_a_batch_fails(notes, monkeypatch):
    folder, calls = notes
    for i in range(40):
        write(folder, f"2026-11-{i:02d} n.md", f"Note {i}", "coding")
    ok = fake_embed(calls)

    def second_fails(texts, prefix):
        if calls:
            raise requests.Timeout("slow")
        return ok(texts, prefix)
    monkeypatch.setattr(p, "embed", second_fails)
    with pytest.raises(requests.Timeout):
        p.sync_search_index()
    saved = json.loads(p.SEARCH_INDEX_FILE.read_text(encoding="utf-8"))
    assert len(saved["notes"]) == 32


def test_save_is_atomic(notes, monkeypatch):
    folder, _ = notes
    write(folder, "2026-11-01 a.md", "Pasta", "A recipe")
    p.sync_search_index()
    good = p.SEARCH_INDEX_FILE.read_text(encoding="utf-8")
    write(folder, "2026-11-02 b.md", "Python", "Coding")
    monkeypatch.setattr(p.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    p.sync_search_index()                        # logs, does not crash
    assert p.SEARCH_INDEX_FILE.read_text(encoding="utf-8") == good


def test_meaning_search_finds_note_without_the_word(notes):
    folder, calls = notes
    write(folder, "2026-11-01 a.md", "Pasta night", "A quick recipe")
    write(folder, "2026-11-02 b.md", "Python", "Coding tips")
    found = p.meaning_search("cooking")
    assert found[0]["title"] == "Pasta night"
    assert calls[-1] == ("search_query: ", ["cooking"])
    assert all(0 <= r["score"] <= 1 for r in found)


def test_exact_words_scaled_and_mixed(notes, monkeypatch):
    folder, _ = notes
    write(folder, "2026-11-01 a.md", "Coding coding", "coding")
    write(folder, "2026-11-02 b.md", "Coding", "x")
    monkeypatch.setattr(p, "embed", lambda texts, prefix: [[1.0, 0.0, 0.0] for _ in texts])
    found = p.meaning_search("coding")           # same meaning score: more words wins
    assert found[0]["path"].name == "2026-11-01 a.md"
    assert found[0]["score"] == pytest.approx(1.0)


def test_falls_back_to_exact_words_when_ollama_is_down(notes, monkeypatch):
    folder, _ = notes
    write(folder, "2026-11-01 a.md", "Pasta", "A recipe")
    write(folder, "2026-11-02 b.md", "Python", "Coding tips")

    def down(texts, prefix):
        raise requests.ConnectionError("no ollama")
    monkeypatch.setattr(p, "embed", down)
    found = p.meaning_search("coding")
    assert [r["title"] for r in found] == ["Python"] and found[0]["score"] == 1.0


def test_hook_treats_index_as_private():
    path = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "pre_commit_check.py"
    spec = importlib.util.spec_from_file_location("pcc", path)
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    assert "search_index.json" in hook.PRIVATE_NAMES
    assert hook.PRIVATE_IN_COMMAND_RE.search("cat search_index.json")
