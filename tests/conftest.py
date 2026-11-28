"""Shared test setup: no test may read or write the bot's real private files."""
import sys
import types
from pathlib import Path

import pytest

sys.modules.setdefault("pytesseract", types.SimpleNamespace(pytesseract=types.SimpleNamespace()))
sys.modules.setdefault("faster_whisper", types.SimpleNamespace(WhisperModel=None))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def private_files_in_tmp(tmp_path, monkeypatch):
    import processor
    for name, file in (("STATE_FILE", "state.json"), ("CLEANUP_UNDO_FILE", "undo.json"),
                       ("SENT_JOBS_FILE", "sent.json"), ("REMINDERS_FILE", "reminders.json"),
                       ("LINK_INDEX_FILE", "link_index.json")):
        monkeypatch.setattr(processor, name, tmp_path / "private" / file, raising=False)
    monkeypatch.setattr(processor, "PENDING_DIR", tmp_path / "private" / "pending", raising=False)
    # no test may reach a real Ollama on this PC: a test that needs the AI mocks requests.post itself
    def no_network(*a, **k):
        raise processor.requests.exceptions.ConnectionError("no network in tests")
    monkeypatch.setattr(processor.requests, "post", no_network)
    (tmp_path / "private").mkdir()
