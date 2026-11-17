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
                       ("SENT_JOBS_FILE", "sent.json"), ("REMINDERS_FILE", "reminders.json")):
        monkeypatch.setattr(processor, name, tmp_path / "private" / file, raising=False)
    (tmp_path / "private").mkdir()
